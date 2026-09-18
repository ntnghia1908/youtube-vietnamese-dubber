"""Stage: tổng hợp giọng nói — ``translated.json`` -> ``tts/*.mp3`` — Checkpoint 4.

Resume/cache theo từng segment (plan §13): mỗi segment được gán một
``cache_key = hash(provider + voice + rate + volume + text)`` (xem
``app.tts.base.TTSEngine.cache_key``). Sửa một câu dịch chỉ đổi cache_key
của đúng câu đó -> chỉ câu đó bị tổng hợp lại; đổi voice/rate/volume đổi
cache_key của mọi câu -> tổng hợp lại tất cả.

Ba lớp an toàn giống stage dịch (CP3, xem ``docs/decisions/checkpoint-3.md``
mục C):
- Ghi file mp3 và manifest atomic (``*.tmp`` rồi ``os.replace``) -> bị kill
  giữa chừng không để lại artifact cụt bị hiểu nhầm là "đã xong".
- Một segment lỗi hết lượt không dừng cả stage (``failed_ids``), trừ khi
  segment lỗi đầu tiên (fail fast) -> khả năng cao là voice sai/mất mạng,
  dừng ngay để khỏi tốn N segment x max_attempts lần thử vô ích.
- Manifest được ghi lại sau mỗi segment xong, từ thread chính, nên kill
  giữa chừng chỉ mất đúng phần chưa ghi.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.translation.base import TranslationError
from app.translation.translate import TranslatedSegment, read_translated
from app.tts.base import TTSEngine, TTSError

TTS_DIRNAME = "tts"
MANIFEST_FILENAME = "manifest.json"

# Chờ giữa các lần thử: giống stage dịch (plan §24) — 2s rồi 5s, các lần
# sau (nếu max_attempts > 3) tiếp tục chờ 5s.
_RETRY_DELAYS = (2.0, 5.0)
_ORPHAN_RE = re.compile(r"^\d{6}\.mp3$")


def segment_filename(segment_id: int) -> str:
    return f"{segment_id:06d}.mp3"


@dataclass(frozen=True)
class TTSResult:
    manifest_path: Path
    synthesized_ids: list[int] = field(default_factory=list)  # gọi TTS lần này
    cached_ids: list[int] = field(default_factory=list)  # dùng lại file cũ
    empty_ids: list[int] = field(default_factory=list)  # bỏ qua vì text rỗng
    failed_ids: list[int] = field(default_factory=list)
    skipped: bool = False


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    # Copy từ app/translation/translate.py:_write_json_atomic (hàm private,
    # không import) — cùng lý do: file cụt do bị kill giữa chừng sẽ bị coi
    # là "đã xong" và skip mãi nếu không ghi atomic.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _is_empty_text(text: str) -> bool:
    # "..." hay các dấu câu trần: edge-tts trả NoAudioReceived, coi như rỗng
    # để khỏi tốn lượt gọi mạng chắc chắn lỗi.
    return not text or not any(c.isalnum() for c in text)


def _read_failed_ids(translated_path: Path) -> set[int]:
    """Đọc ``failed_ids`` trực tiếp từ JSON — chỉ để log, không phải contract.

    ``read_translated`` không trả field này (xem ``TranslatedSegment``), nên
    đọc lại file (đã được xác nhận parse được ở bước trước) để lấy thêm
    thông tin cho dòng log ở hành vi #2. Lỗi ở đây không nên làm hỏng cả
    stage vì chỉ ảnh hưởng một dòng log, nên bỏ qua lặng lẽ nếu có sự cố.
    """
    try:
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        return {int(i) for i in data.get("failed_ids", [])}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return set()


def _cached_entry(
    old_entry: dict[str, Any] | None, cache_key: str, tts_dir: Path
) -> dict[str, Any] | None:
    if not old_entry or old_entry.get("status") != "ok":
        return None
    if old_entry.get("cache_key") != cache_key:
        return None
    file_name = old_entry.get("file")
    if not file_name:
        return None
    try:
        if (tts_dir / file_name).stat().st_size <= 0:
            return None
    except OSError:
        return None
    return old_entry


def _synthesize_with_retry(
    engine: TTSEngine,
    text: str,
    tmp_path: Path,
    final_path: Path,
    *,
    max_attempts: int,
    sleep: Callable[[float], None],
    label: str,
    log: Callable[[str], None],
) -> tuple[bool, str | None]:
    """Thử tổng hợp tối đa ``max_attempts`` lần. Trả (thành công, lỗi cuối)."""
    last_error: str | None = "không rõ lỗi"
    for attempt in range(1, max_attempts + 1):
        try:
            if tmp_path.exists():
                tmp_path.unlink()
            engine.synthesize(text, tmp_path)
            size = tmp_path.stat().st_size if tmp_path.exists() else 0
            if size <= 0:
                # File cụt sau khi bị kill/lỗi giữa chừng không được coi là
                # cache hợp lệ — cùng lý do phải retry như mọi lỗi khác.
                raise TTSError("engine không ghi được audio (file rỗng)")
        except TTSError as exc:
            last_error = str(exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if attempt < max_attempts:
                delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                log(f"[tts] {label} lần {attempt}/{max_attempts} lỗi: {exc} — thử lại sau {delay:g}s")
                sleep(delay)
            continue
        os.replace(tmp_path, final_path)
        return True, None
    return False, last_error


def _run_one(
    engine: TTSEngine,
    seg_id: int,
    text: str,
    tts_dir: Path,
    *,
    max_attempts: int,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> tuple[dict[str, Any], float]:
    final_path = tts_dir / segment_filename(seg_id)
    tmp_path = final_path.with_name(final_path.name + ".tmp")
    started = time.monotonic()
    ok, error = _synthesize_with_retry(
        engine, text, tmp_path, final_path,
        max_attempts=max_attempts, sleep=sleep, label=f"id {seg_id}", log=log,
    )
    elapsed = time.monotonic() - started
    if ok:
        entry = {
            "id": seg_id,
            "status": "ok",
            "file": final_path.name,
            "cache_key": engine.cache_key(text),
            "text": text,
        }
    else:
        entry = {
            "id": seg_id,
            "status": "failed",
            "file": None,
            "cache_key": None,
            "text": text,
            "error": error,
        }
    return entry, elapsed


def synthesize_translation(
    translated_path: Path,
    tts_dir: Path,
    engine: TTSEngine,
    *,
    max_attempts: int = 3,
    concurrency: int = 4,
    force: bool = False,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> TTSResult:
    translated_path = Path(translated_path)
    tts_dir = Path(tts_dir)
    manifest_path = tts_dir / MANIFEST_FILENAME

    if not translated_path.exists():
        raise TTSError(
            f"Không tìm thấy {translated_path}. Chạy `translate` cho episode này trước."
        )
    try:
        _source_language, _target_language, segments = read_translated(translated_path)
    except TranslationError as exc:
        raise TTSError(str(exc)) from exc

    tts_dir.mkdir(parents=True, exist_ok=True)
    # Đầu stage: xoá mọi *.tmp sót lại (vd bị kill giữa lúc ghi lần trước).
    for tmp in tts_dir.glob("*.tmp"):
        tmp.unlink(missing_ok=True)

    log(f"[tts] provider={engine.provider} voice={engine.voice} rate={engine.rate} volume={engine.volume}")

    old_manifest: dict[int, dict[str, Any]] = {}
    if not force and manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_manifest = {int(e["id"]): e for e in data.get("segments", [])}
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            log(f"[tts] manifest cũ ở {manifest_path} hỏng — bỏ qua, tổng hợp lại từ đầu.")

    results: dict[int, dict[str, Any]] = {}
    cached_ids: list[int] = []
    empty_ids: list[int] = []
    pending: list[TranslatedSegment] = []
    text_map: dict[int, str] = {}

    for seg in segments:
        text = seg.translated_text.strip()
        text_map[seg.id] = text
        if _is_empty_text(text):
            empty_ids.append(seg.id)
            results[seg.id] = {
                "id": seg.id, "status": "empty", "file": None, "cache_key": None, "text": text,
            }
            continue
        cache_key = engine.cache_key(text)
        cached = None if force else _cached_entry(old_manifest.get(seg.id), cache_key, tts_dir)
        if cached is not None:
            cached_ids.append(seg.id)
            results[seg.id] = cached
        else:
            pending.append(seg)

    def write_manifest() -> None:
        _write_json_atomic(
            manifest_path,
            {
                "provider": engine.provider,
                "voice": engine.voice,
                "rate": engine.rate,
                "volume": engine.volume,
                "segments": [results[s.id] for s in segments if s.id in results],
            },
        )

    if empty_ids:
        translate_failed_ids = _read_failed_ids(translated_path)
        due_to_translate = sorted(set(empty_ids) & translate_failed_ids)
        log(
            f"[tts] {len(empty_ids)} segment rỗng, bỏ qua"
            + (
                f" (trong đó {len(due_to_translate)} do dịch lỗi — chạy lại "
                f"`translate` nếu muốn có giọng cho các câu này: id {due_to_translate})."
                if due_to_translate
                else "."
            )
        )
    if cached_ids:
        log(f"[tts] {len(cached_ids)} segment dùng lại từ cache.")
    write_manifest()

    synthesized_ids: list[int] = []
    failed_ids: list[int] = []
    total = len(segments)
    progress = len(cached_ids) + len(empty_ids)

    def record(seg_id: int, entry: dict[str, Any], elapsed: float) -> None:
        nonlocal progress
        progress += 1
        results[seg_id] = entry
        write_manifest()
        if entry["status"] == "ok":
            synthesized_ids.append(seg_id)
            log(f"[tts] {progress}/{total} id={seg_id} ok ({elapsed:.1f}s)")
        else:
            failed_ids.append(seg_id)
            log(f"[tts] {progress}/{total} id={seg_id} failed: {entry['error']}")

    # Có segment cache hợp lệ (dùng lại từ manifest cũ) tức là voice/mạng/
    # cấu hình từng chạy được với engine này -- một segment cụ thể lỗi hết
    # lượt lúc đó nhiều khả năng do chính segment đó (network chập chờn
    # đúng lúc, hoặc text khó), không phải cấu hình hỏng. Chỉ fail-fast khi
    # KHÔNG có bằng chứng nào như vậy (lần chạy đầu của episode), tránh
    # resume playlist bị chặn vĩnh viễn mỗi khi đúng segment đầu tiên cần
    # đọc lại là một segment từng lỗi dai dẳng.
    have_working_proof = bool(cached_ids)

    remaining = pending
    if pending:
        # Fail fast: tổng hợp segment cần gọi TTS đầu tiên một mình trước,
        # tuần tự. Voice sai / mất mạng thì lỗi ngay ở đây, tránh N segment
        # x max_attempts lần thử vô ích trước khi biết cấu hình hỏng.
        first = pending[0]
        entry, elapsed = _run_one(
            engine, first.id, text_map[first.id], tts_dir,
            max_attempts=max_attempts, sleep=sleep, log=log,
        )
        record(first.id, entry, elapsed)
        if entry["status"] != "ok" and not have_working_proof:
            raise TTSError(
                f"Không tổng hợp được segment đầu tiên (id {first.id}) sau {max_attempts} lần "
                f"thử: {entry['error']}. Kiểm tra kết nối mạng và tên voice (`--voice`) rồi thử lại."
            )
        remaining = pending[1:]

    if remaining:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {
                pool.submit(
                    _run_one, engine, seg.id, text_map[seg.id], tts_dir,
                    max_attempts=max_attempts, sleep=sleep, log=log,
                ): seg
                for seg in remaining
            }
            for future in as_completed(futures):
                seg = futures[future]
                entry, elapsed = future.result()
                record(seg.id, entry, elapsed)

    # Cùng lý do với fail-fast ở trên: chỉ coi "toàn bộ lỗi" là dấu hiệu
    # cấu hình hỏng khi không có cache nào chứng minh engine từng chạy được.
    # Có cache mà mọi segment thiếu trong lần chạy này đều lỗi (vd đúng lúc
    # mạng chập chờn) thì vẫn chỉ ghi `failed_ids`, không chặn cả episode.
    if pending and not synthesized_ids and not have_working_proof:
        raise TTSError(
            f"Toàn bộ {len(pending)} segment cần tổng hợp đều lỗi — "
            "kiểm tra kết nối mạng / tên voice rồi thử lại."
        )

    write_manifest()

    # Dọn file mồ côi: id biến mất khỏi translated.json hoặc câu nay rỗng.
    ok_files = {e["file"] for e in results.values() if e["status"] == "ok" and e.get("file")}
    for f in tts_dir.iterdir():
        if f.is_file() and _ORPHAN_RE.match(f.name) and f.name not in ok_files:
            f.unlink()

    skipped = not pending and not failed_ids
    return TTSResult(
        manifest_path=manifest_path,
        synthesized_ids=synthesized_ids,
        cached_ids=cached_ids,
        empty_ids=empty_ids,
        failed_ids=failed_ids,
        skipped=skipped,
    )

"""Stage: chuẩn hoá timing — ``translated.json`` + ``tts/*.mp3`` -> ``normalized.json``
— Checkpoint 5.

Mục tiêu: câu tiếng Việt đọc lâu hơn slot gốc (``end - start``) thì bị đè
sang câu sau khi ghép track. Đo độ dài thật từng file TTS bằng ``ffprobe``,
so với slot, rồi co giãn nhẹ bằng ``ffmpeg atempo`` cho những câu hơi dài
(``stretched``). Câu dài quá mức co giãn cho phép vẫn được tăng tốc tối đa
rồi đánh dấu ``too_long`` (còn tràn — rút gọn câu bằng LLM là việc của CP9,
xem "Ngoài phạm vi" ở spec CP5).

Quyết định đã chốt (xem ``docs/decisions/checkpoint-5.md`` mục A):
- Co giãn bằng ``ffmpeg atempo`` cục bộ, không gọi lại TTS với ``rate``
  khác — không tốn mạng, tempo tính chính xác theo tỷ lệ đo được.
- CP5 tự ``ffprobe`` từng file (CP4 không ghi ``duration`` vào manifest),
  nhưng cache theo ``tts_cache_key`` trong chính ``normalized.json`` nên
  chạy lại chỉ probe những câu vừa đổi.
- Slot = ``end - start`` của segment, không mượn khoảng lặng của segment
  kế tiếp (đo trên episode thật không đổi kết quả — các segment Whisper
  nằm liền kề nhau).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.translation.base import TranslationError
from app.translation.translate import TRANSLATED_FILENAME, read_translated
from app.tts.synthesize import MANIFEST_FILENAME, TTS_DIRNAME

NORMALIZED_FILENAME = "normalized.json"
TIMING_DIRNAME = "timing"


class TimingError(RuntimeError):
    """Lỗi rõ ràng khi thiếu input, ffmpeg/ffprobe không có, hoặc lỗi khi co giãn."""


@dataclass(frozen=True)
class TimingResult:
    normalized_path: Path
    normal_ids: list[int] = field(default_factory=list)
    stretched_ids: list[int] = field(default_factory=list)
    too_long_ids: list[int] = field(default_factory=list)
    silent_ids: list[int] = field(default_factory=list)
    missing_ids: list[int] = field(default_factory=list)
    skipped: bool = False


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    # Copy pattern từ app/tts/synthesize.py:_write_json_atomic (hàm private,
    # không import chéo) — cùng lý do: bị kill giữa lúc ghi thì file cụt
    # không được coi là "đã xong" và skip mãi.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def probe_duration(path: Path) -> float:
    """Đo độ dài (giây) của file audio bằng ``ffprobe``.

    Raise ``TimingError`` nếu không tìm thấy ffprobe trên PATH, tiến trình
    lỗi, hoặc output không parse được thành số (file hỏng/rỗng).
    """
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin is None:
        raise TimingError(
            "Không tìm thấy `ffprobe` trên PATH. Cài ffmpeg (kèm ffprobe) rồi thử lại "
            "(xem README.md, mục Yêu cầu)."
        )
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise TimingError(
            f"ffprobe lỗi khi đo độ dài {path}: {result.stderr.strip()[-500:]}"
        )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise TimingError(
            f"ffprobe trả output không phải số cho {path}: {result.stdout!r}"
        ) from exc


def stretch_audio(src: Path, dst: Path, tempo: float) -> None:
    """Co giãn ``src`` theo hệ số ``tempo`` (>1 = nhanh hơn), ghi ra ``dst``.

    Ghi ra ``dst`` kèm hậu tố ``.tmp.wav`` (phải có đuôi ``.wav`` để ffmpeg
    chọn đúng muxer) rồi ``os.replace`` — atomic, tránh để lại file cụt nếu
    bị kill giữa chừng. Xuất mono ``pcm_s16le``, giữ nguyên sample rate gốc
    (không ép ``-ar``) vì input đã là mp3/wav do chính pipeline này tạo ra.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        raise TimingError(
            "Không tìm thấy `ffmpeg` trên PATH. Cài ffmpeg rồi thử lại "
            "(xem README.md, mục Yêu cầu)."
        )
    tmp_path = dst.with_name(dst.stem + ".tmp.wav")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(src),
        "-filter:a", f"atempo={tempo:.4f}",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(tmp_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        tmp_path.unlink(missing_ok=True)
        raise TimingError(
            f"ffmpeg co giãn thất bại cho {src}: {result.stderr.strip()[-2000:]}"
        )
    if not tmp_path.exists():
        raise TimingError(f"ffmpeg chạy xong nhưng không thấy file output tại: {tmp_path}")
    os.replace(tmp_path, dst)


def classify(
    tts_duration: float, slot: float, *, normal_max_ratio: float, max_tempo: float
) -> tuple[str, float | None, float]:
    """Phân loại một segment dựa trên tỷ lệ ``tts_duration / slot``.

    Hàm thuần, không I/O. ``slot <= 0`` (segment Whisper suy biến, hiếm gặp)
    coi luôn là quá dài vì không có chỗ để đặt audio.
    """
    if slot <= 0:
        return "too_long", None, max_tempo
    ratio = tts_duration / slot
    if ratio <= normal_max_ratio:
        return "normal", ratio, 1.0
    if ratio <= max_tempo:
        # Vừa khít slot: tempo đúng bằng ratio để audio_duration ~= slot.
        return "stretched", ratio, ratio
    return "too_long", ratio, max_tempo


def _round3(value: float) -> float:
    return round(value, 3)


def _round4(value: float) -> float:
    return round(value, 4)


def _timing_filename(segment_id: int) -> str:
    return f"{segment_id:06d}.wav"


def _compute_fingerprint(
    params: dict[str, float], rows: list[tuple[int, float, float, str, str | None]]
) -> str:
    payload = {
        "params": params,
        "segments": [list(row) for row in rows],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load_old_normalized(path: Path, log: Callable[[str], None]) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[normalize] {path} hỏng ({exc}) — tính lại từ đầu.")
        return None


def normalize_timing(
    episode_dir: Path,
    *,
    normal_max_ratio: float = 1.05,
    max_tempo: float = 1.25,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> TimingResult:
    """Chuẩn hoá timing cho một episode, ghi ``normalized.json`` + ``timing/*.wav``."""
    episode_dir = Path(episode_dir)
    translated_path = episode_dir / TRANSLATED_FILENAME
    tts_dir = episode_dir / TTS_DIRNAME
    manifest_path = tts_dir / MANIFEST_FILENAME
    normalized_path = episode_dir / NORMALIZED_FILENAME
    timing_dir = episode_dir / TIMING_DIRNAME

    if not translated_path.exists():
        raise TimingError(
            f"Không tìm thấy {translated_path}. Chạy `translate` cho episode này trước."
        )
    if not manifest_path.exists():
        raise TimingError(
            f"Không tìm thấy {manifest_path}. Chạy `tts` cho episode này trước."
        )

    try:
        _src_lang, _tgt_lang, segments = read_translated(translated_path)
    except TranslationError as exc:
        raise TimingError(f"File {translated_path} hỏng: {exc}") from exc

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_by_id: dict[int, dict[str, Any]] = {
            int(e["id"]): e for e in manifest_data.get("segments", [])
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise TimingError(f"File {manifest_path} hỏng: {exc}") from exc

    params = {"normal_max_ratio": normal_max_ratio, "max_tempo": max_tempo}

    # Chuẩn bị dữ liệu đầu vào theo đúng thứ tự translated.json, kèm trạng
    # thái tts (ok/empty/failed/thiếu entry) để tính fingerprint.
    fingerprint_rows: list[tuple[int, float, float, str, str | None]] = []
    seg_inputs: list[dict[str, Any]] = []
    for seg in segments:
        entry = manifest_by_id.get(seg.id)
        tts_status = entry["status"] if entry else "missing"
        tts_cache_key = entry.get("cache_key") if entry else None
        fingerprint_rows.append((seg.id, seg.start, seg.end, tts_status, tts_cache_key))
        seg_inputs.append(
            {
                "id": seg.id,
                "start": seg.start,
                "end": seg.end,
                "source_text": seg.source_text,
                "translated_text": seg.translated_text,
                "tts_status": tts_status,
                "tts_cache_key": tts_cache_key,
                "tts_file": entry.get("file") if entry else None,
            }
        )

    fingerprint = _compute_fingerprint(params, fingerprint_rows)

    timing_dir.mkdir(parents=True, exist_ok=True)
    # Đầu stage: dọn *.tmp.wav sót lại từ lần chạy trước bị kill giữa chừng.
    for tmp in timing_dir.glob("*.tmp.wav"):
        tmp.unlink(missing_ok=True)

    old_data = None if force else _load_old_normalized(normalized_path, log)
    old_by_id: dict[int, dict[str, Any]] = {}
    if old_data is not None:
        old_by_id = {int(s["id"]): s for s in old_data.get("segments", [])}

    # Resume toàn phần: fingerprint khớp và mọi audio tham chiếu còn tồn tại
    # trên đĩa -> không cần probe/stretch gì cả.
    if not force and old_data is not None and old_data.get("fingerprint") == fingerprint:
        all_audio_present = True
        for s in old_data.get("segments", []):
            audio = s.get("audio")
            if audio and not (episode_dir / audio).exists():
                all_audio_present = False
                break
        if all_audio_present:
            old_segments = old_data.get("segments", [])
            return TimingResult(
                normalized_path=normalized_path,
                normal_ids=[s["id"] for s in old_segments if s["status"] == "normal"],
                stretched_ids=[s["id"] for s in old_segments if s["status"] == "stretched"],
                too_long_ids=list(old_data.get("too_long_ids", [])),
                silent_ids=[s["id"] for s in old_segments if s["status"] == "silent"],
                missing_ids=list(old_data.get("missing_ids", [])),
                skipped=True,
            )

    normal_ids: list[int] = []
    stretched_ids: list[int] = []
    too_long_ids: list[int] = []
    silent_ids: list[int] = []
    missing_ids: list[int] = []
    out_segments: list[dict[str, Any]] = []
    referenced_audio: set[str] = set()

    for seg_in in seg_inputs:
        seg_id = seg_in["id"]
        old_entry = None if force else old_by_id.get(seg_id)
        base = {
            "id": seg_id,
            "start": seg_in["start"],
            "end": seg_in["end"],
            "source_text": seg_in["source_text"],
            "translated_text": seg_in["translated_text"],
        }

        if seg_in["tts_status"] == "empty":
            silent_ids.append(seg_id)
            out_segments.append(
                {
                    **base,
                    "slot": _round3(seg_in["end"] - seg_in["start"]),
                    "status": "silent",
                    "tts_file": None,
                    "tts_cache_key": None,
                    "tts_duration": None,
                    "ratio": None,
                    "tempo": None,
                    "audio": None,
                    "audio_duration": None,
                    "overflow": 0.0,
                }
            )
            continue

        if seg_in["tts_status"] != "ok" or not seg_in["tts_file"]:
            missing_ids.append(seg_id)
            if seg_in["tts_status"] == "failed":
                error = f"tts failed: entry status=failed cho id {seg_id}"
            else:
                error = f"tts failed: không có entry 'ok' cho id {seg_id} trong manifest"
            out_segments.append(
                {
                    **base,
                    "slot": _round3(seg_in["end"] - seg_in["start"]),
                    "status": "missing",
                    "tts_file": None,
                    "tts_cache_key": None,
                    "tts_duration": None,
                    "ratio": None,
                    "tempo": None,
                    "audio": None,
                    "audio_duration": None,
                    "overflow": 0.0,
                    "error": error,
                }
            )
            continue

        tts_path = tts_dir / seg_in["tts_file"]
        tts_rel = Path(TTS_DIRNAME, seg_in["tts_file"]).as_posix()
        if not tts_path.exists():
            missing_ids.append(seg_id)
            out_segments.append(
                {
                    **base,
                    "slot": _round3(seg_in["end"] - seg_in["start"]),
                    "status": "missing",
                    "tts_file": None,
                    "tts_cache_key": None,
                    "tts_duration": None,
                    "ratio": None,
                    "tempo": None,
                    "audio": None,
                    "audio_duration": None,
                    "overflow": 0.0,
                    "error": f"file tts không tồn tại: {tts_rel}",
                }
            )
            continue

        # Cache theo segment: cache_key khớp entry cũ -> dùng lại tts_duration
        # đã đo, không gọi ffprobe lại.
        tts_duration: float | None = None
        if (
            old_entry is not None
            and old_entry.get("status") in ("normal", "stretched", "too_long")
            and old_entry.get("tts_cache_key") == seg_in["tts_cache_key"]
            and old_entry.get("tts_duration") is not None
        ):
            tts_duration = old_entry["tts_duration"]

        try:
            if tts_duration is None:
                tts_duration = probe_duration(tts_path)
        except TimingError as exc:
            missing_ids.append(seg_id)
            out_segments.append(
                {
                    **base,
                    "slot": _round3(seg_in["end"] - seg_in["start"]),
                    "status": "missing",
                    "tts_file": tts_rel,
                    "tts_cache_key": seg_in["tts_cache_key"],
                    "tts_duration": None,
                    "ratio": None,
                    "tempo": None,
                    "audio": None,
                    "audio_duration": None,
                    "overflow": 0.0,
                    "error": str(exc),
                }
            )
            continue

        slot = seg_in["end"] - seg_in["start"]
        status, ratio, tempo = classify(
            tts_duration, slot, normal_max_ratio=normal_max_ratio, max_tempo=max_tempo
        )

        if status == "normal":
            normal_ids.append(seg_id)
            audio_rel = tts_rel
            audio_duration = tts_duration
        else:
            if status == "stretched":
                stretched_ids.append(seg_id)
            else:
                too_long_ids.append(seg_id)
            timing_path = timing_dir / _timing_filename(seg_id)
            audio_rel = Path(TIMING_DIRNAME, _timing_filename(seg_id)).as_posix()

            reuse_existing = (
                old_entry is not None
                and old_entry.get("status") in ("stretched", "too_long")
                and old_entry.get("tts_cache_key") == seg_in["tts_cache_key"]
                and old_entry.get("tempo") is not None
                and _round4(old_entry["tempo"]) == _round4(tempo)
                and old_entry.get("audio") == audio_rel
                and timing_path.exists()
            )
            if reuse_existing:
                audio_duration = old_entry["audio_duration"]
            else:
                stretch_audio(tts_path, timing_path, tempo)
                audio_duration = probe_duration(timing_path)

        referenced_audio.add(audio_rel)
        overflow = max(0.0, audio_duration - slot)
        out_segments.append(
            {
                **base,
                "slot": _round3(slot),
                "status": status,
                "tts_file": tts_rel,
                "tts_cache_key": seg_in["tts_cache_key"],
                "tts_duration": _round3(tts_duration),
                "ratio": _round4(ratio) if ratio is not None else None,
                "tempo": _round4(tempo),
                "audio": audio_rel,
                "audio_duration": _round3(audio_duration),
                "overflow": _round3(overflow),
            }
        )

    # Dọn file mồ côi trong timing/: id không còn stretched/too_long ở lần
    # ghi này (vd câu đổi từ stretched thành normal sau khi giảm max_tempo
    # hoặc dịch lại ngắn hơn).
    for f in timing_dir.iterdir():
        if f.is_file() and f.suffix == ".wav":
            rel = Path(TIMING_DIRNAME, f.name).as_posix()
            if rel not in referenced_audio:
                f.unlink()

    summary = {
        "segments": len(out_segments),
        "normal": len(normal_ids),
        "stretched": len(stretched_ids),
        "too_long": len(too_long_ids),
        "silent": len(silent_ids),
        "missing": len(missing_ids),
    }

    # Ghi normalized.json sau cùng, sau khi mọi file timing/ đã xong — kill
    # giữa chừng thì lần sau không SKIP nhầm (fingerprint khớp nhưng thiếu file).
    _write_json_atomic(
        normalized_path,
        {
            "fingerprint": fingerprint,
            "params": params,
            "summary": summary,
            "too_long_ids": sorted(too_long_ids),
            "missing_ids": sorted(missing_ids),
            "segments": out_segments,
        },
    )

    return TimingResult(
        normalized_path=normalized_path,
        normal_ids=normal_ids,
        stretched_ids=stretched_ids,
        too_long_ids=sorted(too_long_ids),
        silent_ids=silent_ids,
        missing_ids=sorted(missing_ids),
        skipped=False,
    )

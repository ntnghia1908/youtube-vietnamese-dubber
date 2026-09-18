"""Stage dịch: ``transcript.json`` -> ``translated.json`` — Checkpoint 3.

Resume ở ba mức (xem ``docs/decisions/checkpoint-3.md`` mục C3/C5/C7):

- ``translated.json`` đã tồn tại, hash transcript khớp và không có
  segment lỗi -> bỏ qua cả stage (trừ khi ``force``).
- Hash transcript khớp nhưng có ``failed_ids`` -> chỉ dịch lại đúng các
  segment đã lỗi lần trước, giữ nguyên các dòng đã dịch tốt.
- Hash transcript khác lần dịch trước (vd transcribe lại với ``--force``)
  -> dịch lại từ đầu như ``force=True``. File cũ chưa có hash (schema cũ)
  thì vẫn SKIP như trước, không có gì để so sánh.
- Đang dịch dở -> mỗi batch xong được ghi ngay vào
  ``translated.partial.json``, gắn theo model đang dùng; đổi model khi
  đang dở thì bỏ partial, dịch lại từ đầu (không trộn hai model chung
  một ``translated.json``).

Batch lỗi output được retry, vẫn lỗi thì chia đôi và dịch từng nửa —
model nhỏ hay gộp/bỏ dòng khi batch dài, batch ngắn thường qua được. Một
segment đơn lẻ vẫn lỗi sau khi chia tới còn 1 dòng thì được đánh dấu lỗi
(``failed_ids``) và bỏ qua, không làm dừng cả stage — playlist qua đêm
không được để một câu khó chặn cả tập. Chỉ khi *toàn bộ* segment có chữ
đều lỗi mới coi là model/cấu hình hỏng và raise.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.transcription.whisper import Segment, read_transcript
from app.translation.base import (
    TranslationError,
    Translator,
    TranslatorConnectionError,
    TranslatorOutputError,
)
from app.translation.prompt import ContextLine, SourceLine

TRANSLATED_FILENAME = "translated.json"
PARTIAL_SUFFIX = ".partial.json"

# Chờ giữa các lần thử theo plan §24: thử 1, chờ 2s, thử 2, chờ 5s, thử 3.
_RETRY_DELAYS = (2.0, 5.0)


@dataclass(frozen=True)
class TranslatedSegment:
    id: int
    start: float
    end: float
    source_text: str
    translated_text: str


@dataclass(frozen=True)
class TranslationResult:
    translated_path: Path
    source_language: str
    target_language: str
    segments: list[TranslatedSegment]
    skipped: bool
    # ID (theo thứ tự transcript) của các segment không dịch được sau khi
    # chia đôi tới còn 1 dòng vẫn lỗi (C3). Rỗng nếu không có lỗi hoặc khi
    # SKIP (SKIP chỉ xảy ra khi lần dịch trước không còn segment lỗi).
    failed_ids: list[int] = field(default_factory=list)


def partial_path_for(translated_path: Path) -> Path:
    return translated_path.with_name(translated_path.stem + PARTIAL_SUFFIX)


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    # Ghi ra file tạm rồi rename: nếu bị kill giữa lúc ghi, file đích không
    # bị cụt — một translated.json cụt sẽ bị coi là "đã xong" và skip mãi.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _segment_dict(seg: Segment, translation: str) -> dict[str, Any]:
    return {
        "id": seg.id,
        "start": seg.start,
        "end": seg.end,
        "source_text": seg.text,
        "translated_text": translation,
    }


def _load_translated_data(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationError(
            f"File {path} hỏng ({exc}). Chạy lại với --force để dịch lại."
        ) from exc


def _segments_from_data(path: Path, data: dict[str, Any]) -> list[TranslatedSegment]:
    try:
        return [
            TranslatedSegment(
                id=s["id"],
                start=s["start"],
                end=s["end"],
                source_text=s["source_text"],
                translated_text=s["translated_text"],
            )
            for s in data["segments"]
        ]
    except (KeyError, TypeError) as exc:
        raise TranslationError(
            f"File {path} hỏng ({exc}). Chạy lại với --force để dịch lại."
        ) from exc


def read_translated(translated_path: Path) -> tuple[str, str, list[TranslatedSegment]]:
    data = _load_translated_data(translated_path)
    segments = _segments_from_data(translated_path, data)
    return data.get("source_language", ""), data.get("target_language", ""), segments


def _read_translated_meta(path: Path) -> dict[str, Any]:
    """Đọc ``translated.json`` kèm các key mới (C3/C7), dung nạp file cũ.

    File sinh ra trước khi có thay đổi này không có ``transcript_sha256``
    (coi như ``None``) hay ``failed_ids`` (coi như rỗng).
    """
    data = _load_translated_data(path)
    segments = _segments_from_data(path, data)
    return {
        "source_language": data.get("source_language", ""),
        "target_language": data.get("target_language", ""),
        "segments": segments,
        "transcript_sha256": data.get("transcript_sha256"),
        "failed_ids": list(data.get("failed_ids", [])),
        "translator": data.get("translator"),
    }


def _load_partial(
    partial_path: Path,
    *,
    transcript_sha256: str,
    target_language: str,
    translator_info: dict[str, str],
    log: Callable[[str], None],
) -> dict[int, str]:
    if not partial_path.exists():
        return {}
    try:
        data = json.loads(partial_path.read_text(encoding="utf-8"))
        if data["transcript_sha256"] != transcript_sha256:
            log("[translate] transcript đã thay đổi — bỏ tiến trình dịch dở cũ.")
            return {}
        if data["target_language"] != target_language:
            log("[translate] ngôn ngữ đích đã đổi — bỏ tiến trình dịch dở cũ.")
            return {}
        old_translator = data.get("translator")
        if old_translator and (
            (old_translator.get("provider"), old_translator.get("model"))
            != (translator_info["provider"], translator_info["model"])
        ):
            # C5: một translated.json không được trộn hai model — partial cũ
            # không có key `translator` (trước C5) thì coi như khớp.
            log(
                "[translate] tiến trình dở dịch bằng "
                f"{old_translator.get('provider')}/{old_translator.get('model')}, "
                f"đang dùng {translator_info['provider']}/{translator_info['model']} — dịch lại từ đầu."
            )
            return {}
        return {int(s["id"]): s["translated_text"] for s in data["segments"]}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        log(f"[translate] file tiến trình hỏng ({exc}) — dịch lại từ đầu.")
        return {}


def _chunks(items: Sequence[Segment], size: int) -> list[list[Segment]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _id_range(batch: Sequence[Segment]) -> str:
    return f"id {batch[0].id}-{batch[-1].id}" if len(batch) > 1 else f"id {batch[0].id}"


def translate_transcript(
    transcript_path: Path,
    translated_path: Path,
    translator: Translator,
    *,
    target_language: str,
    batch_size: int = 25,
    context_size: int = 5,
    max_attempts: int = 3,
    force: bool = False,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> TranslationResult:
    """Dịch ``transcript_path`` sang ``target_language``, ghi ``translated_path``."""
    transcript_path = Path(transcript_path)
    translated_path = Path(translated_path)
    partial_path = partial_path_for(translated_path)

    # C3: id các segment lỗi lần dịch trước cần thử lại; chỉ set khi hash
    # transcript khớp và translated.json có failed_ids (xem khối bên dưới).
    retry_translations: dict[int, str] = {}
    retry_translator_info: dict[str, str] | None = None

    if translated_path.exists() and not force:
        meta = _read_translated_meta(translated_path)
        if meta["transcript_sha256"] is None or not transcript_path.exists():
            # File cũ (trước khi có hash) hoặc không còn transcript để so
            # sánh -> không biết transcript có đổi hay không, giữ hành vi cũ.
            return TranslationResult(
                translated_path,
                meta["source_language"],
                meta["target_language"],
                meta["segments"],
                skipped=True,
                failed_ids=meta["failed_ids"],
            )
        current_hash = hashlib.sha256(transcript_path.read_bytes()).hexdigest()
        if meta["transcript_sha256"] != current_hash:
            # C7: transcript đã đổi kể từ lần dịch -> ID/nội dung không còn
            # đáng tin, dịch lại toàn bộ như force=True.
            log("[translate] transcript đã thay đổi kể từ lần dịch — dịch lại từ đầu.")
            force = True
        elif not meta["failed_ids"]:
            return TranslationResult(
                translated_path,
                meta["source_language"],
                meta["target_language"],
                meta["segments"],
                skipped=True,
                failed_ids=[],
            )
        else:
            retry_translations = {
                s.id: s.translated_text for s in meta["segments"] if s.id not in set(meta["failed_ids"])
            }
            retry_translator_info = meta["translator"]
            log(
                "[translate] thử lại {} segment lỗi lần trước: id {}".format(
                    len(meta["failed_ids"]),
                    ", ".join(str(i) for i in sorted(meta["failed_ids"])),
                )
            )

    if not transcript_path.exists():
        raise TranslationError(
            f"Không tìm thấy {transcript_path}. Chạy `transcribe` cho episode này trước."
        )
    transcript_bytes = transcript_path.read_bytes()
    try:
        source_language, segments = read_transcript(transcript_path)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TranslationError(f"File {transcript_path} hỏng: {exc}") from exc

    ids = [seg.id for seg in segments]
    if len(set(ids)) != len(ids):
        # Validate output dựa hoàn toàn vào ID, ID trùng thì không thể ghép lại.
        raise TranslationError(f"{transcript_path} có segment trùng id.")

    transcript_sha256 = hashlib.sha256(transcript_bytes).hexdigest()
    # `translator_info` gắn vào partial: model đang thật sự chạy lúc này,
    # dùng để C5 phát hiện đổi model giữa chừng.
    translator_info = {"provider": translator.provider, "model": translator.model}
    # `output_translator_info` ghi vào translated.json cuối cùng: ở chế độ
    # thử lại (C3) giữ model của lần dịch trước vì đa số dòng do model đó
    # dịch — chỉ vài dòng lỗi được thử lại bằng model hiện tại.
    if retry_translator_info is not None:
        if (retry_translator_info.get("provider"), retry_translator_info.get("model")) != (
            translator_info["provider"],
            translator_info["model"],
        ):
            log(
                "[translate] thử lại bằng "
                f"{translator_info['provider']}/{translator_info['model']}, khác model lần dịch "
                f"trước ({retry_translator_info.get('provider')}/{retry_translator_info.get('model')})"
                " — translated.json vẫn ghi model của lần trước."
            )
        output_translator_info = dict(retry_translator_info)
    else:
        output_translator_info = translator_info

    if force:
        # Xoá luôn translated.json cũ chứ không chỉ partial: nếu lần chạy
        # --force bị ngắt giữa chừng mà file cũ còn đó, lần chạy lại (không
        # --force) sẽ SKIP và lặng lẽ giữ bản dịch cũ thay vì dịch tiếp.
        translated_path.unlink(missing_ok=True)
        partial_path.unlink(missing_ok=True)
    done: dict[int, str] = dict(retry_translations)
    partial_done = _load_partial(
        partial_path,
        transcript_sha256=transcript_sha256,
        target_language=target_language,
        translator_info=translator_info,
        log=log,
    )
    if partial_done:
        log(f"[translate] resume: đã có {len(partial_done)}/{len(segments)} segment.")
    done.update(partial_done)

    # Dòng gốc rỗng thì bản dịch rỗng, không tốn một lượt gọi model.
    for seg in segments:
        if not seg.text.strip():
            done.setdefault(seg.id, "")

    position = {seg.id: i for i, seg in enumerate(segments)}

    def save_partial() -> None:
        _write_json_atomic(
            partial_path,
            {
                "transcript_sha256": transcript_sha256,
                "source_language": source_language,
                "target_language": target_language,
                "translator": translator_info,
                "segments": [_segment_dict(s, done[s.id]) for s in segments if s.id in done],
            },
        )

    def context_for(batch: list[Segment]) -> list[ContextLine]:
        if context_size == 0:
            return []
        before = [s for s in segments[: position[batch[0].id]] if s.id in done]
        return [ContextLine(s.id, s.text, done[s.id]) for s in before[-context_size:]]

    def call_with_retry(batch: list[Segment], label: str) -> dict[int, str]:
        lines = [SourceLine(s.id, s.text, max(0.0, s.end - s.start)) for s in batch]

        def call() -> dict[int, str]:
            return translator.translate_batch(
                lines,
                context=context_for(batch),
                source_language=source_language,
                target_language=target_language,
            )

        for attempt in range(1, max_attempts):
            try:
                return call()
            except (TranslatorOutputError, TranslatorConnectionError) as exc:
                delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                log(f"[translate] {label} lần {attempt}/{max_attempts} lỗi: {exc} — thử lại sau {delay:g}s")
                sleep(delay)
        return call()  # lần cuối: lỗi thì để nổi lên cho run_batch xử lý

    def run_batch(batch: list[Segment], label: str) -> None:
        started = time.monotonic()
        try:
            translations = call_with_retry(batch, label)
        except TranslatorOutputError as exc:
            if len(batch) == 1:
                # C3: một segment vẫn lỗi sau khi chia tới còn 1 dòng —
                # không raise, đánh dấu lỗi rồi dịch tiếp phần còn lại. Câu
                # khó không được chặn cả tập khi chạy playlist qua đêm.
                # Segment lỗi không vào `done` nên không lọt vào partial và
                # không làm ngữ cảnh cho các batch sau.
                log(
                    f"[translate] id {batch[0].id}: bỏ qua sau {max_attempts} lần lỗi ({exc}) — "
                    "sẽ thử lại ở lần chạy sau."
                )
                return
            mid = len(batch) // 2
            left, right = batch[:mid], batch[mid:]
            log(
                f"[translate] {label} vẫn lỗi ({exc}) — chia đôi: "
                f"{_id_range(left)} và {_id_range(right)}"
            )
            run_batch(left, _id_range(left))
            run_batch(right, _id_range(right))
            return

        done.update(translations)
        save_partial()
        log(f"[translate] {label} DONE ({time.monotonic() - started:.1f}s)")

    pending = [seg for seg in segments if seg.id not in done]
    batches = _chunks(pending, batch_size)
    try:
        for index, batch in enumerate(batches, start=1):
            run_batch(batch, f"batch {index}/{len(batches)} ({_id_range(batch)})")
    except TranslationError as exc:
        # Chỉ còn TranslatorConnectionError/TranslationError (cấu hình) nổi
        # tới đây — lỗi output đơn lẻ đã được run_batch tự xử lý ở trên.
        if not partial_path.exists():
            raise
        raise TranslationError(
            f"{exc}\nĐã lưu {len(done)}/{len(segments)} segment vào {partial_path} — "
            "chạy lại lệnh để dịch tiếp phần còn thiếu."
        ) from exc

    failed_ids = sorted(seg.id for seg in segments if seg.id not in done)
    nonempty_ids = {seg.id for seg in segments if seg.text.strip()}
    if nonempty_ids and not (nonempty_ids & done.keys()):
        # Không một segment có chữ nào dịch được -> nhiều khả năng model
        # hoặc cấu hình dịch có vấn đề chứ không phải câu khó đơn lẻ. Không
        # ghi translated.json (sẽ toàn "" và failed_ids phủ hết); partial
        # (nếu batch nào lỡ ghi được) vẫn giữ nguyên cho lần chạy sau.
        raise TranslationError(
            f"Toàn bộ {len(nonempty_ids)} segment có chữ đều dịch lỗi — "
            f"khả năng model {translator_info['model']} hoặc cấu hình dịch có vấn đề."
        )

    translated_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        translated_path,
        {
            "source_language": source_language,
            "target_language": target_language,
            "translator": output_translator_info,
            "transcript_sha256": transcript_sha256,
            "failed_ids": failed_ids,
            "segments": [_segment_dict(s, done.get(s.id, "")) for s in segments],
        },
    )
    if partial_path.exists():
        partial_path.unlink()

    result_segments = [
        TranslatedSegment(s.id, s.start, s.end, s.text, done.get(s.id, "")) for s in segments
    ]
    return TranslationResult(
        translated_path,
        source_language,
        target_language,
        result_segments,
        skipped=False,
        failed_ids=failed_ids,
    )

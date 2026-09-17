"""Stage dịch: ``transcript.json`` -> ``translated.json`` — Checkpoint 3.

Resume ở hai mức:

- ``translated.json`` đã tồn tại -> bỏ qua cả stage (trừ khi ``force``).
- Đang dịch dở -> mỗi batch xong được ghi ngay vào
  ``translated.partial.json``; chạy lại chỉ dịch các segment còn thiếu.
  File partial gắn với hash của transcript, transcript đổi (vd transcribe
  lại với ``--force``) thì bỏ partial cũ vì ID không còn khớp nội dung.

Batch lỗi output được retry, vẫn lỗi thì chia đôi và dịch từng nửa —
model nhỏ hay gộp/bỏ dòng khi batch dài, batch ngắn thường qua được.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


def read_translated(translated_path: Path) -> tuple[str, str, list[TranslatedSegment]]:
    try:
        data = json.loads(translated_path.read_text(encoding="utf-8"))
        segments = [
            TranslatedSegment(
                id=s["id"],
                start=s["start"],
                end=s["end"],
                source_text=s["source_text"],
                translated_text=s["translated_text"],
            )
            for s in data["segments"]
        ]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TranslationError(
            f"File {translated_path} hỏng ({exc}). Chạy lại với --force để dịch lại."
        ) from exc
    return data.get("source_language", ""), data.get("target_language", ""), segments


def _load_partial(
    partial_path: Path, *, transcript_sha256: str, target_language: str, log: Callable[[str], None]
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

    if translated_path.exists() and not force:
        source_language, target, segments = read_translated(translated_path)
        return TranslationResult(translated_path, source_language, target, segments, skipped=True)

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
    translator_info = {"provider": translator.provider, "model": translator.model}

    if force:
        # Xoá luôn translated.json cũ chứ không chỉ partial: nếu lần chạy
        # --force bị ngắt giữa chừng mà file cũ còn đó, lần chạy lại (không
        # --force) sẽ SKIP và lặng lẽ giữ bản dịch cũ thay vì dịch tiếp.
        translated_path.unlink(missing_ok=True)
        partial_path.unlink(missing_ok=True)
    done = _load_partial(
        partial_path,
        transcript_sha256=transcript_sha256,
        target_language=target_language,
        log=log,
    )
    if done:
        log(f"[translate] resume: đã có {len(done)}/{len(segments)} segment.")

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
                raise TranslationError(
                    f"Không dịch được segment id {batch[0].id} sau {max_attempts} lần: {exc}"
                ) from exc
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
        if not partial_path.exists():
            raise
        raise TranslationError(
            f"{exc}\nĐã lưu {len(done)}/{len(segments)} segment vào {partial_path} — "
            "chạy lại lệnh để dịch tiếp phần còn thiếu."
        ) from exc

    translated_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        translated_path,
        {
            "source_language": source_language,
            "target_language": target_language,
            "translator": translator_info,
            "segments": [_segment_dict(s, done[s.id]) for s in segments],
        },
    )
    if partial_path.exists():
        partial_path.unlink()

    result_segments = [
        TranslatedSegment(s.id, s.start, s.end, s.text, done[s.id]) for s in segments
    ]
    return TranslationResult(
        translated_path, source_language, target_language, result_segments, skipped=False
    )

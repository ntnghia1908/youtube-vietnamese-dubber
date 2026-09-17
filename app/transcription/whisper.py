"""Speech-to-text bằng faster-whisper — Checkpoint 2.

Sinh transcript có timestamp cho từng đoạn lời thoại từ ``audio.wav``.

Resume: nếu ``transcript.json`` của episode đã tồn tại thì không chạy
lại Whisper (đọc lại từ file), trừ khi gọi với ``force=True``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TRANSCRIPT_FILENAME = "transcript.json"

# "medium" là điểm khởi đầu khuyến nghị trong docs/IMPLEMENTATION_PLAN.md
# (mục 4, Speech-to-text) — cân bằng chất lượng/tốc độ cho CPU/GPU vừa phải.
DEFAULT_MODEL_SIZE = "medium"


class TranscriptionError(RuntimeError):
    """Lỗi rõ ràng khi load model faster-whisper hoặc transcribe thất bại."""


@dataclass(frozen=True)
class Segment:
    """Một đoạn lời thoại có timestamp — dùng lại ở translate/timing sau này."""

    id: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    """Kết quả transcribe — dùng lại ở checkpoint translate."""

    language: str
    segments: list[Segment]
    transcript_path: Path


def _run_whisper(
    audio_path: Path,
    *,
    model_size: str,
    device: str,
    compute_type: str,
    language: str | None,
) -> tuple[str, list[Segment]]:
    """Chạy faster-whisper thật. Raise TranscriptionError nếu load/transcribe lỗi."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionError(
            "Chưa cài `faster-whisper`. Chạy `pip install -e .` rồi thử lại."
        ) from exc

    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        # language=None -> để Whisper tự nhận dạng. Auto-detect có thể đoán
        # sai với confidence thấp (vd nhạc nền ở đầu video), khi đó toàn bộ
        # transcript sẽ bị dịch sang ngôn ngữ đoán nhầm thay vì phiên âm
        # đúng tiếng gốc — nên cho phép ép cứng qua --source-lang.
        segments_iter, info = model.transcribe(str(audio_path), language=language)
        segments = [
            Segment(id=idx, start=seg.start, end=seg.end, text=seg.text.strip())
            for idx, seg in enumerate(segments_iter, start=1)
        ]
    except TranscriptionError:
        raise
    except Exception as exc:
        # faster-whisper/ctranslate2 không có một exception type ổn định
        # duy nhất cho mọi lỗi (model không tồn tại, audio hỏng, hết VRAM...).
        raise TranscriptionError(
            f"Transcribe thất bại cho: {audio_path}\nChi tiết: {exc}"
        ) from exc

    return info.language, segments


def _write_transcript(language: str, segments: list[Segment], transcript_path: Path) -> None:
    data = {
        "language": language,
        "segments": [
            {"id": seg.id, "start": seg.start, "end": seg.end, "text": seg.text}
            for seg in segments
        ],
    }
    transcript_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_transcript(transcript_path: Path) -> tuple[str, list[Segment]]:
    """Đọc transcript.json — dùng lại ở stage translate."""
    data: dict[str, Any] = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = [
        Segment(id=s["id"], start=s["start"], end=s["end"], text=s["text"])
        for s in data.get("segments", [])
    ]
    return data.get("language", ""), segments


def transcribe_audio(
    audio_path: Path,
    transcript_path: Path,
    *,
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = "auto",
    compute_type: str = "auto",
    language: str | None = None,
    force: bool = False,
) -> TranscriptResult:
    """Transcribe ``audio_path`` bằng faster-whisper, ghi ra ``transcript_path``.

    Bỏ qua chạy Whisper (đọc lại transcript có sẵn) nếu ``transcript_path``
    đã tồn tại, trừ khi ``force=True``.
    """
    audio_path = Path(audio_path)
    transcript_path = Path(transcript_path)

    if transcript_path.exists() and not force:
        language, segments = read_transcript(transcript_path)
        return TranscriptResult(
            language=language, segments=segments, transcript_path=transcript_path
        )

    if not audio_path.exists():
        raise TranscriptionError(f"Không tìm thấy file audio: {audio_path}")

    # Tên khác với tham số ``language``: tham số là ngôn ngữ *yêu cầu* (có thể
    # None = auto), còn đây là ngôn ngữ Whisper *thực sự* dùng — ghi vào file.
    detected_language, segments = _run_whisper(
        audio_path,
        model_size=model_size,
        device=device,
        compute_type=compute_type,
        language=language,
    )
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    _write_transcript(detected_language, segments, transcript_path)

    return TranscriptResult(
        language=detected_language, segments=segments, transcript_path=transcript_path
    )

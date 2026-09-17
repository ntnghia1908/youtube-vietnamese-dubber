"""Trích audio từ video bằng FFmpeg — Checkpoint 2.

Chuẩn hoá output về WAV mono 16kHz PCM — định dạng khuyến nghị cho
faster-whisper (tránh phải resample lại ở bước transcribe).

Resume: nếu ``audio.wav`` của episode đã tồn tại thì không trích lại,
trừ khi gọi với ``force=True``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

AUDIO_FILENAME = "audio.wav"

_SAMPLE_RATE_HZ = 16000


class AudioExtractionError(RuntimeError):
    """Lỗi rõ ràng khi không tìm thấy ffmpeg hoặc trích audio thất bại."""


def extract_audio(source_path: Path, audio_path: Path, *, force: bool = False) -> Path:
    """Trích audio track từ ``source_path`` (video) ra ``audio_path`` (WAV).

    Bỏ qua nếu ``audio_path`` đã tồn tại (resume), trừ khi ``force=True``.
    """
    source_path = Path(source_path)
    audio_path = Path(audio_path)

    if audio_path.exists() and not force:
        return audio_path

    if not source_path.exists():
        raise AudioExtractionError(f"Không tìm thấy file video nguồn: {source_path}")

    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        raise AudioExtractionError(
            "Không tìm thấy `ffmpeg` trên PATH. Cài ffmpeg rồi thử lại "
            "(xem README.md, mục Yêu cầu)."
        )

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(_SAMPLE_RATE_HZ),
        "-ac",
        "1",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise AudioExtractionError(
            f"ffmpeg trích audio thất bại cho: {source_path}\n"
            f"Chi tiết: {result.stderr.strip()[-2000:]}"
        )
    if not audio_path.exists():
        raise AudioExtractionError(
            f"ffmpeg chạy xong nhưng không thấy file output tại: {audio_path}"
        )
    return audio_path

"""Command-line interface cho YouTube Vietnamese Dubber.

Checkpoint 1: subcommand ``download`` (tải một video YouTube).
Checkpoint 2: subcommand ``transcribe`` (trích audio + speech-to-text).
Các subcommand khác (translate, tts, render, dub, playlist, ...) sẽ
được thêm dần ở các checkpoint tiếp theo, xem docs/IMPLEMENTATION_PLAN.md.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app import __version__

DEFAULT_WORKSPACE = Path("output")


def build_parser() -> argparse.ArgumentParser:
    """Tạo argument parser cấp cao nhất + các subcommand đã implement."""
    parser = argparse.ArgumentParser(
        prog="app",
        description=(
            "YouTube Vietnamese Dubber — tạo bản thuyết minh tiếng Việt "
            "cho video/playlist YouTube, ưu tiên chạy local, chi phí thấp."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    download_parser = subparsers.add_parser(
        "download",
        help="Tải một video YouTube, tạo metadata.json + source.mp4.",
    )
    download_parser.add_argument("url", help="URL video YouTube cần tải.")
    download_parser.add_argument(
        "--workspace",
        default=str(DEFAULT_WORKSPACE),
        help=f"Thư mục gốc chứa các episode (mặc định: {DEFAULT_WORKSPACE}).",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="Tải lại source.mp4 dù đã tồn tại (bỏ qua resume).",
    )

    transcribe_parser = subparsers.add_parser(
        "transcribe",
        help="Trích audio + speech-to-text (faster-whisper), tạo audio.wav + transcript.json.",
    )
    transcribe_parser.add_argument(
        "episode_dir",
        help="Thư mục episode đã có source.mp4 (tạo bởi subcommand `download`).",
    )
    transcribe_parser.add_argument(
        "--whisper-model",
        default="medium",
        help="Kích cỡ model faster-whisper (tiny/base/small/medium/large-v3, ...). Mặc định: medium.",
    )
    transcribe_parser.add_argument(
        "--device",
        default="auto",
        help="Device chạy faster-whisper (auto/cpu/cuda). Mặc định: auto.",
    )
    transcribe_parser.add_argument(
        "--source-lang",
        default="auto",
        help=(
            "Mã ngôn ngữ gốc của video (vd zh, en, ja). Mặc định: auto "
            "(để Whisper tự nhận dạng). Nên ép cứng nếu auto-detect đoán sai."
        ),
    )
    transcribe_parser.add_argument(
        "--force",
        action="store_true",
        help="Trích audio + transcribe lại dù audio.wav/transcript.json đã tồn tại.",
    )

    return parser


def _cmd_download(args: argparse.Namespace) -> int:
    # Import cục bộ: các subcommand chưa dùng tới không cần yt-dlp có sẵn.
    from app.youtube.download import VideoDownloadError, download_video

    try:
        episode = download_video(args.url, Path(args.workspace), force=args.force)
    except VideoDownloadError as exc:
        print(f"[download] LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"[download] video_id : {episode.video_id}")
    print(f"[download] title    : {episode.title}")
    print(f"[download] episode  : {episode.episode_dir}")
    print(f"[download] metadata : {episode.metadata_path}")
    print(f"[download] source   : {episode.source_path}")
    return 0


def _cmd_transcribe(args: argparse.Namespace) -> int:
    # Import cục bộ: subcommand chưa dùng tới không cần ffmpeg/faster-whisper có sẵn.
    from app.audio.ffmpeg import AUDIO_FILENAME, AudioExtractionError, extract_audio
    from app.transcription.whisper import (
        TRANSCRIPT_FILENAME,
        TranscriptionError,
        transcribe_audio,
    )
    from app.youtube.download import SOURCE_FILENAME

    episode_dir = Path(args.episode_dir)
    source_path = episode_dir / SOURCE_FILENAME
    audio_path = episode_dir / AUDIO_FILENAME
    transcript_path = episode_dir / TRANSCRIPT_FILENAME

    try:
        extract_audio(source_path, audio_path, force=args.force)
        result = transcribe_audio(
            audio_path,
            transcript_path,
            model_size=args.whisper_model,
            device=args.device,
            language=None if args.source_lang == "auto" else args.source_lang,
            force=args.force,
        )
    except (AudioExtractionError, TranscriptionError) as exc:
        print(f"[transcribe] LỖI: {exc}", file=sys.stderr)
        return 1

    print(f"[transcribe] audio      : {audio_path}")
    print(f"[transcribe] transcript : {result.transcript_path}")
    print(f"[transcribe] language   : {result.language}")
    print(f"[transcribe] segments   : {len(result.segments)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point dùng bởi ``python -m app``."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "download":
        return _cmd_download(args)
    if args.command == "transcribe":
        return _cmd_transcribe(args)

    # Chưa có subcommand nào được chọn — hiển thị help.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

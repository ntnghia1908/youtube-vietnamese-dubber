"""Command-line interface cho YouTube Vietnamese Dubber.

Checkpoint 1: có subcommand ``download`` (tải một video YouTube).
Các subcommand khác (transcribe, translate, tts, render, dub,
playlist, ...) sẽ được thêm dần ở các checkpoint tiếp theo, xem
docs/IMPLEMENTATION_PLAN.md.
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


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point dùng bởi ``python -m app``."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "download":
        return _cmd_download(args)

    # Chưa có subcommand nào được chọn — hiển thị help.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

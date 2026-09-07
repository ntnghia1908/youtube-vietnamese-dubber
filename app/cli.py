"""Command-line interface cho YouTube Vietnamese Dubber.

Ở Checkpoint 0, CLI chỉ hiển thị help — chưa có subcommand nào xử lý
media. Các subcommand (download, transcribe, translate, tts, render,
dub, playlist, ...) sẽ được thêm dần ở các checkpoint tiếp theo, xem
docs/IMPLEMENTATION_PLAN.md.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app import __version__


def build_parser() -> argparse.ArgumentParser:
    """Tạo argument parser cấp cao nhất.

    Hiện tại chỉ hỗ trợ ``--help`` / ``--version``. Chưa có subcommand
    xử lý video/audio nào được đăng ký ở bước skeleton này.
    """
    parser = argparse.ArgumentParser(
        prog="app",
        description=(
            "YouTube Vietnamese Dubber — tạo bản thuyết minh tiếng Việt "
            "cho video/playlist YouTube, ưu tiên chạy local, chi phí thấp. "
            "Project hiện đang ở giai đoạn skeleton (Checkpoint 0): chưa có "
            "subcommand xử lý media nào được implement."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point dùng bởi ``python -m app``."""
    parser = build_parser()
    parser.parse_args(argv)
    # Chưa có subcommand nào để dispatch ở skeleton này — hiển thị help.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

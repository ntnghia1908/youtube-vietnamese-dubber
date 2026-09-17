"""Cho phép chạy package bằng ``python -m app``."""

import sys

from app.cli import main

if __name__ == "__main__":
    # Ép stdout/stderr dùng UTF-8: trên Windows, console mặc định có thể
    # dùng code page khác (vd cp1252), không encode được tiếng Việt có
    # dấu trong help text/thông báo lỗi, khiến chương trình crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())

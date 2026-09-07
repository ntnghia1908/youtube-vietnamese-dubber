"""Smoke test cho CLI skeleton.

Ở Checkpoint 0 chưa có logic pipeline nào để test — test này chỉ xác
nhận entry point ``python -m app --help`` chạy được và trả về exit
code 0, đúng acceptance criteria của checkpoint.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCliHelp(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "app", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_help_exits_zero_and_prints_usage(self) -> None:
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("usage:", result.stdout.lower())
        self.assertIn("YouTube Vietnamese Dubber", result.stdout)

    def test_version_exits_zero(self) -> None:
        result = self._run("--version")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("app", result.stdout)


if __name__ == "__main__":
    unittest.main()

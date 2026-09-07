"""Test cho CLI.

- Nhóm ``TestCliHelp``: smoke test qua subprocess (``python -m app``),
  xác nhận ``--help``/``--version`` chạy được — acceptance criteria
  của Checkpoint 0.
- Nhóm ``TestDownloadSubcommand``: test subcommand ``download`` thêm ở
  Checkpoint 1, gọi thẳng ``app.cli.main`` trong tiến trình hiện tại
  và mock ``download_video`` để không cần mạng thật.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app import cli
from app.youtube.download import EpisodeInfo, VideoDownloadError

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

    def test_download_help_lists_subcommand(self) -> None:
        result = self._run("--help")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("download", result.stdout)

    def test_download_without_url_errors(self) -> None:
        result = self._run("download")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("url", result.stderr.lower())


class TestDownloadSubcommand(unittest.TestCase):
    def test_download_success_prints_episode_info(self) -> None:
        fake_episode = EpisodeInfo(
            video_id="vid001",
            title="Video Demo",
            source_url="https://youtu.be/vid001",
            episode_dir=Path("output/vid001__Video Demo"),
            metadata_path=Path("output/vid001__Video Demo/metadata.json"),
            source_path=Path("output/vid001__Video Demo/source.mp4"),
        )
        with (
            patch("app.youtube.download.download_video", return_value=fake_episode),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["download", "https://youtu.be/vid001"])

        self.assertEqual(exit_code, 0)
        self.assertIn("vid001", fake_stdout.getvalue())

    def test_download_failure_prints_error_and_returns_nonzero(self) -> None:
        with (
            patch(
                "app.youtube.download.download_video",
                side_effect=VideoDownloadError("URL không hợp lệ"),
            ),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["download", "https://youtu.be/broken"])

        self.assertEqual(exit_code, 1)
        self.assertIn("URL không hợp lệ", fake_stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Unit test cho ``app.youtube.download``.

Không gọi mạng thật (không có internet tới youtube.com trong môi
trường test) — ``_extract_info`` và ``_download_source`` được mock.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.youtube.download import (
    EpisodeInfo,
    VideoDownloadError,
    build_episode_dir_name,
    download_video,
    sanitize_filename,
)


class TestSanitizeFilename(unittest.TestCase):
    def test_removes_unsafe_characters(self) -> None:
        self.assertEqual(sanitize_filename('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_collapses_whitespace_and_strips_dots(self) -> None:
        self.assertEqual(sanitize_filename("  Tập   01 .  "), "Tập 01")

    def test_empty_input_falls_back_to_untitled(self) -> None:
        self.assertEqual(sanitize_filename("   "), "untitled")
        self.assertEqual(sanitize_filename("///"), "untitled")

    def test_truncates_long_titles(self) -> None:
        long_title = "a" * 200
        result = sanitize_filename(long_title, max_length=10)
        self.assertEqual(len(result), 10)


class TestBuildEpisodeDirName(unittest.TestCase):
    def test_combines_id_and_sanitized_title(self) -> None:
        self.assertEqual(
            build_episode_dir_name("abc123", "Tập 01: Khởi đầu"),
            "abc123__Tập 01: Khởi đầu".replace(":", "_"),
        )


class TestDownloadVideo(unittest.TestCase):
    def _fake_info(self) -> dict:
        return {
            "id": "vid001",
            "title": "Video Demo",
            "webpage_url": "https://youtube.com/watch?v=vid001",
            "duration": 120,
            "uploader": "Ai Do",
            "upload_date": "20260101",
            "extractor": "youtube",
        }

    def test_downloads_when_source_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with (
                patch(
                    "app.youtube.download._extract_info",
                    return_value=self._fake_info(),
                ),
                patch("app.youtube.download._download_source") as mock_download,
            ):
                # _download_source giả lập việc tạo file, vì thật ra hàm chạy
                # yt-dlp mới là bên tạo file source.mp4.
                def _fake_download(url: str, source_path: Path) -> None:
                    source_path.write_bytes(b"fake-video-bytes")

                mock_download.side_effect = _fake_download

                episode = download_video("https://youtu.be/vid001", workspace)

                mock_download.assert_called_once()
                self.assertIsInstance(episode, EpisodeInfo)
                self.assertEqual(episode.video_id, "vid001")
                self.assertTrue(episode.source_path.exists())
                self.assertTrue(episode.metadata_path.exists())

                metadata = json.loads(episode.metadata_path.read_text(encoding="utf-8"))
                self.assertEqual(metadata["id"], "vid001")
                self.assertEqual(metadata["title"], "Video Demo")

    def test_skips_download_when_source_already_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            episode_dir = workspace / build_episode_dir_name("vid001", "Video Demo")
            episode_dir.mkdir(parents=True)
            (episode_dir / "source.mp4").write_bytes(b"already-here")

            with (
                patch(
                    "app.youtube.download._extract_info",
                    return_value=self._fake_info(),
                ),
                patch("app.youtube.download._download_source") as mock_download,
            ):
                download_video("https://youtu.be/vid001", workspace)
                mock_download.assert_not_called()

    def test_force_redownloads_even_if_source_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            episode_dir = workspace / build_episode_dir_name("vid001", "Video Demo")
            episode_dir.mkdir(parents=True)
            (episode_dir / "source.mp4").write_bytes(b"already-here")

            with (
                patch(
                    "app.youtube.download._extract_info",
                    return_value=self._fake_info(),
                ),
                patch("app.youtube.download._download_source") as mock_download,
            ):
                download_video("https://youtu.be/vid001", workspace, force=True)
                mock_download.assert_called_once()

    def test_raises_clear_error_when_video_id_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with patch(
                "app.youtube.download._extract_info",
                return_value={"title": "No ID here"},
            ):
                with self.assertRaises(VideoDownloadError):
                    download_video("https://youtu.be/broken", workspace)


if __name__ == "__main__":
    unittest.main()

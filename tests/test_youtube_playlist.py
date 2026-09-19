"""Unit test cho ``app.youtube.playlist``.

Không gọi mạng thật — patch ``yt_dlp.YoutubeDL`` (đúng như spec cp-8.md),
khác cách ``test_youtube_download.py`` patch trực tiếp ``_extract_info``
(``fetch_playlist`` không tách riêng hàm gọi mạng vì chỉ có một chỗ gọi).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import yt_dlp

from app.youtube.playlist import PlaylistError, fetch_playlist


def _fake_ydl(info: dict) -> MagicMock:
    """Giả lập context manager ``yt_dlp.YoutubeDL(...)`` trả về ``info``."""
    instance = MagicMock()
    instance.extract_info.return_value = info
    instance.__enter__.return_value = instance
    instance.__exit__.return_value = False
    return MagicMock(return_value=instance)


class TestFetchPlaylist(unittest.TestCase):
    def _playlist_info(self, entries: list) -> dict:
        return {
            "_type": "playlist",
            "id": "PLabc123",
            "title": "Series Demo",
            "entries": entries,
        }

    def test_passes_extract_flat_in_playlist_opts(self) -> None:
        fake_cls = _fake_ydl(
            self._playlist_info([{"id": "v1", "title": "Ep 1", "url": "https://youtu.be/v1"}])
        )
        with patch("yt_dlp.YoutubeDL", fake_cls):
            fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        opts = fake_cls.call_args.args[0]
        self.assertEqual(opts["extract_flat"], "in_playlist")
        self.assertTrue(opts["quiet"])
        self.assertTrue(opts["skip_download"])

    def test_parses_full_entry(self) -> None:
        entries = [
            {"id": "v1", "title": "Ep 1", "url": "https://youtu.be/v1", "playlist_index": 1},
        ]
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info(entries))):
            info = fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertEqual(info.playlist_id, "PLabc123")
        self.assertEqual(info.title, "Series Demo")
        self.assertEqual(len(info.entries), 1)
        entry = info.entries[0]
        self.assertEqual(entry.index, 1)
        self.assertEqual(entry.video_id, "v1")
        self.assertEqual(entry.title, "Ep 1")
        self.assertEqual(entry.url, "https://youtu.be/v1")

    def test_missing_playlist_index_falls_back_to_position(self) -> None:
        entries = [
            {"id": "v1", "title": "Ep 1"},
            {"id": "v2", "title": "Ep 2"},
        ]
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info(entries))):
            info = fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertEqual([e.index for e in info.entries], [1, 2])

    def test_missing_or_non_http_url_builds_from_id(self) -> None:
        entries = [
            {"id": "v1", "title": "Ep 1"},
            {"id": "v2", "title": "Ep 2", "url": "v2"},
        ]
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info(entries))):
            info = fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertEqual(info.entries[0].url, "https://www.youtube.com/watch?v=v1")
        self.assertEqual(info.entries[1].url, "https://www.youtube.com/watch?v=v2")

    def test_none_entry_and_missing_id_are_dropped(self) -> None:
        entries = [
            None,
            {"id": "v1", "title": "Ep 1"},
            {"title": "Không có id"},
        ]
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info(entries))):
            info = fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertEqual([e.video_id for e in info.entries], ["v1"])

    def test_duplicate_video_id_keeps_first(self) -> None:
        entries = [
            {"id": "v1", "title": "Bản đầu"},
            {"id": "v1", "title": "Bản trùng"},
        ]
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info(entries))):
            info = fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertEqual(len(info.entries), 1)
        self.assertEqual(info.entries[0].title, "Bản đầu")

    def test_missing_title_defaults_to_untitled(self) -> None:
        entries = [{"id": "v1"}]
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info(entries))):
            info = fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertEqual(info.entries[0].title, "untitled")

    def test_single_video_raises_playlist_error(self) -> None:
        info = {"_type": "video", "id": "v1", "title": "Not a playlist"}
        with patch("yt_dlp.YoutubeDL", _fake_ydl(info)):
            with self.assertRaises(PlaylistError):
                fetch_playlist("https://youtu.be/v1")

    def test_download_error_becomes_playlist_error(self) -> None:
        instance = MagicMock()
        instance.extract_info.side_effect = yt_dlp.utils.DownloadError("network down")
        instance.__enter__.return_value = instance
        instance.__exit__.return_value = False
        with patch("yt_dlp.YoutubeDL", MagicMock(return_value=instance)):
            with self.assertRaises(PlaylistError) as ctx:
                fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")

        self.assertIn("PLabc123", str(ctx.exception))

    def test_empty_playlist_raises_playlist_error(self) -> None:
        with patch("yt_dlp.YoutubeDL", _fake_ydl(self._playlist_info([]))):
            with self.assertRaises(PlaylistError):
                fetch_playlist("https://www.youtube.com/playlist?list=PLabc123")


if __name__ == "__main__":
    unittest.main()

"""Test ``app.web.library`` (thuần stdlib, luôn chạy) — AC9, AC11."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.web import library


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _json(path: Path, data: object) -> None:
    _write(path, json.dumps(data, ensure_ascii=False))


def _full_episode(d: Path, title: str = "Tập đủ", too_long: int = 1) -> None:
    _json(d / "metadata.json", {"id": "abc", "title": title, "duration_seconds": 125})
    _write(d / "source.mp4")
    _json(d / "transcript.json", {"language": "en", "segments": [{"id": 1, "start": 0, "end": 1, "text": "hi"}]})
    _json(d / "translated.json", {"segments": [{"id": 1, "start": 0, "end": 1, "source_text": "hi", "translated_text": "chào"}]})
    _json(d / "tts" / "manifest.json", {"segments": []})
    segs = [
        {"id": i, "start": i, "end": i + 1, "source_text": "s", "translated_text": "t",
         "status": "too_long" if i <= too_long else "normal", "tempo": 1.1}
        for i in range(1, 4)
    ]
    _json(d / "normalized.json", {"segments": segs})
    _write(d / "output_vi.mp4")


class TestScanWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)

    def test_full_partial_playlist_and_junk(self) -> None:
        _full_episode(self.ws / "vid1__full", too_long=2)
        # Episode dở: mới tải + transcribe.
        partial = self.ws / "vid2__partial"
        _json(partial / "metadata.json", {"id": "v2", "title": "Dở"})
        _write(partial / "source.mp4")
        _json(partial / "transcript.json", {"segments": []})
        # Playlist 2 tập, một tập failed với error nhiều dòng.
        pl = self.ws / "PL1__list"
        error = "dòng 1\ndòng 2\ndòng 3"
        _json(pl / "playlist.json", {"title": "DS", "url": "https://x", "entries": [
            {"index": 1, "title": "A", "status": "completed", "episode_dir": "a__A"},
            {"index": 2, "title": "B", "status": "failed", "error": error},
        ]})
        _full_episode(pl / "a__A", title="A")
        # Rác + .web + thư mục không có metadata.
        (self.ws / "junk").mkdir()
        _write(self.ws / ".web" / "jobs" / "x.json", "{}")
        _write(self.ws / "file.txt")

        playlists, singles = library.scan_workspace(self.ws)

        self.assertEqual(sorted(e.rel_dir for e in singles), ["vid1__full", "vid2__partial"])
        full = next(e for e in singles if e.rel_dir == "vid1__full")
        self.assertTrue(all(v == "done" for v in full.stages.values()))
        self.assertEqual(full.too_long_count, 2)
        self.assertEqual(full.title, "Tập đủ")
        self.assertEqual(full.duration_seconds, 125.0)
        part = next(e for e in singles if e.rel_dir == "vid2__partial")
        self.assertEqual(part.stages["download"], "done")
        self.assertEqual(part.stages["transcribe"], "done")
        self.assertEqual(part.stages["translate"], "missing")
        self.assertEqual(part.stages["render"], "missing")
        self.assertIsNone(part.too_long_count)

        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0].title, "DS")
        self.assertEqual(playlists[0].entries[1]["error"], error)
        self.assertEqual([e.rel_dir for e in playlists[0].episodes], ["PL1__list/a__A"])
        self.assertEqual(playlists[0].episodes[0].playlist_key, playlists[0].key)
        self.assertEqual(playlists[0].episodes[0].key, "PL1__list~a__A")

    def test_download_needs_both_source_and_metadata(self) -> None:
        d = self.ws / "v__t"
        _json(d / "metadata.json", {"id": "v"})
        _, singles = library.scan_workspace(self.ws)
        self.assertEqual(singles[0].stages["download"], "missing")

    def test_broken_json_does_not_crash(self) -> None:
        d = self.ws / "v__t"
        _write(d / "metadata.json", "{không phải json")
        _write(d / "normalized.json", "[[")
        pl = self.ws / "PL__x"
        _write(pl / "playlist.json", "{hỏng")
        with self.assertLogs("app.web.library", level="WARNING"):
            playlists, singles = library.scan_workspace(self.ws)
        self.assertEqual(singles[0].title, None)
        self.assertIsNone(singles[0].too_long_count)
        self.assertEqual(playlists[0].entries, [])

    def test_missing_workspace(self) -> None:
        self.assertEqual(library.scan_workspace(self.ws / "none"), ([], []))

    def test_find_episode_rejects_unknown_and_traversal(self) -> None:
        _full_episode(self.ws / "vid1__full")
        pl = self.ws / "PL1__l"
        _json(pl / "playlist.json", {"entries": []})
        _full_episode(pl / "a__A")
        self.assertEqual(library.find_episode(self.ws, "vid1__full"), self.ws / "vid1__full")
        self.assertEqual(library.find_episode(self.ws, "PL1__l~a__A"), pl / "a__A")
        for bad in ("..", "../..", "..~..", "junk", "", "vid1__full/..", "%2e%2e", "/etc"):
            self.assertIsNone(library.find_episode(self.ws, bad), bad)
        self.assertEqual(library.find_playlist(self.ws, "PL1__l"), pl)
        self.assertIsNone(library.find_playlist(self.ws, "vid1__full"))
        self.assertIsNone(library.find_playlist(self.ws, ".."))


class TestLoadSegments(unittest.TestCase):
    def test_fallback_order(self) -> None:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertEqual(library.load_segments(d), [])
            _json(d / "transcript.json", {"segments": [{"id": 1, "start": 0, "end": 2, "text": "hello"}]})
            seg = library.load_segments(d)[0]
            self.assertEqual(seg["source_text"], "hello")
            self.assertIsNone(seg["translated_text"])
            self.assertIsNone(seg["status"])
            _json(d / "translated.json", {"segments": [
                {"id": 1, "start": 0, "end": 2, "source_text": "hello", "translated_text": "xin chào"}]})
            self.assertEqual(library.load_segments(d)[0]["translated_text"], "xin chào")
            _json(d / "normalized.json", {"segments": [
                {"id": 1, "start": 0, "end": 2, "source_text": "hello", "translated_text": "xin chào",
                 "status": "stretched", "tempo": 1.2}]})
            seg = library.load_segments(d)[0]
            self.assertEqual((seg["status"], seg["tempo"]), ("stretched", 1.2))


if __name__ == "__main__":
    unittest.main()

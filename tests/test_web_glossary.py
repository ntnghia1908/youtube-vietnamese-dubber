"""Test ``app.web.glossary`` (thuần stdlib + yaml, không cần fastapi) — AC1–AC5."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.translation.glossary import GlossaryError, parse_glossary
from app.web import glossary as g
from app.web.jobs import JobValidationError

VALID = "# ghi chú\nterms:\n  quantum mechanics: cơ học lượng tử\n"


def _sha_of(text: str) -> str:
    import yaml

    return parse_glossary(yaml.safe_load(text), source="t").sha256()


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ws = Path(self._tmp.name)
        self.ep = self.ws / "v1__t"
        self.ep.mkdir()
        (self.ep / "metadata.json").write_text(
            json.dumps({"id": "v1", "original_url": "https://www.youtube.com/watch?v=v1"}), encoding="utf-8")

    def translated(self, sha: str | None, *, key: bool = True) -> None:
        data = {"segments": []}
        if key:
            data["glossary_sha256"] = sha
        (self.ep / "translated.json").write_text(json.dumps(data), encoding="utf-8")


class TestState(Base):
    def test_no_file(self) -> None:
        st = g.read_glossary_state(self.ep, None)
        self.assertFalse(st.exists)
        self.assertEqual((st.content, st.file_sha256, st.stale, st.error), ("", None, None, None))
        self.assertFalse(st.has_translation)
        self.assertFalse(st.has_transcript)

    def test_valid_file_not_translated(self) -> None:
        (self.ep / "glossary.yaml").write_text(VALID, encoding="utf-8")
        (self.ep / "transcript.json").write_text("{}", encoding="utf-8")
        st = g.read_glossary_state(self.ep, None)
        self.assertTrue(st.exists and st.has_transcript)
        self.assertEqual(st.content, VALID)
        self.assertEqual(st.effective_sha256, _sha_of(VALID))
        self.assertIsNone(st.stale)  # chưa dịch

    def test_stale_match_and_mismatch(self) -> None:
        (self.ep / "glossary.yaml").write_text(VALID, encoding="utf-8")
        self.translated(_sha_of(VALID))
        self.assertFalse(g.read_glossary_state(self.ep, None).stale)
        self.translated("0" * 64)
        self.assertTrue(g.read_glossary_state(self.ep, None).stale)
        self.translated(None, key=False)  # file cũ thiếu key
        st = g.read_glossary_state(self.ep, None)
        self.assertTrue(st.stale)
        self.assertIsNone(st.translated_sha256)

    def test_translated_without_glossary_is_not_stale(self) -> None:
        self.translated(None)
        st = g.read_glossary_state(self.ep, None)
        self.assertIsNone(st.effective_sha256)
        self.assertIs(st.stale, False)

    def test_broken_file_gives_error_and_content(self) -> None:
        (self.ep / "glossary.yaml").write_text("terms: [\n", encoding="utf-8")
        self.translated(None)
        st = g.read_glossary_state(self.ep, None)
        self.assertIsNotNone(st.error)
        self.assertEqual(st.content, "terms: [\n")
        self.assertIsNone(st.stale)

    def test_shared_glossary(self) -> None:
        shared = self.ws / "shared.yaml"
        shared.write_text("terms:\n  a: b\n", encoding="utf-8")
        st = g.read_glossary_state(self.ep, shared)
        self.assertEqual(st.shared_path, str(shared))
        self.assertEqual(st.effective_sha256, _sha_of("terms:\n  a: b\n"))
        missing = g.read_glossary_state(self.ep, self.ws / "none.yaml")
        self.assertIn("none.yaml", missing.error)


class TestValidate(unittest.TestCase):
    def test_ok(self) -> None:
        for text in ("", "# chỉ comment\n", VALID):
            g.validate_glossary_text(text)

    def test_bad(self) -> None:
        with self.assertRaises(GlossaryError) as ctx:
            g.validate_glossary_text("terms: [\n")
        self.assertIn("dòng", str(ctx.exception))
        with self.assertRaises(GlossaryError):
            g.validate_glossary_text("alias: x\n")
        with self.assertRaises(GlossaryError):
            g.validate_glossary_text("context: " + "a" * g.MAX_GLOSSARY_BYTES + "\n")


class TestSave(Base):
    def path(self) -> Path:
        return self.ep / "glossary.yaml"

    def test_create_then_update_with_backup(self) -> None:
        st = g.save_glossary_text(self.ep, VALID, base_sha256=None, shared_path=None)
        self.assertEqual(self.path().read_text(encoding="utf-8"), VALID)  # giữ comment
        self.assertFalse((self.ep / "glossary.yaml.bak").exists())
        new = VALID + "  a: b"  # thiếu xuống dòng cuối -> được chuẩn hoá
        g.save_glossary_text(self.ep, new, base_sha256=st.file_sha256, shared_path=None)
        self.assertEqual((self.ep / "glossary.yaml.bak").read_text(encoding="utf-8"), VALID)
        self.assertTrue(self.path().read_text(encoding="utf-8").endswith("a: b\n"))
        self.assertFalse((self.ep / "glossary.yaml.tmp").exists())

    def test_comment_only_change_keeps_stale(self) -> None:
        st = g.save_glossary_text(self.ep, VALID, base_sha256=None, shared_path=None)
        self.translated(st.effective_sha256)
        st2 = g.save_glossary_text(self.ep, "# khác\n" + VALID, base_sha256=st.file_sha256, shared_path=None)
        self.assertIs(st2.stale, False)
        self.assertNotEqual(st2.file_sha256, st.file_sha256)
        st3 = g.save_glossary_text(self.ep, VALID + "  c: d\n", base_sha256=st2.file_sha256, shared_path=None)
        self.assertIs(st3.stale, True)

    def test_conflict_leaves_file(self) -> None:
        g.save_glossary_text(self.ep, VALID, base_sha256=None, shared_path=None)
        with self.assertRaises(g.GlossaryConflictError):
            g.save_glossary_text(self.ep, "terms: {}\n", base_sha256="deadbeef", shared_path=None)
        with self.assertRaises(g.GlossaryConflictError):  # base None nhưng file đã có
            g.save_glossary_text(self.ep, "terms: {}\n", base_sha256=None, shared_path=None)
        self.assertEqual(self.path().read_text(encoding="utf-8"), VALID)

    def test_invalid_does_not_touch_files(self) -> None:
        st = g.save_glossary_text(self.ep, VALID, base_sha256=None, shared_path=None)
        with self.assertRaises(GlossaryError):
            g.save_glossary_text(self.ep, "alias: x\n", base_sha256=st.file_sha256, shared_path=None)
        self.assertEqual(self.path().read_text(encoding="utf-8"), VALID)
        self.assertFalse((self.ep / "glossary.yaml.bak").exists())

    def test_base_none_when_no_file_conflict_if_base_given(self) -> None:
        with self.assertRaises(g.GlossaryConflictError):
            g.save_glossary_text(self.ep, VALID, base_sha256="abc", shared_path=None)
        self.assertFalse(self.path().exists())


class TestRedub(Base):
    def test_single(self) -> None:
        req = g.redub_request(self.ws, self.ep)
        self.assertEqual((req.kind, req.url, req.recheck, req.items),
                         ("dub", "https://www.youtube.com/watch?v=v1", False, None))

    def test_single_missing_url(self) -> None:
        (self.ep / "metadata.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(JobValidationError):
            g.redub_request(self.ws, self.ep)

    def test_playlist(self) -> None:
        pl = self.ws / "PL__x"
        ep = pl / "v2__t"
        ep.mkdir(parents=True)
        (pl / "playlist.json").write_text(json.dumps({
            "url": "https://www.youtube.com/playlist?list=PLx",
            "entries": [{"index": 1, "episode_dir": "a__A"}, {"index": 7, "episode_dir": "v2__t"}]}),
            encoding="utf-8")
        req = g.redub_request(self.ws, ep)
        self.assertEqual((req.kind, req.url, req.items, req.recheck),
                         ("playlist", "https://www.youtube.com/playlist?list=PLx", "7", True))

    def test_playlist_missing_entry_or_url(self) -> None:
        pl = self.ws / "PL__x"
        ep = pl / "v2__t"
        ep.mkdir(parents=True)
        (pl / "playlist.json").write_text(json.dumps({"url": "https://www.youtube.com/playlist?list=PLx",
                                                       "entries": []}), encoding="utf-8")
        with self.assertRaises(JobValidationError):
            g.redub_request(self.ws, ep)
        (pl / "playlist.json").write_text(json.dumps({"entries": [{"index": 1, "episode_dir": "v2__t"}]}),
                                          encoding="utf-8")
        with self.assertRaises(JobValidationError):
            g.redub_request(self.ws, ep)


class TestPlaylistGlossary(unittest.TestCase):
    """CP9-A: glossary playlist + dịch lại các tập stale."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pl = Path(self._tmp.name) / "PL__x"
        entries = []
        for idx, name in ((2, "b__B"), (3, "c__C"), (7, "d__D")):
            (self.pl / name).mkdir(parents=True)
            entries.append({"index": idx, "title": name, "episode_dir": name})
        (self.pl / "playlist.json").write_text(
            json.dumps({"url": "https://www.youtube.com/playlist?list=PLx", "entries": entries}), encoding="utf-8")
        # tập 2, 3 đã dịch (không hash = cũ); tập 7 chưa dịch
        for name in ("b__B", "c__C"):
            (self.pl / name / "translated.json").write_text(json.dumps({"segments": []}), encoding="utf-8")

    def test_state_without_file(self) -> None:
        st = g.read_playlist_glossary_state(self.pl, None)
        self.assertFalse(st.exists)
        self.assertEqual((st.stale_items, st.translated_items), ([], [2, 3]))  # không glossary = hash None = khớp

    def test_stale_after_save_and_match_after_redub(self) -> None:
        st = g.save_playlist_glossary_text(self.pl, VALID, base_sha256=None, shared_path=None)
        self.assertTrue(st.exists)
        self.assertEqual((st.stale_items, st.translated_items), ([2, 3], [2, 3]))
        (self.pl / "b__B" / "translated.json").write_text(
            json.dumps({"segments": [], "glossary_sha256": _sha_of(VALID)}), encoding="utf-8")
        self.assertEqual(g.read_playlist_glossary_state(self.pl, None).stale_items, [3])

    def test_save_conflict_and_backup(self) -> None:
        st = g.save_playlist_glossary_text(self.pl, VALID, base_sha256=None, shared_path=None)
        with self.assertRaises(g.GlossaryConflictError):
            g.save_playlist_glossary_text(self.pl, "terms: {a: b}\n", base_sha256=None, shared_path=None)
        g.save_playlist_glossary_text(self.pl, "terms: {a: b}\n", base_sha256=st.file_sha256, shared_path=None)
        self.assertEqual((self.pl / "glossary.yaml.bak").read_text(encoding="utf-8"), VALID)
        with self.assertRaises(GlossaryError):
            g.save_playlist_glossary_text(self.pl, "context: [x\n", base_sha256=None, shared_path=None)

    def test_redub_request(self) -> None:
        with self.assertRaisesRegex(JobValidationError, "Không có tập nào"):
            g.playlist_redub_request(self.pl, None)
        g.save_playlist_glossary_text(self.pl, VALID, base_sha256=None, shared_path=None)
        req = g.playlist_redub_request(self.pl, None)
        self.assertEqual((req.kind, req.url, req.items, req.recheck),
                         ("playlist", "https://www.youtube.com/playlist?list=PLx", "2,3", True))

    def test_episode_state_playlist_path(self) -> None:
        st = g.read_glossary_state(self.pl / "b__B", None)
        self.assertEqual(st.playlist_path, str(self.pl / "glossary.yaml"))
        lone = self.pl.parent / "lone"
        lone.mkdir()
        self.assertIsNone(g.read_glossary_state(lone, None).playlist_path)


if __name__ == "__main__":
    unittest.main()

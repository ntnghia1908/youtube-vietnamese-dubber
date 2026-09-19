"""Unit test cho ``app.translation.glossary`` (Checkpoint 6.5)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.translation.base import TranslationError
from app.translation.glossary import (
    GLOSSARY_FILENAME,
    Address,
    Character,
    Glossary,
    GlossaryError,
    load_effective_glossary,
    load_glossary,
    merge_glossaries,
    parse_glossary,
    write_glossary,
)


def _full_data() -> dict[str, Any]:
    return {
        "context": "  Truyện thiếu nhi.  ",
        "characters": [
            {
                "name": "Little Nutbrown Hare",
                "vi": "Thỏ Con",
                "aliases": ["Little Nut Brown Hair", "little nut brown hare"],
                "note": "thỏ con",
            },
            {"name": "Big Nutbrown Hare", "vi": "Thỏ Cha"},
        ],
        "address": [
            {"speaker": "Little Nutbrown Hare", "listener": "Big Nutbrown Hare", "self": "con", "other": "ba"}
        ],
        "terms": {"Patreon": "Patreon", "hare": "thỏ rừng"},
        "skip": ["support Storybook Nanny on Patreon", "  "],
    }


def _hare_glossary() -> Glossary:
    return parse_glossary(_full_data())


class TestParseGlossary(unittest.TestCase):
    def test_full_data(self) -> None:
        g = parse_glossary(_full_data())
        self.assertEqual(g.context, "Truyện thiếu nhi.")
        self.assertEqual(len(g.characters), 2)
        self.assertEqual(g.characters[0].name, "Little Nutbrown Hare")
        self.assertEqual(g.characters[0].vi, "Thỏ Con")
        self.assertEqual(g.characters[0].aliases, ("Little Nut Brown Hair", "little nut brown hare"))
        self.assertEqual(
            g.address,
            (Address("Little Nutbrown Hare", "Big Nutbrown Hare", self_term="con", other_term="ba"),),
        )
        self.assertEqual(g.terms, (("Patreon", "Patreon"), ("hare", "thỏ rừng")))
        # skip rỗng (chỉ khoảng trắng) bị bỏ.
        self.assertEqual(g.skip, ("support Storybook Nanny on Patreon",))
        self.assertFalse(g.is_empty())

    def test_none_and_empty_mapping_are_empty(self) -> None:
        for data in (None, {}):
            with self.subTest(data=data):
                g = parse_glossary(data)
                self.assertEqual(g, Glossary())
                self.assertTrue(g.is_empty())

    def test_blank_sections_are_empty(self) -> None:
        # YAML `terms:` để trống -> None.
        g = parse_glossary({"context": None, "characters": None, "address": None, "terms": None, "skip": None})
        self.assertTrue(g.is_empty())

    def test_not_a_mapping(self) -> None:
        for data in ([], "text", 3):
            with self.subTest(data=data), self.assertRaises(GlossaryError):
                parse_glossary(data)

    def test_error_is_translation_error_and_names_source(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "my/file.yaml") as ctx:
            parse_glossary({"context": 5}, source="my/file.yaml")
        self.assertIsInstance(ctx.exception, TranslationError)

    def test_unknown_top_level_key(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "characterz") as ctx:
            parse_glossary({"characterz": []})
        # Thông báo phải nêu key hợp lệ.
        self.assertIn("characters", str(ctx.exception))

    def test_unknown_key_in_character(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "alias"):
            parse_glossary({"characters": [{"name": "A", "alias": ["x"]}]})

    def test_unknown_key_in_address(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "selff"):
            parse_glossary(
                {"address": [{"speaker": "A", "listener": "B", "selff": "x", "self": "con", "other": "ba"}]}
            )

    def test_wrong_types(self) -> None:
        bad = [
            {"context": 5},
            {"context": ["a"]},
            {"characters": {"name": "A"}},
            {"characters": ["A"]},
            {"characters": [{"name": 5}]},
            {"characters": [{"name": "A", "aliases": "x"}]},
            {"characters": [{"name": "A", "aliases": [1]}]},
            {"characters": [{"name": "A", "note": 3}]},
            {"characters": [{"name": "A", "vi": []}]},
            {"address": {"speaker": "A"}},
            {"address": ["A"]},
            {"terms": ["a", "b"]},
            {"terms": {"a": 1}},
            {"terms": {1: "a"}},
            {"terms": {"a": ""}},
            {"skip": "abc"},
            {"skip": [1]},
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(GlossaryError):
                parse_glossary(data)

    def test_character_requires_name(self) -> None:
        for character in ({"vi": "x"}, {"name": ""}, {"name": "   "}, {"name": None}):
            with self.subTest(character=character), self.assertRaisesRegex(GlossaryError, "name"):
                parse_glossary({"characters": [character]})

    def test_address_requires_all_four_keys(self) -> None:
        full = {"speaker": "A", "listener": "B", "self": "con", "other": "ba"}
        for key in full:
            entry = {k: v for k, v in full.items() if k != key}
            with self.subTest(missing=key), self.assertRaisesRegex(GlossaryError, key):
                parse_glossary({"address": [entry]})
        with self.assertRaises(GlossaryError):
            parse_glossary({"address": [{**full, "other": " "}]})

    def test_empty_vi_falls_back_to_name(self) -> None:
        for vi in ("", "  ", None):
            with self.subTest(vi=vi):
                g = parse_glossary({"characters": [{"name": "Pip", "vi": vi}]})
                self.assertEqual(g.characters[0].vi, "Pip")
        self.assertEqual(parse_glossary({"characters": [{"name": "Pip"}]}).characters[0].vi, "Pip")

    def test_aliases_drop_duplicates_empty_and_name(self) -> None:
        g = parse_glossary(
            {
                "characters": [
                    {
                        "name": "Little Hare",
                        "aliases": ["little hare", "Lil Hare", "LIL HARE", " ", "Lil  Hare", "Lil Hare"],
                    }
                ]
            }
        )
        # "little hare" trùng name (khác hoa thường), "LIL HARE"/"Lil Hare" trùng nhau,
        # "Lil  Hare" (hai dấu cách) là alias khác thật.
        self.assertEqual(g.characters[0].aliases, ("Lil Hare", "Lil  Hare"))


class TestApplyAliases(unittest.TestCase):
    def setUp(self) -> None:
        self.g = parse_glossary(
            {
                "characters": [
                    {"name": "Little Nutbrown Hare", "aliases": ["Little Nut Brown Hair", "Nut Brown Hair"]},
                    {"name": "Big Nutbrown Hare", "aliases": ["Big Nut Brown Hair"]},
                ]
            }
        )

    def test_case_insensitive_and_uses_canonical_case(self) -> None:
        self.assertEqual(
            self.g.apply_aliases("little nut brown hair said hi"),
            "Little Nutbrown Hare said hi",
        )
        self.assertEqual(self.g.apply_aliases("LITTLE NUT BROWN HAIR"), "Little Nutbrown Hare")

    def test_word_boundary(self) -> None:
        g = parse_glossary({"characters": [{"name": "Hare", "aliases": ["Hair"]}]})
        self.assertEqual(g.apply_aliases("Hairy Hair"), "Hairy Hare")
        self.assertEqual(g.apply_aliases("the hair, the hair."), "the Hare, the Hare.")
        self.assertEqual(g.apply_aliases("chair"), "chair")

    def test_longer_alias_wins(self) -> None:
        # "Big Nut Brown Hair" phải ăn cả cụm, không để alias ngắn "Nut Brown Hair"
        # thay giữa cụm rồi sót "Big ".
        self.assertEqual(self.g.apply_aliases("Big Nut Brown Hair"), "Big Nutbrown Hare")
        self.assertEqual(self.g.apply_aliases("Nut Brown Hair"), "Little Nutbrown Hare")

    def test_single_pass_does_not_rescan_replacement(self) -> None:
        g = parse_glossary(
            {"characters": [{"name": "Hair", "aliases": ["Hare"]}, {"name": "Hare", "aliases": ["Hair"]}]}
        )
        # Nếu quét lại phần vừa thay thì "Hare" -> "Hair" -> "Hare" ...
        self.assertEqual(g.apply_aliases("Hare and Hair"), "Hair and Hare")

    def test_regex_special_characters_are_escaped(self) -> None:
        g = parse_glossary({"characters": [{"name": "Mr. Fox", "aliases": ["Mr. (Fox)", "Mr.+Fox"]}]})
        self.assertEqual(g.apply_aliases("Hi Mr. (Fox)!"), "Hi Mr. Fox!")
        self.assertEqual(g.apply_aliases("MrXFox"), "MrXFox")

    def test_no_alias_returns_text_unchanged(self) -> None:
        text = "Nothing to replace here."
        self.assertIs(Glossary().apply_aliases(text), text)
        g = parse_glossary({"characters": [{"name": "Pip"}]})
        self.assertIs(g.apply_aliases(text), text)


class TestShouldSkip(unittest.TestCase):
    def test_substring_case_insensitive(self) -> None:
        g = Glossary(skip=("support Storybook Nanny on Patreon",))
        self.assertTrue(g.should_skip("Please SUPPORT storybook nanny on patreon. Thanks!"))
        self.assertFalse(g.should_skip("Storybook Nanny reads a story."))

    def test_empty_skip_is_false(self) -> None:
        self.assertFalse(Glossary().should_skip("anything"))


class TestMergeGlossaries(unittest.TestCase):
    def test_override_replaces_whole_character_entry(self) -> None:
        base = parse_glossary(
            {"characters": [{"name": "Pip", "vi": "Bé Pip", "aliases": ["Pipp"], "note": "cũ"}]}
        )
        override = parse_glossary({"characters": [{"name": "pip", "vi": "Pip Con"}]})
        merged = merge_glossaries(base, override)
        self.assertEqual(len(merged.characters), 1)
        # Thay cả entry: alias/note của base không sót lại.
        self.assertEqual(merged.characters[0], Character(name="pip", vi="Pip Con"))

    def test_new_entries_are_appended_in_order(self) -> None:
        base = parse_glossary({"characters": [{"name": "A"}, {"name": "B"}]})
        override = parse_glossary({"characters": [{"name": "B", "vi": "Bê"}, {"name": "C"}]})
        merged = merge_glossaries(base, override)
        self.assertEqual([c.name for c in merged.characters], ["A", "B", "C"])
        self.assertEqual(merged.characters[1].vi, "Bê")

    def test_address_keyed_by_speaker_listener(self) -> None:
        def entry(s: str, l: str, me: str, other: str) -> dict[str, str]:
            return {"speaker": s, "listener": l, "self": me, "other": other}

        base = parse_glossary({"address": [entry("A", "B", "con", "ba"), entry("B", "A", "ba", "con")]})
        override = parse_glossary({"address": [entry("a", "b", "em", "anh"), entry("A", "C", "tôi", "bạn")]})
        merged = merge_glossaries(base, override)
        self.assertEqual(len(merged.address), 3)
        self.assertEqual((merged.address[0].self_term, merged.address[0].other_term), ("em", "anh"))
        self.assertEqual(merged.address[1].speaker, "B")
        self.assertEqual(merged.address[2].listener, "C")

    def test_context_empty_override_does_not_clobber(self) -> None:
        base = Glossary(context="base ctx")
        self.assertEqual(merge_glossaries(base, Glossary()).context, "base ctx")
        self.assertEqual(merge_glossaries(base, Glossary(context="ep ctx")).context, "ep ctx")
        self.assertEqual(merge_glossaries(Glossary(), base).context, "base ctx")

    def test_terms_and_skip_merge(self) -> None:
        base = Glossary(terms=(("Hare", "thỏ"), ("Moon", "mặt trăng")), skip=("a", "b"))
        override = Glossary(terms=(("hare", "thỏ rừng"), ("Star", "ngôi sao")), skip=("B", "c"))
        merged = merge_glossaries(base, override)
        # Override thắng, khoá không phân biệt hoa thường, thứ tự ổn định.
        self.assertEqual(
            merged.terms,
            (("hare", "thỏ rừng"), ("Moon", "mặt trăng"), ("Star", "ngôi sao")),
        )
        self.assertEqual(merged.skip, ("a", "b", "c"))

    def test_merge_is_deterministic(self) -> None:
        a, b = _hare_glossary(), Glossary(terms=(("x", "y"),))
        self.assertEqual(merge_glossaries(a, b), merge_glossaries(a, b))


class TestSha256(unittest.TestCase):
    def test_stable_across_yaml_formatting(self) -> None:
        import yaml

        text_a = (
            "# comment\n"
            "context: hi\n"
            "characters:\n"
            "  - name: A\n"
            "    vi: Ây\n"
            "    aliases: [aa, ay]\n"
            "terms: {x: y, z: w}\n"
        )
        text_b = (
            "terms:\n"
            "    z:   w\n"
            "    x:   y   # comment khác\n"
            "\n\n"
            "characters:\n"
            "- aliases:\n"
            "  - aa\n"
            "  - ay\n"
            "  vi: Ây\n"
            "  name: A\n"
            "context: hi\n"
        )
        a = parse_glossary(yaml.safe_load(text_a))
        b = parse_glossary(yaml.safe_load(text_b))
        self.assertEqual(a.sha256(), b.sha256())

    def test_changing_a_vi_changes_hash(self) -> None:
        data = _full_data()
        before = parse_glossary(data).sha256()
        data["characters"][0]["vi"] = "Thỏ Nhỏ"
        self.assertNotEqual(before, parse_glossary(data).sha256())

    def test_hash_is_hex_sha256(self) -> None:
        digest = Glossary().sha256()
        self.assertEqual(len(digest), 64)
        int(digest, 16)

    def test_to_dict_has_five_keys_even_when_empty(self) -> None:
        self.assertEqual(
            Glossary().to_dict(),
            {"context": "", "characters": [], "address": [], "terms": {}, "skip": []},
        )


class TestLoadEffectiveGlossary(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.episode = self.root / "ep"
        self.episode.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, path: Path, text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        return path

    def test_no_files(self) -> None:
        self.assertEqual(load_effective_glossary(self.episode, None), (None, []))

    def test_episode_only(self) -> None:
        path = self._write(self.episode / GLOSSARY_FILENAME, "terms: {a: b}\n")
        glossary, paths = load_effective_glossary(self.episode, None)
        self.assertEqual(glossary, Glossary(terms=(("a", "b"),)))
        self.assertEqual(paths, [path])

    def test_shared_only(self) -> None:
        shared = self._write(self.root / "shared.yaml", "context: chung\n")
        glossary, paths = load_effective_glossary(self.episode, shared)
        self.assertEqual(glossary, Glossary(context="chung"))
        self.assertEqual(paths, [shared])

    def test_both_merged_in_order(self) -> None:
        shared = self._write(self.root / "shared.yaml", "context: chung\nterms: {a: 1x, b: 2x}\n")
        episode_file = self._write(self.episode / GLOSSARY_FILENAME, "terms: {b: 2y}\n")
        glossary, paths = load_effective_glossary(self.episode, shared)
        assert glossary is not None
        self.assertEqual(glossary.context, "chung")
        self.assertEqual(glossary.terms, (("a", "1x"), ("b", "2y")))
        self.assertEqual(paths, [shared, episode_file])

    def test_missing_shared_path_is_error(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "nope.yaml"):
            load_effective_glossary(self.episode, self.root / "nope.yaml")

    def test_empty_files_mean_no_glossary(self) -> None:
        self._write(self.episode / GLOSSARY_FILENAME, "# chỉ có comment\n")
        self.assertEqual(load_effective_glossary(self.episode, None), (None, []))
        shared = self._write(self.root / "shared.yaml", "{}\n")
        self.assertEqual(load_effective_glossary(self.episode, shared), (None, []))

    def test_broken_yaml_names_path(self) -> None:
        path = self._write(self.episode / GLOSSARY_FILENAME, "context: [unclosed\n")
        with self.assertRaisesRegex(GlossaryError, "glossary.yaml") as ctx:
            load_effective_glossary(self.episode, None)
        self.assertIn(str(path), str(ctx.exception))

    def test_invalid_content_names_path(self) -> None:
        path = self._write(self.episode / GLOSSARY_FILENAME, "characterz: []\n")
        with self.assertRaises(GlossaryError) as ctx:
            load_effective_glossary(self.episode, None)
        self.assertIn(str(path), str(ctx.exception))

    def test_load_glossary_missing_file(self) -> None:
        with self.assertRaises(GlossaryError):
            load_glossary(self.root / "nope.yaml")


class TestWriteGlossary(unittest.TestCase):
    def test_round_trip_with_vietnamese(self) -> None:
        glossary = Glossary(
            context="Truyện thiếu nhi: \"Thỏ Con\" và Thỏ Cha; giọng kể ấm áp, câu ngắn, dễ nghe cho trẻ nhỏ. "
            "Dòng này cố ý rất dài để kiểm tra việc YAML tự ngắt dòng khi ghi ra file.",
            characters=(
                Character("Little Nutbrown Hare", "Thỏ Con", ("Little Nut Brown Hair", "no"), "thỏ con: nhân vật chính"),
                Character("Big Nutbrown Hare", "Thỏ Cha"),
            ),
            address=(Address("Little Nutbrown Hare", "Big Nutbrown Hare", "con", "ba"),),
            terms=(("Hare", "thỏ rừng"), ("yes", "vâng"), ("1.5", "một rưỡi")),
            skip=("support Storybook Nanny on Patreon",),
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "glossary.yaml"
            write_glossary(glossary, path, header="Dòng một\n\nDòng ba")
            text = path.read_text(encoding="utf-8")
            self.assertEqual(load_glossary(path), glossary)
            self.assertFalse(path.with_name("glossary.yaml.tmp").exists())

        # Header luôn là comment YAML, tiếng Việt không bị escape.
        self.assertTrue(text.startswith("# Dòng một\n#\n# Dòng ba\n\n"))
        self.assertIn("Thỏ Con", text)
        self.assertNotIn("\\u", text)

    def test_empty_glossary_writes_all_five_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "glossary.yaml"
            write_glossary(Glossary(), path, header="h")
            text = path.read_text(encoding="utf-8")
            for key in ("context:", "characters: []", "address: []", "terms: {}", "skip: []"):
                self.assertIn(key, text)
            self.assertEqual(load_glossary(path), Glossary())

    def test_overwrites_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "glossary.yaml"
            path.write_text("cũ", encoding="utf-8")
            write_glossary(Glossary(context="mới"), path, header="h")
            self.assertEqual(load_glossary(path).context, "mới")


if __name__ == "__main__":
    unittest.main()

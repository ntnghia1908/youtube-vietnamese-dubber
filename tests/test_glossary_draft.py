"""Unit test cho ``app.translation.glossary_draft`` (Checkpoint 6.5).

Translator giả trả JSON dựng sẵn — không gọi Ollama.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.translation.base import (
    TranslationError,
    Translator,
    TranslatorConnectionError,
    TranslatorOutputError,
)
from app.translation.glossary import GLOSSARY_FILENAME, GlossaryError, load_glossary
from app.translation.glossary_draft import (
    _DRAFT_ITEM_COUNT,
    GLOSSARY_SCHEMA,
    build_draft_messages,
    draft_glossary_file,
    generate_glossary_draft,
)


def _draft_json(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "context": "Truyện thiếu nhi đọc to.",
        "characters": [
            {
                "name": "Little Nutbrown Hare",
                "vi": "Thỏ Con",
                "aliases": ["Little Nut Brown Hair"],
                "note": "nhân vật chính",
            }
        ],
        "address": [
            {"speaker": "Little Nutbrown Hare", "listener": "Big Nutbrown Hare", "self": "con", "other": "ba"}
        ],
        "terms": [{"source": "hare", "vi": "thỏ rừng"}],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class ScriptedTranslator(Translator):
    """Mỗi lần ``_complete_json`` lấy một phần tử trong ``script``: chuỗi thì trả về,
    Exception thì raise."""

    provider = "fake"

    def __init__(self, script: list[Any]) -> None:
        super().__init__("fake-model")
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def _complete_json(self, messages: Any, *, schema: Any, item_count: int) -> str:
        self.calls.append({"messages": messages, "schema": schema, "item_count": item_count})
        if not self.script:
            raise AssertionError("Model bị gọi nhiều hơn số lần đã dựng sẵn trong script.")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class DraftTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.logs: list[str] = []
        self.sleeps: list[float] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_transcript(self, texts: list[str], language: str = "en") -> Path:
        path = self.dir / "transcript.json"
        segments = [
            {"id": i, "start": float(i), "end": i + 1.0, "text": text} for i, text in enumerate(texts, start=1)
        ]
        path.write_text(json.dumps({"language": language, "segments": segments}), encoding="utf-8")
        return path

    def _write_metadata(self, title: str = "Guess How Much I Love You") -> Path:
        path = self.dir / "metadata.json"
        path.write_text(json.dumps({"title": title, "uploader": "Storybook Nanny"}), encoding="utf-8")
        return path

    def _generate(self, translator: Translator, transcript: Path, **kwargs: Any):
        params: dict[str, Any] = {
            "metadata_path": self.dir / "metadata.json",
            "target_language": "vi",
            "log": self.logs.append,
            "sleep": self.sleeps.append,
        }
        params.update(kwargs)
        return generate_glossary_draft(transcript, translator, **params)


class TestGenerateGlossaryDraft(DraftTestBase):
    def test_valid_draft(self) -> None:
        transcript = self._write_transcript(["Little Nut Brown Hair went to bed."])
        translator = ScriptedTranslator([_draft_json()])
        g = self._generate(translator, transcript)

        self.assertEqual(g.context, "Truyện thiếu nhi đọc to.")
        self.assertEqual(g.characters[0].name, "Little Nutbrown Hare")
        self.assertEqual(g.characters[0].vi, "Thỏ Con")
        self.assertEqual(g.characters[0].aliases, ("Little Nut Brown Hair",))
        self.assertEqual(g.address[0].self_term, "con")
        # terms: list [{source, vi}] -> dict/tuple cặp.
        self.assertEqual(g.terms, (("hare", "thỏ rừng"),))
        self.assertEqual(g.skip, ())
        call = translator.calls[0]
        self.assertIs(call["schema"], GLOSSARY_SCHEMA)
        self.assertEqual(call["item_count"], _DRAFT_ITEM_COUNT)

    def test_schema_has_no_skip_and_requires_four_keys(self) -> None:
        self.assertNotIn("skip", GLOSSARY_SCHEMA["properties"])
        self.assertEqual(GLOSSARY_SCHEMA["required"], ["context", "characters", "address", "terms"])

    def test_skip_from_model_is_ignored(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator([_draft_json(skip=["Hello."])])
        self.assertEqual(self._generate(translator, transcript).skip, ())

    def test_cleaning_drops_nameless_characters_and_caps_counts(self) -> None:
        transcript = self._write_transcript(["Hello."])
        characters = [{"name": "", "vi": "x", "aliases": [], "note": ""}, {"vi": "y"}, "rác"]
        characters += [{"name": f"C{i}", "vi": f"V{i}", "aliases": [], "note": ""} for i in range(40)]
        address = [{"speaker": "A", "listener": "B", "self": "", "other": "x"}]  # thiếu self -> bỏ
        address += [{"speaker": f"S{i}", "listener": "L", "self": "con", "other": "ba"} for i in range(40)]
        terms = [{"source": "", "vi": "x"}, {"source": "a", "vi": ""}]
        terms += [{"source": f"t{i}", "vi": f"v{i}"} for i in range(80)]
        translator = ScriptedTranslator([_draft_json(characters=characters, address=address, terms=terms)])

        g = self._generate(translator, transcript)
        self.assertEqual(len(g.characters), 30)
        self.assertEqual(g.characters[0].name, "C0")
        self.assertEqual(len(g.address), 30)
        self.assertEqual(g.address[0].speaker, "S0")
        self.assertEqual(len(g.terms), 60)
        self.assertEqual(g.terms[0], ("t0", "v0"))

    def test_invalid_json_retries_max_attempts_then_raises(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator(["{not json", "[]", json.dumps({"context": "x"})])
        with self.assertRaisesRegex(GlossaryError, "3 lần"):
            self._generate(translator, transcript, max_attempts=3)
        self.assertEqual(len(translator.calls), 3)
        # Lỗi output không cần chờ backoff.
        self.assertEqual(self.sleeps, [])

    def test_max_attempts_is_respected(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator(["{bad"] * 5)
        with self.assertRaises(GlossaryError):
            self._generate(translator, transcript, max_attempts=2)
        self.assertEqual(len(translator.calls), 2)

    def test_second_attempt_succeeds(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator(["{bad", _draft_json()])
        g = self._generate(translator, transcript)
        self.assertEqual(len(translator.calls), 2)
        self.assertEqual(g.characters[0].name, "Little Nutbrown Hare")

    def test_validation_error_is_retried(self) -> None:
        # `characters` không phải list -> TranslatorOutputError; alias sai kiểu được làm sạch.
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator([_draft_json(characters="oops"), _draft_json()])
        self._generate(translator, transcript)
        self.assertEqual(len(translator.calls), 2)

    def test_output_error_from_provider_is_retried(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator([TranslatorOutputError("cắt"), _draft_json()])
        self._generate(translator, transcript)
        self.assertEqual(len(translator.calls), 2)

    def test_connection_error_backs_off_2_then_5(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator(
            [TranslatorConnectionError("down"), TranslatorConnectionError("down"), _draft_json()]
        )
        self._generate(translator, transcript, max_attempts=3)
        self.assertEqual(self.sleeps, [2.0, 5.0])
        self.assertEqual(len(translator.calls), 3)

    def test_connection_error_exhausts_attempts(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator([TranslatorConnectionError("mất kết nối")] * 3)
        with self.assertRaisesRegex(GlossaryError, "mất kết nối"):
            self._generate(translator, transcript, max_attempts=3)
        self.assertEqual(self.sleeps, [2.0, 5.0])

    def test_config_error_is_not_retried(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator([TranslationError("model not found")])
        with self.assertRaisesRegex(TranslationError, "model not found"):
            self._generate(translator, transcript)
        self.assertEqual(len(translator.calls), 1)

    def test_prompt_contains_title_and_transcript(self) -> None:
        transcript = self._write_transcript(["Line one about Hare.", "Line two."])
        self._write_metadata("My Special Title")
        translator = ScriptedTranslator([_draft_json()])
        self._generate(translator, transcript)

        messages = translator.calls[0]["messages"]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("My Special Title", messages[1]["content"])
        self.assertIn("Line one about Hare.\nLine two.", messages[1]["content"])
        system = messages[0]["content"]
        for expected in ("English", "Vietnamese", "aliases", "hare", "speech-to-text"):
            self.assertIn(expected, system)

    def test_long_transcript_is_cut_at_line_boundary(self) -> None:
        transcript = self._write_transcript(["aaaa aaaa", "bbbb bbbb", "cccc cccc", "dddd dddd"])
        translator = ScriptedTranslator([_draft_json()])
        self._generate(translator, transcript, max_chars=20)

        user = translator.calls[0]["messages"][1]["content"]
        # 9 + 1 + 9 = 19 <= 20: giữ hai dòng đầu, không cụt giữa dòng thứ ba.
        self.assertIn("aaaa aaaa\nbbbb bbbb", user)
        self.assertNotIn("cccc", user)
        self.assertTrue(any("chỉ dùng phần đầu transcript" in line for line in self.logs))

    def test_short_transcript_has_no_truncation_warning(self) -> None:
        transcript = self._write_transcript(["short"])
        self._generate(ScriptedTranslator([_draft_json()]), transcript)
        self.assertFalse(any("chỉ dùng phần đầu" in line for line in self.logs))

    def test_missing_or_broken_metadata_still_runs(self) -> None:
        transcript = self._write_transcript(["Hello."])
        translator = ScriptedTranslator([_draft_json(), _draft_json()])
        self._generate(translator, transcript)  # không có metadata.json
        (self.dir / "metadata.json").write_text("{hỏng", encoding="utf-8")
        self._generate(translator, transcript)
        self._generate(ScriptedTranslator([_draft_json()]), transcript, metadata_path=None)
        for call in translator.calls:
            self.assertIn("Title: (unknown)", call["messages"][1]["content"])

    def test_missing_transcript(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "transcribe"):
            self._generate(ScriptedTranslator([_draft_json()]), self.dir / "transcript.json")

    def test_build_draft_messages_uses_language_names(self) -> None:
        messages = build_draft_messages(
            title="T", transcript_text="text", source_language="zh", target_language="vi"
        )
        self.assertIn("Chinese", messages[0]["content"])
        self.assertIn("Vietnamese", messages[0]["content"])
        self.assertIn("Title: T", messages[1]["content"])


class TestDraftGlossaryFile(DraftTestBase):
    def _episode(self) -> Path:
        self._write_transcript(["Little Nut Brown Hair went to bed."])
        self._write_metadata()
        return self.dir

    def _draft(self, translator: Translator, **kwargs: Any):
        params: dict[str, Any] = {"target_language": "vi", "log": self.logs.append, "sleep": self.sleeps.append}
        params.update(kwargs)
        return draft_glossary_file(self.dir, translator, **params)

    def test_writes_new_file_with_header(self) -> None:
        self._episode()
        translator = ScriptedTranslator([_draft_json()])
        result = self._draft(translator)

        self.assertFalse(result.skipped)
        self.assertIsNone(result.backup_path)
        self.assertEqual(result.glossary_path, self.dir / GLOSSARY_FILENAME)
        text = result.glossary_path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# "))
        header = text.split("\n\n", 1)[0]
        self.assertTrue(all(line.startswith("#") for line in header.splitlines()))
        for section in ("context", "characters", "address", "terms", "skip"):
            self.assertIn(section, header)
        self.assertIn("NHÁP", header)
        self.assertIn("support Storybook Nanny on Patreon", header)  # ví dụ skip trong comment
        # Parse lại được và bằng đúng kết quả trả về.
        self.assertEqual(load_glossary(result.glossary_path), result.glossary)
        self.assertEqual(result.glossary.skip, ())
        self.assertIn("skip: []", text)

    def test_existing_file_without_force_is_skipped_and_model_not_called(self) -> None:
        self._episode()
        path = self.dir / GLOSSARY_FILENAME
        path.write_text("context: người dùng tự sửa\n", encoding="utf-8")
        translator = ScriptedTranslator([_draft_json()])

        result = self._draft(translator)
        self.assertTrue(result.skipped)
        self.assertEqual(translator.calls, [])
        self.assertEqual(result.glossary.context, "người dùng tự sửa")
        self.assertEqual(path.read_text(encoding="utf-8"), "context: người dùng tự sửa\n")
        self.assertFalse((self.dir / "glossary.yaml.bak").exists())

    def test_skip_does_not_need_transcript(self) -> None:
        (self.dir / GLOSSARY_FILENAME).write_text("context: x\n", encoding="utf-8")
        self.assertTrue(self._draft(ScriptedTranslator([])).skipped)

    def test_skip_with_broken_existing_file_raises(self) -> None:
        (self.dir / GLOSSARY_FILENAME).write_text("context: [hỏng\n", encoding="utf-8")
        with self.assertRaises(GlossaryError):
            self._draft(ScriptedTranslator([]))

    def test_force_backs_up_old_content_then_writes_draft(self) -> None:
        self._episode()
        path = self.dir / GLOSSARY_FILENAME
        old = "context: bản cũ của người dùng\n"
        path.write_text(old, encoding="utf-8")
        (self.dir / "glossary.yaml.bak").write_text("bak cũ hơn", encoding="utf-8")
        translator = ScriptedTranslator([_draft_json()])

        result = self._draft(translator, force=True)
        self.assertFalse(result.skipped)
        self.assertEqual(result.backup_path, self.dir / "glossary.yaml.bak")
        self.assertEqual(result.backup_path.read_text(encoding="utf-8"), old)
        self.assertEqual(len(translator.calls), 1)
        self.assertEqual(load_glossary(path).characters[0].name, "Little Nutbrown Hare")

    def test_force_without_existing_file_makes_no_backup(self) -> None:
        self._episode()
        result = self._draft(ScriptedTranslator([_draft_json()]), force=True)
        self.assertIsNone(result.backup_path)
        self.assertFalse((self.dir / "glossary.yaml.bak").exists())

    def test_failed_generation_leaves_existing_file_and_no_backup(self) -> None:
        self._episode()
        path = self.dir / GLOSSARY_FILENAME
        path.write_text("context: giữ nguyên\n", encoding="utf-8")
        with self.assertRaises(GlossaryError):
            self._draft(ScriptedTranslator(["{bad"] * 3), force=True)
        self.assertEqual(path.read_text(encoding="utf-8"), "context: giữ nguyên\n")
        self.assertFalse((self.dir / "glossary.yaml.bak").exists())

    def test_missing_transcript(self) -> None:
        with self.assertRaisesRegex(GlossaryError, "transcribe"):
            self._draft(ScriptedTranslator([_draft_json()]))
        self.assertFalse((self.dir / GLOSSARY_FILENAME).exists())


if __name__ == "__main__":
    unittest.main()

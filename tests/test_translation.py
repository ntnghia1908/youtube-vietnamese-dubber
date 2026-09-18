"""Unit test cho ``app.translation``.

Không gọi Ollama thật: stage dùng ``FakeTranslator``, còn
``OllamaTranslator`` được test với ``urlopen`` bị mock.
"""

from __future__ import annotations

import hashlib
import io
import json
import unittest
import urllib.error
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from app.config import TranslationConfig
from app.translation import create_translator
from app.translation.base import (
    TranslationError,
    Translator,
    TranslatorConnectionError,
    TranslatorOutputError,
    parse_translations,
)
from app.translation.ollama import OllamaTranslator, resolve_host
from app.translation.prompt import ContextLine, SourceLine, build_messages
from app.translation.translate import partial_path_for, translate_transcript


def _lines(*ids: int) -> list[SourceLine]:
    return [SourceLine(i, f"line {i}", 1.0) for i in ids]


class TestParseTranslations(unittest.TestCase):
    def test_valid_output(self) -> None:
        raw = json.dumps({"translations": [{"id": 1, "text": " một "}, {"id": 2, "text": "hai"}]})
        self.assertEqual(parse_translations(raw, _lines(1, 2)), {1: "một", 2: "hai"})

    def test_accepts_bare_array(self) -> None:
        raw = json.dumps([{"id": 1, "text": "một"}])
        self.assertEqual(parse_translations(raw, _lines(1)), {1: "một"})

    def test_invalid_json(self) -> None:
        with self.assertRaisesRegex(TranslatorOutputError, "JSON"):
            parse_translations('{"translations": [', _lines(1))

    def test_missing_id(self) -> None:
        raw = json.dumps({"translations": [{"id": 1, "text": "một"}]})
        with self.assertRaisesRegex(TranslatorOutputError, "thiếu id \\[2\\]"):
            parse_translations(raw, _lines(1, 2))

    def test_duplicate_id(self) -> None:
        raw = json.dumps({"translations": [{"id": 1, "text": "a"}, {"id": 1, "text": "b"}]})
        with self.assertRaisesRegex(TranslatorOutputError, "trùng id"):
            parse_translations(raw, _lines(1))

    def test_unexpected_id(self) -> None:
        raw = json.dumps({"translations": [{"id": 1, "text": "a"}, {"id": 9, "text": "b"}]})
        with self.assertRaisesRegex(TranslatorOutputError, "id lạ"):
            parse_translations(raw, _lines(1))

    def test_string_id_rejected(self) -> None:
        raw = json.dumps({"translations": [{"id": "1", "text": "a"}]})
        with self.assertRaises(TranslatorOutputError):
            parse_translations(raw, _lines(1))

    def test_empty_translation_for_non_empty_source(self) -> None:
        raw = json.dumps({"translations": [{"id": 1, "text": "  "}]})
        with self.assertRaisesRegex(TranslatorOutputError, "rỗng"):
            parse_translations(raw, _lines(1))


class TestBuildMessages(unittest.TestCase):
    def test_includes_lines_context_and_languages(self) -> None:
        messages = build_messages(
            [SourceLine(7, "Where are you going?", 2.345)],
            context=[ContextLine(6, "Hi.", "Chào.")],
            source_language="en",
            target_language="vi",
        )
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("English", messages[0]["content"])
        self.assertIn("Vietnamese", messages[0]["content"])
        user = messages[1]["content"]
        self.assertIn('"id": 7', user)
        self.assertIn('"duration": 2.3', user)
        self.assertIn("Chào.", user)

    def test_no_context_section_when_empty(self) -> None:
        messages = build_messages(
            _lines(1), context=[], source_language="zh", target_language="vi"
        )
        self.assertNotIn("Previous lines", messages[1]["content"])


class FakeTranslator(Translator):
    """Translator giả: mỗi lần gọi chạy ``behaviour(ids, call_no)``.

    ``behaviour`` trả về dict {id: text} hoặc raise lỗi để mô phỏng model.
    """

    provider = "fake"

    def __init__(
        self,
        behaviour: Callable[[list[int], int], dict[int, str]] | None = None,
        *,
        model: str = "fake-model",
    ) -> None:
        super().__init__(model)
        self.calls: list[dict[str, Any]] = []
        self.behaviour = behaviour or (lambda ids, n: {i: f"vi {i}" for i in ids})

    def translate_batch(
        self,
        lines: Sequence[SourceLine],
        *,
        context: Sequence[ContextLine],
        source_language: str,
        target_language: str,
    ) -> dict[int, str]:
        ids = [ln.id for ln in lines]
        self.calls.append({"ids": ids, "context": [c.id for c in context]})
        return self.behaviour(ids, len(self.calls))

    def _complete_json(self, messages: Any, *, schema: Any, item_count: int) -> str:
        raise NotImplementedError


class TestTranslateTranscript(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.transcript = self.dir / "transcript.json"
        self.translated = self.dir / "translated.json"
        self.logs: list[str] = []
        self.sleeps: list[float] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_transcript(self, count: int, *, empty_ids: Sequence[int] = ()) -> None:
        segments = [
            {"id": i, "start": float(i), "end": i + 1.5, "text": "" if i in empty_ids else f"line {i}"}
            for i in range(1, count + 1)
        ]
        self.transcript.write_text(
            json.dumps({"language": "en", "segments": segments}), encoding="utf-8"
        )

    def _run(self, translator: Translator, **kwargs: Any):
        params: dict[str, Any] = {
            "target_language": "vi",
            "batch_size": 4,
            "context_size": 2,
            "max_attempts": 3,
            "log": self.logs.append,
            "sleep": self.sleeps.append,
        }
        params.update(kwargs)
        return translate_transcript(self.transcript, self.translated, translator, **params)

    def test_translates_in_batches_and_writes_schema(self) -> None:
        self._write_transcript(10)
        translator = FakeTranslator()
        result = self._run(translator)

        self.assertEqual([c["ids"] for c in translator.calls], [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10]])
        self.assertFalse(result.skipped)
        data = json.loads(self.translated.read_text(encoding="utf-8"))
        self.assertEqual(data["source_language"], "en")
        self.assertEqual(data["target_language"], "vi")
        self.assertEqual(data["translator"], {"provider": "fake", "model": "fake-model"})
        self.assertEqual(len(data["segments"]), 10)
        self.assertEqual(
            data["segments"][0],
            {"id": 1, "start": 1.0, "end": 2.5, "source_text": "line 1", "translated_text": "vi 1"},
        )
        self.assertFalse(partial_path_for(self.translated).exists())

    def test_context_is_previous_translated_lines(self) -> None:
        self._write_transcript(10)
        translator = FakeTranslator()
        self._run(translator)
        self.assertEqual([c["context"] for c in translator.calls], [[], [3, 4], [7, 8]])

    def test_skips_when_translated_exists(self) -> None:
        self._write_transcript(3)
        self._run(FakeTranslator())
        translator = FakeTranslator()
        result = self._run(translator)
        self.assertTrue(result.skipped)
        self.assertEqual(translator.calls, [])
        self.assertEqual(result.segments[2].translated_text, "vi 3")
        self.assertEqual(result.failed_ids, [])

    def test_force_retranslates(self) -> None:
        self._write_transcript(3)
        self._run(FakeTranslator())
        translator = FakeTranslator(lambda ids, n: {i: f"mới {i}" for i in ids})
        result = self._run(translator, force=True)
        self.assertEqual(len(translator.calls), 1)
        self.assertEqual(result.segments[0].translated_text, "mới 1")

    def test_interrupted_force_run_resumes_instead_of_keeping_old_file(self) -> None:
        """Regression: --force bị ngắt giữa chừng, chạy lại không --force
        từng SKIP vì translated.json cũ vẫn còn."""
        self._write_transcript(4)
        self._run(FakeTranslator(lambda ids, n: {i: f"cũ {i}" for i in ids}))

        def die_on_second_batch(ids: list[int], n: int) -> dict[int, str]:
            if 3 in ids:
                raise TranslationError("bị ngắt")
            return {i: f"mới {i}" for i in ids}

        with self.assertRaises(TranslationError):
            self._run(FakeTranslator(die_on_second_batch), batch_size=2, force=True)

        translator = FakeTranslator(lambda ids, n: {i: f"mới {i}" for i in ids})
        result = self._run(translator, batch_size=2)
        self.assertFalse(result.skipped)
        self.assertEqual(translator.calls[0]["ids"], [3, 4])
        self.assertEqual([s.translated_text for s in result.segments], ["mới 1", "mới 2", "mới 3", "mới 4"])

    def test_retries_output_error_then_succeeds(self) -> None:
        self._write_transcript(2)

        def flaky(ids: list[int], n: int) -> dict[int, str]:
            if n == 1:
                raise TranslatorOutputError("thiếu id")
            return {i: f"vi {i}" for i in ids}

        translator = FakeTranslator(flaky)
        self._run(translator)
        self.assertEqual(len(translator.calls), 2)
        self.assertEqual(self.sleeps, [2.0])

    def test_splits_batch_when_output_keeps_failing(self) -> None:
        self._write_transcript(4)

        # Model chỉ dịch được batch <= 2 dòng.
        def small_only(ids: list[int], n: int) -> dict[int, str]:
            if len(ids) > 2:
                raise TranslatorOutputError("gộp dòng")
            return {i: f"vi {i}" for i in ids}

        translator = FakeTranslator(small_only)
        result = self._run(translator)
        self.assertEqual([c["ids"] for c in translator.calls], [[1, 2, 3, 4]] * 3 + [[1, 2], [3, 4]])
        self.assertEqual(self.sleeps, [2.0, 5.0])
        self.assertEqual(len(result.segments), 4)
        # Nửa sau dùng nửa đầu làm ngữ cảnh.
        self.assertEqual(translator.calls[-1]["context"], [1, 2])

    def test_single_segment_failure_is_marked_failed_not_raised(self) -> None:
        """C3: một segment vẫn lỗi sau khi chia tới còn 1 dòng — không dừng
        cả stage, các segment khác vẫn dịch đủ và được ghi ra file."""
        self._write_transcript(6)

        def bad_segment_5(ids: list[int], n: int) -> dict[int, str]:
            if 5 in ids:
                raise TranslatorOutputError("không dịch nổi")
            return {i: f"vi {i}" for i in ids}

        result = self._run(FakeTranslator(bad_segment_5), batch_size=2)
        self.assertFalse(result.skipped)
        self.assertEqual(result.failed_ids, [5])
        self.assertEqual(
            [s.translated_text for s in result.segments],
            ["vi 1", "vi 2", "vi 3", "vi 4", "", "vi 6"],
        )
        self.assertTrue(self.translated.exists())
        self.assertFalse(partial_path_for(self.translated).exists())
        data = json.loads(self.translated.read_text(encoding="utf-8"))
        self.assertEqual(data["failed_ids"], [5])
        self.assertIn("transcript_sha256", data)

    def test_retries_only_failed_ids_from_previous_run(self) -> None:
        """C3: chạy lại (không --force) khi translated.json có failed_ids
        chỉ dịch lại đúng các id đó, giữ nguyên bản dịch cũ."""
        self._write_transcript(6)

        def bad_segment_5(ids: list[int], n: int) -> dict[int, str]:
            if 5 in ids:
                raise TranslatorOutputError("không dịch nổi")
            return {i: f"vi {i}" for i in ids}

        self._run(FakeTranslator(bad_segment_5), batch_size=2)

        translator = FakeTranslator()
        result = self._run(translator, batch_size=2)
        self.assertEqual([c["ids"] for c in translator.calls], [[5]])
        self.assertEqual(result.failed_ids, [])
        self.assertEqual(
            [s.translated_text for s in result.segments],
            ["vi 1", "vi 2", "vi 3", "vi 4", "vi 5", "vi 6"],
        )
        self.assertTrue(any("thử lại" in line and "id 5" in line for line in self.logs))

    def test_all_nonempty_segments_failing_raises(self) -> None:
        """C3: model/cấu hình hỏng hoàn toàn (không dịch nổi một dòng nào)
        vẫn phải raise — khác với một câu khó đơn lẻ."""
        self._write_transcript(3)

        def always_fail(ids: list[int], n: int) -> dict[int, str]:
            raise TranslatorOutputError("hỏng")

        with self.assertRaises(TranslationError):
            self._run(FakeTranslator(always_fail), batch_size=4)
        self.assertFalse(self.translated.exists())

    def test_connection_error_is_retried_but_not_split(self) -> None:
        self._write_transcript(4)

        def down(ids: list[int], n: int) -> dict[int, str]:
            raise TranslatorConnectionError("connection refused")

        translator = FakeTranslator(down)
        with self.assertRaisesRegex(TranslationError, "connection refused"):
            self._run(translator)
        self.assertEqual(len(translator.calls), 3)
        self.assertTrue(all(c["ids"] == [1, 2, 3, 4] for c in translator.calls))

    def test_config_error_is_not_retried(self) -> None:
        self._write_transcript(2)

        def not_found(ids: list[int], n: int) -> dict[int, str]:
            raise TranslationError("model not found")

        translator = FakeTranslator(not_found)
        with self.assertRaises(TranslationError):
            self._run(translator)
        self.assertEqual(len(translator.calls), 1)

    def test_partial_discarded_when_transcript_changes(self) -> None:
        self._write_transcript(4)

        def fail_second_batch(ids: list[int], n: int) -> dict[int, str]:
            if 3 in ids:
                raise TranslationError("stop")
            return {i: f"cũ {i}" for i in ids}

        with self.assertRaises(TranslationError):
            self._run(FakeTranslator(fail_second_batch), batch_size=2)
        self.assertTrue(partial_path_for(self.translated).exists())

        self._write_transcript(5)  # transcribe lại -> nội dung khác
        translator = FakeTranslator()
        result = self._run(translator, batch_size=2)
        self.assertEqual(translator.calls[0]["ids"], [1, 2])
        self.assertEqual(result.segments[0].translated_text, "vi 1")

    def test_partial_discarded_when_model_changes(self) -> None:
        """C5: partial dở dang bằng model A, chạy tiếp bằng model B —
        không được trộn hai model vào một translated.json, dịch lại từ đầu."""
        self._write_transcript(4)

        def fail_second_batch(ids: list[int], n: int) -> dict[int, str]:
            if 3 in ids:
                raise TranslationError("stop")
            return {i: f"cũ {i}" for i in ids}

        with self.assertRaises(TranslationError):
            self._run(FakeTranslator(fail_second_batch, model="model-a"), batch_size=2)
        self.assertTrue(partial_path_for(self.translated).exists())

        translator = FakeTranslator(model="model-b")
        result = self._run(translator, batch_size=2)
        self.assertEqual(translator.calls[0]["ids"], [1, 2])
        self.assertEqual(result.segments[0].translated_text, "vi 1")
        self.assertTrue(any("đang dùng" in line for line in self.logs))

    def test_partial_without_translator_key_resumes(self) -> None:
        """C5: partial ghi trước khi có key `translator` (schema cũ) vẫn
        được coi là khớp, không mất tiến trình dở."""
        self._write_transcript(4)
        transcript_sha256 = hashlib.sha256(self.transcript.read_bytes()).hexdigest()
        partial_path_for(self.translated).write_text(
            json.dumps(
                {
                    "transcript_sha256": transcript_sha256,
                    "source_language": "en",
                    "target_language": "vi",
                    "segments": [
                        {"id": 1, "start": 1.0, "end": 2.5, "source_text": "line 1", "translated_text": "cũ 1"},
                        {"id": 2, "start": 2.0, "end": 3.5, "source_text": "line 2", "translated_text": "cũ 2"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        translator = FakeTranslator()
        result = self._run(translator, batch_size=2)
        self.assertEqual(translator.calls[0]["ids"], [3, 4])
        self.assertEqual(result.segments[0].translated_text, "cũ 1")

    def test_transcript_hash_mismatch_retranslates_all(self) -> None:
        """C7: transcribe lại (nội dung transcript đổi) sau khi đã dịch thì
        không được lặng lẽ SKIP với bản dịch của transcript cũ."""
        self._write_transcript(3)
        self._run(FakeTranslator())

        self._write_transcript(4)  # mô phỏng transcribe --force ra nội dung khác
        translator = FakeTranslator(lambda ids, n: {i: f"mới {i}" for i in ids})
        result = self._run(translator)

        self.assertEqual(len(translator.calls), 1)
        self.assertEqual(len(result.segments), 4)
        self.assertEqual(result.segments[0].translated_text, "mới 1")
        self.assertTrue(any("transcript đã thay đổi" in line for line in self.logs))

    def test_translated_without_hash_skips(self) -> None:
        """C7: file dịch từ trước khi có transcript_sha256 vẫn SKIP như cũ,
        không có gì để so sánh."""
        self._write_transcript(2)
        self.translated.write_text(
            json.dumps(
                {
                    "source_language": "en",
                    "target_language": "vi",
                    "translator": {"provider": "fake", "model": "fake-model"},
                    "segments": [
                        {"id": 1, "start": 1.0, "end": 2.5, "source_text": "line 1", "translated_text": "cũ 1"},
                        {"id": 2, "start": 2.0, "end": 3.5, "source_text": "line 2", "translated_text": "cũ 2"},
                    ],
                }
            ),
            encoding="utf-8",
        )

        translator = FakeTranslator()
        result = self._run(translator)
        self.assertTrue(result.skipped)
        self.assertEqual(translator.calls, [])

    def test_empty_source_lines_not_sent(self) -> None:
        self._write_transcript(3, empty_ids=[2])
        translator = FakeTranslator()
        result = self._run(translator)
        self.assertEqual(translator.calls[0]["ids"], [1, 3])
        self.assertEqual(result.segments[1].translated_text, "")

    def test_missing_transcript(self) -> None:
        with self.assertRaisesRegex(TranslationError, "transcribe"):
            self._run(FakeTranslator())

    def test_duplicate_transcript_ids_rejected(self) -> None:
        self.transcript.write_text(
            json.dumps(
                {
                    "language": "en",
                    "segments": [
                        {"id": 1, "start": 0, "end": 1, "text": "a"},
                        {"id": 1, "start": 1, "end": 2, "text": "b"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(TranslationError, "trùng id"):
            self._run(FakeTranslator())


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class TestOllamaTranslator(unittest.TestCase):
    def _response(self, content: str, done_reason: str = "stop") -> _FakeResponse:
        body = {"message": {"role": "assistant", "content": content}, "done_reason": done_reason}
        return _FakeResponse(json.dumps(body).encode("utf-8"))

    def test_sends_structured_request_and_parses(self) -> None:
        translator = OllamaTranslator("qwen3:8b", host="http://h:1", num_ctx=4096)
        content = json.dumps({"translations": [{"id": 1, "text": "một"}]})
        with patch("urllib.request.urlopen", return_value=self._response(content)) as mock_open:
            result = translator.translate_batch(
                _lines(1), context=[], source_language="en", target_language="vi"
            )

        self.assertEqual(result, {1: "một"})
        request = mock_open.call_args.args[0]
        self.assertEqual(request.full_url, "http://h:1/api/chat")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "qwen3:8b")
        self.assertFalse(body["stream"])
        self.assertFalse(body["think"])
        self.assertIn("translations", body["format"]["properties"])
        self.assertEqual(body["options"]["num_ctx"], 4096)
        self.assertGreater(body["options"]["num_predict"], 0)

    def test_think_none_is_not_sent(self) -> None:
        translator = OllamaTranslator("m", think=None)
        content = json.dumps({"translations": [{"id": 1, "text": "x"}]})
        with patch("urllib.request.urlopen", return_value=self._response(content)) as mock_open:
            translator.translate_batch(_lines(1), context=[], source_language="en", target_language="vi")
        self.assertNotIn("think", json.loads(mock_open.call_args.args[0].data))

    def test_truncated_output_is_output_error(self) -> None:
        translator = OllamaTranslator("m")
        with patch("urllib.request.urlopen", return_value=self._response('{"transl', "length")):
            with self.assertRaisesRegex(TranslatorOutputError, "cắt"):
                translator.translate_batch(_lines(1), context=[], source_language="en", target_language="vi")

    def _http_error(self, code: int, message: str) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            "http://x", code, "err", {}, io.BytesIO(json.dumps({"error": message}).encode())  # type: ignore[arg-type]
        )

    def test_404_is_config_error_not_retryable(self) -> None:
        translator = OllamaTranslator("nope:1b")
        with patch("urllib.request.urlopen", side_effect=self._http_error(404, "model 'nope:1b' not found")):
            with self.assertRaises(TranslationError) as ctx:
                translator.translate_batch(_lines(1), context=[], source_language="en", target_language="vi")
        self.assertNotIsInstance(ctx.exception, (TranslatorConnectionError, TranslatorOutputError))
        self.assertIn("ollama pull nope:1b", str(ctx.exception))

    def test_500_and_connection_refused_are_retryable(self) -> None:
        translator = OllamaTranslator("m")
        for error in (self._http_error(500, "boom"), urllib.error.URLError(ConnectionRefusedError())):
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(TranslatorConnectionError):
                    translator.translate_batch(_lines(1), context=[], source_language="en", target_language="vi")

    def test_resolve_host(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(resolve_host(None), "http://localhost:11434")
        with patch.dict("os.environ", {"OLLAMA_HOST": "0.0.0.0:11434"}):
            self.assertEqual(resolve_host(None), "http://127.0.0.1:11434")
            self.assertEqual(resolve_host("http://gpu-box:11434/"), "http://gpu-box:11434")


class TestCreateTranslator(unittest.TestCase):
    def test_requires_model(self) -> None:
        with self.assertRaisesRegex(TranslationError, "translation.model"):
            create_translator(TranslationConfig(model=None))

    def test_creates_ollama(self) -> None:
        translator = create_translator(TranslationConfig(model="qwen3:8b", host="http://h:1"))
        self.assertIsInstance(translator, OllamaTranslator)
        self.assertEqual(translator.model, "qwen3:8b")


if __name__ == "__main__":
    unittest.main()

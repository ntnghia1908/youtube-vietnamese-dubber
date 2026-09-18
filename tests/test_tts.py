"""Unit test cho ``app.tts`` — Checkpoint 4.

Dùng ``FakeEngine`` (subclass ``TTSEngine`` ghi bytes giả) thay cho
edge-tts thật — test không cần mạng. ``EdgeTTSEngine`` được test riêng ở
cuối file bằng cách patch ``sys.modules["edge_tts"]``.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from app.tts.base import TTSEngine, TTSError
from app.tts.synthesize import MANIFEST_FILENAME, segment_filename, synthesize_translation


class FakeEngine(TTSEngine):
    """Engine giả: ghi ``b"AUDIO:<text>"`` thay vì gọi mạng thật.

    - ``fail_counts``: {text: N} -> N lần gọi đầu cho text đó raise lỗi rồi
      mới thành công (N >= max_attempts nghĩa là luôn luôn lỗi).
    - ``zero_byte_texts``: text nào trong đây thì luôn ghi file 0 byte
      (không raise) — mô phỏng engine "thành công" nhưng không có audio.
    """

    provider = "fake"

    def __init__(
        self,
        voice: str = "vi-VN-HoaiMyNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        *,
        fail_counts: dict[str, int] | None = None,
        zero_byte_texts: set[str] | None = None,
    ) -> None:
        super().__init__(voice, rate, volume)
        self.calls: list[str] = []
        self.fail_counts = dict(fail_counts or {})
        self.zero_byte_texts = set(zero_byte_texts or set())
        self._seen: dict[str, int] = {}

    def synthesize(self, text: str, output_path: Path) -> None:
        self.calls.append(text)
        seen = self._seen.get(text, 0)
        self._seen[text] = seen + 1
        if seen < self.fail_counts.get(text, 0):
            raise TTSError(f"lỗi giả lần {seen + 1} cho {text!r}")
        if text in self.zero_byte_texts:
            output_path.write_bytes(b"")
            return
        output_path.write_bytes(f"AUDIO:{text}".encode("utf-8"))


def _write_translated(
    path: Path,
    segments: list[tuple[int, float, float, str, str]],
    *,
    failed_ids: list[int] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_language": "en",
                "target_language": "vi",
                "translator": {"provider": "ollama", "model": "qwen3:8b"},
                "transcript_sha256": "deadbeef",
                "failed_ids": failed_ids or [],
                "segments": [
                    {"id": i, "start": s, "end": e, "source_text": src, "translated_text": tr}
                    for (i, s, e, src, tr) in segments
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _no_sleep(_seconds: float) -> None:
    pass


def _quiet(_message: str) -> None:
    # Tránh gọi print() thật: console Windows mặc định không phải UTF-8,
    # log có dấu tiếng Việt sẽ crash UnicodeEncodeError khi chạy unittest
    # trực tiếp (khác `python -m app`, nơi __main__.py đã reconfigure
    # stdout sang UTF-8). Test không cần xem log, chỉ cần không crash.
    pass


class TestSegmentFilename(unittest.TestCase):
    def test_pads_to_six_digits(self) -> None:
        self.assertEqual(segment_filename(1), "000001.mp3")
        self.assertEqual(segment_filename(123456), "123456.mp3")


class TestCacheKey(unittest.TestCase):
    def test_changes_with_any_component(self) -> None:
        base = FakeEngine("voiceA", "+0%", "+0%")
        key = base.cache_key("hello")
        self.assertNotEqual(key, FakeEngine("voiceB", "+0%", "+0%").cache_key("hello"))
        self.assertNotEqual(key, FakeEngine("voiceA", "+10%", "+0%").cache_key("hello"))
        self.assertNotEqual(key, FakeEngine("voiceA", "+0%", "+10%").cache_key("hello"))
        self.assertNotEqual(key, base.cache_key("world"))
        self.assertEqual(key, FakeEngine("voiceA", "+0%", "+0%").cache_key("hello"))

    def test_changes_with_provider(self) -> None:
        class OtherEngine(FakeEngine):
            provider = "other"

        self.assertNotEqual(
            FakeEngine("v", "+0%", "+0%").cache_key("x"),
            OtherEngine("v", "+0%", "+0%").cache_key("x"),
        )


class TestSynthesizeTranslation(unittest.TestCase):
    def _segments(self) -> list[tuple[int, float, float, str, str]]:
        return [
            (1, 0.0, 1.0, "Hello", "Xin chào"),
            (2, 1.0, 2.0, "World", "Thế giới"),
            (3, 2.0, 3.0, "Bye", "Tạm biệt"),
        ]

    def test_generates_files_for_all_nonempty_segments(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            engine = FakeEngine()

            result = synthesize_translation(
                translated, base / "tts", engine, concurrency=1, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(sorted(result.synthesized_ids), [1, 2, 3])
            self.assertEqual(result.cached_ids, [])
            self.assertEqual(result.empty_ids, [])
            self.assertEqual(result.failed_ids, [])
            self.assertFalse(result.skipped)
            for seg_id in (1, 2, 3):
                self.assertTrue((base / "tts" / segment_filename(seg_id)).exists())

            manifest = json.loads((base / "tts" / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual([s["id"] for s in manifest["segments"]], [1, 2, 3])
            self.assertTrue(all(s["status"] == "ok" for s in manifest["segments"]))

    def test_nonconsecutive_ids_get_correct_filenames(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(
                translated,
                [(5, 0.0, 1.0, "A", "Một"), (17, 1.0, 2.0, "B", "Hai")],
            )
            engine = FakeEngine()
            synthesize_translation(translated, base / "tts", engine, concurrency=1, sleep=_no_sleep, log=_quiet)

            self.assertTrue((base / "tts" / "000005.mp3").exists())
            self.assertTrue((base / "tts" / "000017.mp3").exists())

    def test_empty_translated_text_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(
                translated,
                [
                    (1, 0.0, 1.0, "Hello", "Xin chào"),
                    (2, 1.0, 2.0, "", ""),
                    (3, 2.0, 3.0, "...", "..."),
                    (4, 3.0, 4.0, "Bad", ""),
                ],
                failed_ids=[4],
            )
            engine = FakeEngine()

            result = synthesize_translation(
                translated, base / "tts", engine, concurrency=1, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(sorted(result.empty_ids), [2, 3, 4])
            self.assertEqual(result.synthesized_ids, [1])
            self.assertEqual(engine.calls, ["Xin chào"])
            for seg_id in (2, 3, 4):
                self.assertFalse((base / "tts" / segment_filename(seg_id)).exists())

    def test_second_run_skips_everything(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            engine = FakeEngine()
            synthesize_translation(translated, base / "tts", engine, concurrency=1, sleep=_no_sleep, log=_quiet)

            engine2 = FakeEngine()
            result2 = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(engine2.calls, [])
            self.assertTrue(result2.skipped)
            self.assertEqual(sorted(result2.cached_ids), [1, 2, 3])

    def test_editing_one_segment_only_resynthesizes_it(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            synthesize_translation(translated, base / "tts", FakeEngine(), concurrency=1, sleep=_no_sleep, log=_quiet)

            segs = self._segments()
            segs[1] = (2, 1.0, 2.0, "World", "Thế giới mới")
            _write_translated(translated, segs)

            engine2 = FakeEngine()
            result2 = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(engine2.calls, ["Thế giới mới"])
            self.assertEqual(result2.synthesized_ids, [2])
            self.assertEqual(sorted(result2.cached_ids), [1, 3])

    def test_changing_rate_resynthesizes_all(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            synthesize_translation(
                translated, base / "tts", FakeEngine(rate="+0%"), concurrency=1, sleep=_no_sleep, log=_quiet
            )

            engine2 = FakeEngine(rate="+20%")
            result2 = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(sorted(result2.synthesized_ids), [1, 2, 3])
            self.assertEqual(len(engine2.calls), 3)

    def test_deleted_or_zero_byte_file_is_resynthesized(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            synthesize_translation(translated, base / "tts", FakeEngine(), concurrency=1, sleep=_no_sleep, log=_quiet)

            (base / "tts" / segment_filename(1)).unlink()
            (base / "tts" / segment_filename(2)).write_bytes(b"")

            engine2 = FakeEngine()
            result2 = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(sorted(result2.synthesized_ids), [1, 2])
            self.assertEqual(result2.cached_ids, [3])

    def test_force_resynthesizes_all(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            synthesize_translation(translated, base / "tts", FakeEngine(), concurrency=1, sleep=_no_sleep, log=_quiet)

            engine2 = FakeEngine()
            result2 = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, force=True, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(sorted(result2.synthesized_ids), [1, 2, 3])
            self.assertEqual(result2.cached_ids, [])

    def test_retries_then_succeeds_with_correct_sleep_delays(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, [(1, 0.0, 1.0, "Hi", "Chào")])
            engine = FakeEngine(fail_counts={"Chào": 2})
            delays: list[float] = []

            result = synthesize_translation(
                translated, base / "tts", engine, concurrency=1, sleep=delays.append, log=_quiet
            )

            self.assertEqual(result.synthesized_ids, [1])
            self.assertEqual(delays, [2.0, 5.0])
            self.assertEqual(len(engine.calls), 3)

    def test_non_first_segment_fails_completely_does_not_stop_stage(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            engine = FakeEngine(fail_counts={"Thế giới": 99})

            result = synthesize_translation(
                translated, base / "tts", engine, concurrency=1, max_attempts=3, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(result.failed_ids, [2])
            self.assertEqual(sorted(result.synthesized_ids), [1, 3])
            self.assertFalse((base / "tts" / segment_filename(2)).exists())

            # Chạy lại: chỉ segment lỗi được gọi lại (id 1, 3 vẫn cache hợp lệ).
            engine2 = FakeEngine()
            result2 = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, sleep=_no_sleep, log=_quiet
            )
            self.assertEqual(engine2.calls, ["Thế giới"])
            self.assertEqual(result2.synthesized_ids, [2])
            self.assertEqual(sorted(result2.cached_ids), [1, 3])

    def test_first_segment_fails_completely_raises_and_stops(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            engine = FakeEngine(fail_counts={"Xin chào": 99})

            with self.assertRaises(TTSError):
                synthesize_translation(
                    translated, base / "tts", engine, concurrency=1, max_attempts=3, sleep=_no_sleep, log=_quiet
                )

            self.assertEqual(set(engine.calls), {"Xin chào"})

    def test_first_pending_fails_but_has_cache_does_not_raise(self) -> None:
        """Resume: có cache hợp lệ từ trước (bằng chứng voice/mạng ổn) thì
        segment lỗi hết lượt dù là segment cần đọc đầu tiên cũng chỉ bị
        đánh dấu failed, không raise chặn cả episode (khác lần chạy đầu
        tiên của episode, khi chưa có bằng chứng nào)."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            synthesize_translation(
                translated, base / "tts", FakeEngine(), concurrency=1, sleep=_no_sleep, log=_quiet
            )

            # Sửa id 1 để nó cần tổng hợp lại (là segment "đầu tiên" của
            # pending), luôn lỗi; id 2, 3 vẫn còn cache hợp lệ từ lần trước.
            segs = self._segments()
            segs[0] = (1, 0.0, 1.0, "Hello", "Xin chào mới")
            _write_translated(translated, segs)
            engine2 = FakeEngine(fail_counts={"Xin chào mới": 99})

            result = synthesize_translation(
                translated, base / "tts", engine2, concurrency=1, max_attempts=3, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(result.failed_ids, [1])
            self.assertEqual(sorted(result.cached_ids), [2, 3])
            self.assertEqual(result.synthesized_ids, [])

    def test_zero_byte_output_is_retried_then_failed_without_leftovers(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, [(1, 0.0, 1.0, "Hi", "Chào")])
            engine = FakeEngine(zero_byte_texts={"Chào"})

            with self.assertRaises(TTSError):
                synthesize_translation(
                    translated, base / "tts", engine, concurrency=1, max_attempts=2, sleep=_no_sleep, log=_quiet
                )

            tts_dir = base / "tts"
            leftovers = list(tts_dir.glob("*.mp3")) + list(tts_dir.glob("*.tmp"))
            self.assertEqual(leftovers, [])

    def test_stale_tmp_and_orphan_files_are_cleaned(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            _write_translated(translated, self._segments())
            tts_dir = base / "tts"
            tts_dir.mkdir(parents=True)
            (tts_dir / "999999.mp3.tmp").write_bytes(b"leftover")
            (tts_dir / "000099.mp3").write_bytes(b"orphan")
            (tts_dir / "notes.txt").write_text("giữ nguyên", encoding="utf-8")

            synthesize_translation(translated, tts_dir, FakeEngine(), concurrency=1, sleep=_no_sleep, log=_quiet)

            self.assertFalse((tts_dir / "999999.mp3.tmp").exists())
            self.assertFalse((tts_dir / "000099.mp3").exists())
            self.assertTrue((tts_dir / "notes.txt").exists())

    def test_missing_translated_json_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.assertRaises(TTSError):
                synthesize_translation(
                    base / "translated.json", base / "tts", FakeEngine(), sleep=_no_sleep, log=_quiet
                )

    def test_corrupt_translated_json_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            translated.write_text("{not json", encoding="utf-8")
            with self.assertRaises(TTSError):
                synthesize_translation(translated, base / "tts", FakeEngine(), sleep=_no_sleep, log=_quiet)

    def test_concurrency_generates_all_files_in_order(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            translated = base / "translated.json"
            segments = [(i, float(i), float(i + 1), f"src{i}", f"dịch{i}") for i in range(1, 11)]
            _write_translated(translated, segments)
            engine = FakeEngine()

            result = synthesize_translation(
                translated, base / "tts", engine, concurrency=4, sleep=_no_sleep, log=_quiet
            )

            self.assertEqual(sorted(result.synthesized_ids), list(range(1, 11)))
            for i in range(1, 11):
                self.assertTrue((base / "tts" / segment_filename(i)).exists())
            manifest = json.loads((base / "tts" / MANIFEST_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual([s["id"] for s in manifest["segments"]], list(range(1, 11)))


class TestEdgeTTSEngine(unittest.TestCase):
    def test_passes_voice_rate_volume_and_path(self) -> None:
        from app.tts.edge import EdgeTTSEngine

        fake_module = MagicMock()
        communicate_instance = MagicMock()
        communicate_instance.save = AsyncMock(return_value=None)
        fake_module.Communicate = MagicMock(return_value=communicate_instance)

        with TemporaryDirectory() as tmp, patch.dict(sys.modules, {"edge_tts": fake_module}):
            output_path = Path(tmp) / "out.mp3"
            engine = EdgeTTSEngine("vi-VN-HoaiMyNeural", "+10%", "-5%", timeout_seconds=30)
            engine.synthesize("Xin chào", output_path)

        fake_module.Communicate.assert_called_once_with(
            "Xin chào", "vi-VN-HoaiMyNeural", rate="+10%", volume="-5%", receive_timeout=30
        )
        communicate_instance.save.assert_awaited_once_with(str(output_path))

    def test_save_error_wrapped_as_tts_error(self) -> None:
        from app.tts.edge import EdgeTTSEngine

        fake_module = MagicMock()
        communicate_instance = MagicMock()
        communicate_instance.save = AsyncMock(side_effect=RuntimeError("NoAudioReceived"))
        fake_module.Communicate = MagicMock(return_value=communicate_instance)

        with TemporaryDirectory() as tmp, patch.dict(sys.modules, {"edge_tts": fake_module}):
            output_path = Path(tmp) / "out.mp3"
            engine = EdgeTTSEngine("v", "+0%", "+0%", timeout_seconds=30)
            with self.assertRaises(TTSError):
                engine.synthesize("...", output_path)


if __name__ == "__main__":
    unittest.main()

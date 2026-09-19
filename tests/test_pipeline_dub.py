"""Test cho ``app.pipeline.dub`` (Checkpoint 7) — điều phối end-to-end ``dub``.

Patch mọi hàm stage ở ĐÚNG chỗ ``app.pipeline.dub`` import chúng (không phải
module gốc) — ``dub.py`` import ở cấp module nên patch ở module gốc sẽ
không có tác dụng. Kết quả giả dựng bằng dataclass thật (không phải
SimpleNamespace) để khớp đúng field mà ``run_dub`` đọc.

Đây chỉ là unit test (mock hoá toàn bộ I/O thật) — theo CLAUDE.md, checkpoint
chỉ coi là xong sau khi chạy thật với video thật và đọc artifact sinh ra.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.audio.ffmpeg import AudioExtractionError
from app.audio.render import RenderError, RenderResult
from app.config import AppConfig, TranslationConfig
from app.synchronization.timing import TimingError, TimingResult
from app.transcription.whisper import Segment, TranscriptionError, TranscriptResult
from app.translation.glossary import GlossaryError
from app.translation.base import TranslationError
from app.translation.translate import TranslatedSegment, TranslationResult
from app.tts.base import TTSError
from app.tts.synthesize import TTSResult
from app.youtube.download import EpisodeInfo, VideoDownloadError

from app.pipeline.dub import DubError, DubOptions, run_dub


def _episode_info(episode_dir: Path) -> EpisodeInfo:
    return EpisodeInfo(
        video_id="vid001",
        title="Video Demo",
        source_url="https://youtu.be/vid001",
        episode_dir=episode_dir,
        metadata_path=episode_dir / "metadata.json",
        source_path=episode_dir / "source.mp4",
    )


def _transcript_result(language: str = "en") -> TranscriptResult:
    segments = [
        Segment(id=1, start=0.0, end=1.0, text="Hi"),
        Segment(id=2, start=1.0, end=2.0, text="Bye"),
    ]
    return TranscriptResult(language=language, segments=segments, transcript_path=Path("transcript.json"))


def _translation_result(failed_ids: list[int] | None = None, skipped: bool = False) -> TranslationResult:
    return TranslationResult(
        translated_path=Path("translated.json"),
        source_language="en",
        target_language="vi",
        segments=[
            TranslatedSegment(1, 0.0, 1.0, "Hi", "Chào"),
            TranslatedSegment(2, 1.0, 2.0, "Bye", "Tạm biệt"),
        ],
        skipped=skipped,
        failed_ids=failed_ids or [],
    )


def _tts_result(skipped: bool = False) -> TTSResult:
    return TTSResult(
        manifest_path=Path("tts/manifest.json"),
        synthesized_ids=[1, 2],
        cached_ids=[],
        empty_ids=[],
        failed_ids=[],
        skipped=skipped,
    )


def _timing_result(
    missing_ids: list[int] | None = None,
    too_long_ids: list[int] | None = None,
    skipped: bool = False,
) -> TimingResult:
    return TimingResult(
        normalized_path=Path("normalized.json"),
        normal_ids=[1, 2],
        stretched_ids=[],
        too_long_ids=too_long_ids or [],
        silent_ids=[],
        missing_ids=missing_ids or [],
        skipped=skipped,
    )


def _render_result(
    missing_ids: list[int] | None = None,
    voice_track_skipped: bool = False,
    output_skipped: bool = False,
) -> RenderResult:
    return RenderResult(
        voice_track_path=Path("voice_track.wav"),
        output_path=Path("output_vi.mp4"),
        render_path=Path("render.json"),
        placed_ids=[1, 2],
        silent_ids=[],
        missing_ids=missing_ids or [],
        shifted_ids=[],
        overlap_ids=[],
        max_shift_seen=0.0,
        duration=10.0,
        voice_track_skipped=voice_track_skipped,
        output_skipped=output_skipped,
    )


class DubPipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "workspace"
        self.workspace.mkdir()
        self.episode_dir = self.workspace / "vid001__Video Demo"
        self.episode_dir.mkdir()
        self.config = AppConfig(
            target_language="vi",
            translation=TranslationConfig(model="test-model"),
        )
        self.options = DubOptions(workspace=self.workspace)
        self.log_lines: list[str] = []

    def _log(self, message: str) -> None:
        self.log_lines.append(message)

    def _patch_all(self, **overrides: MagicMock) -> dict[str, MagicMock]:
        mocks: dict[str, MagicMock] = {
            "download_video": MagicMock(return_value=_episode_info(self.episode_dir)),
            "extract_audio": MagicMock(return_value=self.episode_dir / "audio.wav"),
            "transcribe_audio": MagicMock(return_value=_transcript_result()),
            "create_translator": MagicMock(
                return_value=SimpleNamespace(provider="fake", model="test-model")
            ),
            "load_effective_glossary": MagicMock(return_value=(None, [])),
            "translate_transcript": MagicMock(return_value=_translation_result()),
            "create_tts_engine": MagicMock(
                return_value=SimpleNamespace(provider="edge", voice="v", rate="+0%", volume="+0%")
            ),
            "synthesize_translation": MagicMock(return_value=_tts_result()),
            "normalize_timing": MagicMock(return_value=_timing_result()),
            "render_episode": MagicMock(return_value=_render_result()),
        }
        mocks.update(overrides)
        for name, mock in mocks.items():
            patcher = patch(f"app.pipeline.dub.{name}", mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        return mocks

    def _run(self, options: DubOptions | None = None):
        return run_dub(
            "https://youtu.be/vid001", self.config, options or self.options, log=self._log
        )


class TestHappyPath(DubPipelineTestCase):
    """Test 1: đường thẳng đủ 6 stage, tham số lấy từ config đúng chỗ."""

    def test_calls_all_six_stages_with_config_params(self) -> None:
        from dataclasses import replace

        base = self
        base.config = replace(
            base.config,
            translation=TranslationConfig(model="m", batch_size=7, context_size=2, max_attempts=4),
            tts=replace(base.config.tts, concurrency=9),
            timing=replace(base.config.timing, max_tempo=1.4),
            mixing=replace(base.config.mixing, speech_volume=0.8, max_shift_seconds=2.0),
        )
        base.options = DubOptions(workspace=base.workspace, original_volume=0.6)

        mocks = base._patch_all()
        result = base._run()

        mocks["download_video"].assert_called_once_with(
            "https://youtu.be/vid001", base.workspace, force=False
        )
        mocks["translate_transcript"].assert_called_once()
        self.assertEqual(mocks["translate_transcript"].call_args.kwargs["batch_size"], 7)
        self.assertEqual(mocks["translate_transcript"].call_args.kwargs["context_size"], 2)
        self.assertEqual(mocks["translate_transcript"].call_args.kwargs["max_attempts"], 4)
        self.assertEqual(mocks["translate_transcript"].call_args.kwargs["target_language"], "vi")

        mocks["synthesize_translation"].assert_called_once()
        self.assertEqual(mocks["synthesize_translation"].call_args.kwargs["concurrency"], 9)

        mocks["normalize_timing"].assert_called_once()
        self.assertEqual(mocks["normalize_timing"].call_args.kwargs["max_tempo"], 1.4)

        mocks["render_episode"].assert_called_once()
        render_kwargs = mocks["render_episode"].call_args.kwargs
        self.assertEqual(render_kwargs["original_volume"], 0.6)
        self.assertEqual(render_kwargs["speech_volume"], 0.8)
        self.assertEqual(render_kwargs["max_shift"], 2.0)

        self.assertEqual(result.output_path, Path("output_vi.mp4"))
        self.assertEqual(result.segments, 2)
        self.assertEqual(result.source_language, "en")


class TestForceFlag(DubPipelineTestCase):
    """Test 2: force=True chỉ áp cho lần gọi đầu, vòng sửa luôn force=False."""

    def test_force_only_applies_to_first_call_of_each_stage(self) -> None:
        self.options = DubOptions(workspace=self.workspace, force=True)
        mocks = self._patch_all(
            translate_transcript=MagicMock(
                side_effect=[_translation_result(failed_ids=[5]), _translation_result()]
            ),
            synthesize_translation=MagicMock(side_effect=[_tts_result(), _tts_result()]),
            normalize_timing=MagicMock(
                side_effect=[_timing_result(missing_ids=[3]), _timing_result()]
            ),
        )
        self._run()

        translate_calls = mocks["translate_transcript"].call_args_list
        self.assertTrue(translate_calls[0].kwargs["force"])
        self.assertFalse(translate_calls[1].kwargs["force"])

        tts_calls = mocks["synthesize_translation"].call_args_list
        self.assertTrue(tts_calls[0].kwargs["force"])
        self.assertFalse(tts_calls[1].kwargs["force"])

        normalize_calls = mocks["normalize_timing"].call_args_list
        self.assertTrue(normalize_calls[0].kwargs["force"])
        self.assertFalse(normalize_calls[1].kwargs["force"])

        self.assertTrue(mocks["download_video"].call_args.kwargs["force"])
        self.assertTrue(mocks["render_episode"].call_args.kwargs["force"])


class TestLanguageMismatch(DubPipelineTestCase):
    """Test 3 + 4: bẫy auto-detect zh -> en (xem CLAUDE.md)."""

    def test_source_lang_mismatch_raises_dub_error_before_translate(self) -> None:
        self.options = DubOptions(workspace=self.workspace, source_lang="zh")
        mocks = self._patch_all(transcribe_audio=MagicMock(return_value=_transcript_result("en")))

        with self.assertRaises(DubError) as ctx:
            self._run()

        self.assertEqual(ctx.exception.stage, "transcribe")
        self.assertIn("--source-lang zh --force", str(ctx.exception))
        self.assertIn("en", str(ctx.exception))
        mocks["translate_transcript"].assert_not_called()

    def test_auto_detect_logs_warning_but_continues(self) -> None:
        self.options = DubOptions(workspace=self.workspace, source_lang=None)
        self._patch_all(transcribe_audio=MagicMock(return_value=_transcript_result("zh")))

        result = self._run()

        self.assertTrue(any("LƯU Ý" in line for line in self.log_lines))
        self.assertEqual(result.source_language, "zh")


class TestMissingTranslationModel(DubPipelineTestCase):
    """Test 5: thiếu translation.model báo lỗi ngay, không chạm mạng."""

    def test_missing_model_fails_fast_before_download(self) -> None:
        self.config = AppConfig(target_language="vi", translation=TranslationConfig(model=None))
        mocks = self._patch_all()

        with self.assertRaises(DubError) as ctx:
            self._run()

        self.assertEqual(ctx.exception.stage, "translate")
        mocks["download_video"].assert_not_called()


class TestGlossary(DubPipelineTestCase):
    """Test 6: nhắc tạo glossary khi chưa có, truyền đúng object khi có, lỗi glossary -> DubError."""

    def test_missing_glossary_file_logs_reminder(self) -> None:
        self._patch_all(load_effective_glossary=MagicMock(return_value=(None, [])))
        self._run()

        self.assertTrue(any("python -m app glossary" in line for line in self.log_lines))
        self.assertFalse(any(line.startswith("[dub] glossary :") for line in self.log_lines))

    def test_existing_glossary_is_passed_to_translate(self) -> None:
        fake_glossary = object()
        glossary_path = self.episode_dir / "glossary.yaml"
        glossary_path.write_text("terms: {}\n", encoding="utf-8")
        mocks = self._patch_all(
            load_effective_glossary=MagicMock(return_value=(fake_glossary, [glossary_path]))
        )
        self._run()

        self.assertIs(mocks["translate_transcript"].call_args.kwargs["glossary"], fake_glossary)
        self.assertTrue(any("[dub] glossary : " in line for line in self.log_lines))
        self.assertFalse(any("python -m app glossary" in line for line in self.log_lines))

    def test_glossary_error_becomes_dub_error_on_translate_stage(self) -> None:
        mocks = self._patch_all(
            load_effective_glossary=MagicMock(
                side_effect=GlossaryError("glossary hỏng")
            )
        )
        with self.assertRaises(DubError) as ctx:
            self._run()

        self.assertEqual(ctx.exception.stage, "translate")
        mocks["translate_transcript"].assert_not_called()


class TestTranslateRepair(DubPipelineTestCase):
    """Test 7 + 8: retry translate tối đa repair_rounds lần."""

    def test_retries_until_failed_ids_empty(self) -> None:
        mocks = self._patch_all(
            translate_transcript=MagicMock(
                side_effect=[_translation_result(failed_ids=[5]), _translation_result(failed_ids=[])]
            )
        )
        result = self._run()

        self.assertEqual(mocks["translate_transcript"].call_count, 2)
        self.assertEqual(result.repair_rounds_used, 1)
        self.assertEqual(result.translate_failed_ids, [])

    def test_gives_up_after_repair_rounds_but_still_renders(self) -> None:
        mocks = self._patch_all(
            translate_transcript=MagicMock(return_value=_translation_result(failed_ids=[5]))
        )
        result = self._run()

        self.assertEqual(mocks["translate_transcript"].call_count, 3)  # 1 + repair_rounds mặc định (2)
        self.assertEqual(result.translate_failed_ids, [5])
        mocks["render_episode"].assert_called_once()


class TestMissingAudioRepair(DubPipelineTestCase):
    """Test 9-12: vòng sửa thiếu audio (tts + normalize)."""

    def test_retries_until_missing_empty(self) -> None:
        mocks = self._patch_all(
            normalize_timing=MagicMock(
                side_effect=[_timing_result(missing_ids=[3]), _timing_result(missing_ids=[])]
            )
        )
        self._run()

        self.assertEqual(mocks["synthesize_translation"].call_count, 2)
        self.assertEqual(mocks["normalize_timing"].call_count, 2)
        self.assertFalse(mocks["render_episode"].call_args.kwargs["allow_missing"])

    def test_gives_up_after_repair_rounds_blocks_render(self) -> None:
        mocks = self._patch_all(
            normalize_timing=MagicMock(return_value=_timing_result(missing_ids=[3]))
        )
        with self.assertRaises(DubError) as ctx:
            self._run()

        self.assertEqual(ctx.exception.stage, "render")
        self.assertIn("--allow-missing", str(ctx.exception))
        self.assertEqual(mocks["synthesize_translation"].call_count, 3)
        self.assertEqual(mocks["normalize_timing"].call_count, 3)
        mocks["render_episode"].assert_not_called()

    def test_allow_missing_renders_with_missing_ids_from_render_result(self) -> None:
        self.options = DubOptions(workspace=self.workspace, allow_missing=True)
        mocks = self._patch_all(
            normalize_timing=MagicMock(return_value=_timing_result(missing_ids=[3])),
            render_episode=MagicMock(return_value=_render_result(missing_ids=[3])),
        )
        result = self._run()

        self.assertTrue(mocks["render_episode"].call_args.kwargs["allow_missing"])
        self.assertEqual(result.missing_ids, [3])

    def test_repair_rounds_zero_does_not_retry_tts(self) -> None:
        from dataclasses import replace

        self.config = replace(self.config, pipeline=replace(self.config.pipeline, repair_rounds=0))
        mocks = self._patch_all(
            normalize_timing=MagicMock(return_value=_timing_result(missing_ids=[3]))
        )
        with self.assertRaises(DubError):
            self._run()

        mocks["synthesize_translation"].assert_called_once()


class TestStageErrors(DubPipelineTestCase):
    """Test 13: mỗi loại lỗi stage -> DubError với .stage đúng, dừng ngay."""

    def test_download_error(self) -> None:
        mocks = self._patch_all(
            download_video=MagicMock(side_effect=VideoDownloadError("boom"))
        )
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "download")
        mocks["transcribe_audio"].assert_not_called()

    def test_audio_extraction_error(self) -> None:
        mocks = self._patch_all(extract_audio=MagicMock(side_effect=AudioExtractionError("boom")))
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "transcribe")
        mocks["translate_transcript"].assert_not_called()

    def test_transcription_error(self) -> None:
        mocks = self._patch_all(transcribe_audio=MagicMock(side_effect=TranscriptionError("boom")))
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "transcribe")
        mocks["translate_transcript"].assert_not_called()

    def test_translation_error(self) -> None:
        mocks = self._patch_all(translate_transcript=MagicMock(side_effect=TranslationError("boom")))
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "translate")
        mocks["synthesize_translation"].assert_not_called()

    def test_tts_error(self) -> None:
        mocks = self._patch_all(synthesize_translation=MagicMock(side_effect=TTSError("boom")))
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "tts")
        mocks["normalize_timing"].assert_not_called()

    def test_timing_error(self) -> None:
        mocks = self._patch_all(normalize_timing=MagicMock(side_effect=TimingError("boom")))
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "normalize")
        mocks["render_episode"].assert_not_called()

    def test_render_error(self) -> None:
        self._patch_all(render_episode=MagicMock(side_effect=RenderError("boom")))
        with self.assertRaises(DubError) as ctx:
            self._run()
        self.assertEqual(ctx.exception.stage, "render")


class TestSkippedStages(DubPipelineTestCase):
    """Test 14: mọi stage đã có artifact -> đủ 6 tên trong skipped_stages."""

    def test_all_six_stages_reported_as_skipped(self) -> None:
        (self.episode_dir / "source.mp4").write_bytes(b"fake")
        (self.episode_dir / "transcript.json").write_text("{}", encoding="utf-8")

        self._patch_all(
            translate_transcript=MagicMock(return_value=_translation_result(skipped=True)),
            synthesize_translation=MagicMock(return_value=_tts_result(skipped=True)),
            normalize_timing=MagicMock(return_value=_timing_result(skipped=True)),
            render_episode=MagicMock(
                return_value=_render_result(voice_track_skipped=True, output_skipped=True)
            ),
        )
        result = self._run()

        self.assertEqual(set(result.skipped_stages), {
            "download", "transcribe", "translate", "tts", "normalize", "render"
        })
        self.assertEqual(result.repair_rounds_used, 0)


if __name__ == "__main__":
    unittest.main()

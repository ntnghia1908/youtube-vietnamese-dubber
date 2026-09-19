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
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import cli
from app.audio.ffmpeg import AudioExtractionError
from app.audio.render import RenderError, RenderResult
from app.pipeline.dub import DubError, DubResult
from app.pipeline.playlist import EpisodeOutcome, PlaylistResult
from app.transcription.whisper import Segment, TranscriptionError, TranscriptResult
from app.translation.glossary import GlossaryError, parse_glossary
from app.translation.glossary_draft import GlossaryDraftResult
from app.translation.translate import TranslatedSegment, TranslationResult
from app.synchronization.timing import TimingError, TimingResult
from app.tts.synthesize import TTSResult
from app.youtube.download import EpisodeInfo, VideoDownloadError

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCliHelp(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # CP4: encoding="utf-8" ép rõ — subprocess con in UTF-8 (help text có
        # tiếng Việt), nhưng mặc định `text=True` decode theo locale của máy
        # (cp1252 trên Windows) nên ngẫu nhiên vỡ UnicodeDecodeError tuỳ nội
        # dung help text dài ngắn thế nào (thêm subcommand `tts` là lộ ra).
        return subprocess.run(
            [sys.executable, "-m", "app", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
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


class TestTranscribeSubcommand(unittest.TestCase):
    def test_transcribe_success_prints_summary(self) -> None:
        fake_result = TranscriptResult(
            language="en",
            segments=[Segment(id=1, start=0.0, end=1.0, text="Hi")],
            transcript_path=Path("output/ep/transcript.json"),
        )
        with (
            patch("app.audio.ffmpeg.extract_audio", return_value=Path("output/ep/audio.wav")),
            patch("app.transcription.whisper.transcribe_audio", return_value=fake_result),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["transcribe", "output/ep"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("en", output)
        self.assertIn("transcript.json", output)

    def test_transcribe_audio_extraction_failure(self) -> None:
        with (
            patch(
                "app.audio.ffmpeg.extract_audio",
                side_effect=AudioExtractionError("Không tìm thấy ffmpeg"),
            ),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["transcribe", "output/ep"])

        self.assertEqual(exit_code, 1)
        self.assertIn("ffmpeg", fake_stderr.getvalue())

    def test_transcribe_whisper_failure(self) -> None:
        with (
            patch("app.audio.ffmpeg.extract_audio", return_value=Path("output/ep/audio.wav")),
            patch(
                "app.transcription.whisper.transcribe_audio",
                side_effect=TranscriptionError("model load failed"),
            ),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["transcribe", "output/ep"])

        self.assertEqual(exit_code, 1)
        self.assertIn("model load failed", fake_stderr.getvalue())

    def test_transcribe_uses_whisper_model_from_config(self) -> None:
        fake_result = TranscriptResult(language="en", segments=[], transcript_path=Path("t.json"))
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text("whisper:\n  model: small\n", encoding="utf-8")
            with (
                patch("app.audio.ffmpeg.extract_audio"),
                patch(
                    "app.transcription.whisper.transcribe_audio", return_value=fake_result
                ) as mock_transcribe,
                patch("sys.stdout", new_callable=StringIO),
            ):
                cli.main(["transcribe", "output/ep", "--config", str(config_path)])
                self.assertEqual(mock_transcribe.call_args.kwargs["model_size"], "small")

                # Flag CLI ghi đè config.
                cli.main(
                    ["transcribe", "output/ep", "--config", str(config_path), "--whisper-model", "tiny"]
                )
                self.assertEqual(mock_transcribe.call_args.kwargs["model_size"], "tiny")


class TestTranslateSubcommand(unittest.TestCase):
    def _result(self, skipped: bool = False, failed_ids: list[int] | None = None) -> TranslationResult:
        return TranslationResult(
            translated_path=Path("output/ep/translated.json"),
            source_language="en",
            target_language="vi",
            segments=[TranslatedSegment(1, 0.0, 1.0, "Hi", "Chào")],
            skipped=skipped,
            failed_ids=failed_ids or [],
        )

    def test_translate_uses_cli_model_over_config(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text(
                "translation:\n  model: from-config\n  batch_size: 20\n", encoding="utf-8"
            )
            with (
                patch(
                    "app.translation.translate.translate_transcript", return_value=self._result()
                ) as mock_translate,
                patch("sys.stdout", new_callable=StringIO) as fake_stdout,
            ):
                exit_code = cli.main(
                    ["translate", "output/ep", "--config", str(config_path), "--model", "from-cli"]
                )

        self.assertEqual(exit_code, 0)
        translator = mock_translate.call_args.args[2]
        self.assertEqual(translator.model, "from-cli")
        self.assertEqual(mock_translate.call_args.kwargs["batch_size"], 20)
        self.assertEqual(mock_translate.call_args.kwargs["target_language"], "vi")
        self.assertIn("en -> vi", fake_stdout.getvalue())

    def test_translate_without_model_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text("translation:\n  batch_size: 20\n", encoding="utf-8")
            with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
                exit_code = cli.main(["translate", "output/ep", "--config", str(config_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("--model", fake_stderr.getvalue())

    def test_translate_skip_message(self) -> None:
        with (
            patch("app.translation.translate.translate_transcript", return_value=self._result(True)),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["translate", "output/ep", "--model", "m"])

        self.assertEqual(exit_code, 0)
        self.assertIn("SKIP", fake_stdout.getvalue())

    def test_translate_warns_on_failed_ids_but_exits_zero(self) -> None:
        """C3: một câu khó không được chặn cả playlist -> exit code vẫn 0,
        chỉ in cảnh báo để người dùng biết chạy lại lệnh."""
        with (
            patch(
                "app.translation.translate.translate_transcript",
                return_value=self._result(failed_ids=[3, 4]),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["translate", "output/ep", "--model", "m"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO", output)
        self.assertIn("3, 4", output)

    def test_invalid_config_file_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text("translation:\n  batchsize: 20\n", encoding="utf-8")
            with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
                exit_code = cli.main(["translate", "output/ep", "--config", str(config_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("batchsize", fake_stderr.getvalue())


class TestTTSSubcommand(unittest.TestCase):
    def _result(self, skipped: bool = False, failed_ids: list[int] | None = None) -> TTSResult:
        return TTSResult(
            manifest_path=Path("output/ep/tts/manifest.json"),
            synthesized_ids=[1],
            cached_ids=[],
            empty_ids=[],
            failed_ids=failed_ids or [],
            skipped=skipped,
        )

    def test_tts_uses_config_and_cli_overrides(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text(
                "tts:\n  voice: from-config\n  concurrency: 2\n", encoding="utf-8"
            )
            with (
                patch(
                    "app.tts.synthesize.synthesize_translation", return_value=self._result()
                ) as mock_synth,
                patch("app.tts.create_tts_engine") as mock_create_engine,
                patch("sys.stdout", new_callable=StringIO),
            ):
                exit_code = cli.main(
                    ["tts", "output/ep", "--config", str(config_path), "--voice", "from-cli"]
                )

        self.assertEqual(exit_code, 0)
        tconfig_used = mock_create_engine.call_args.args[0]
        self.assertEqual(tconfig_used.voice, "from-cli")
        self.assertEqual(tconfig_used.concurrency, 2)
        self.assertEqual(mock_synth.call_args.kwargs["concurrency"], 2)

    def test_tts_skip_message(self) -> None:
        with (
            patch("app.tts.synthesize.synthesize_translation", return_value=self._result(True)),
            patch("app.tts.create_tts_engine"),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["tts", "output/ep"])

        self.assertEqual(exit_code, 0)
        self.assertIn("SKIP", fake_stdout.getvalue())

    def test_tts_invalid_rate_errors(self) -> None:
        with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
            exit_code = cli.main(["tts", "output/ep", "--rate=bad"])

        self.assertEqual(exit_code, 1)
        self.assertIn("rate", fake_stderr.getvalue())

    def test_tts_warns_on_failed_ids_but_exits_zero(self) -> None:
        with (
            patch(
                "app.tts.synthesize.synthesize_translation",
                return_value=self._result(failed_ids=[7]),
            ),
            patch("app.tts.create_tts_engine"),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["tts", "output/ep"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO", output)
        self.assertIn("7", output)


class TestNormalizeSubcommand(unittest.TestCase):
    def _result(self, skipped: bool = False, missing_ids: list[int] | None = None) -> TimingResult:
        return TimingResult(
            normalized_path=Path("output/ep/normalized.json"),
            normal_ids=[1],
            stretched_ids=[],
            too_long_ids=[],
            silent_ids=[],
            missing_ids=missing_ids or [],
            skipped=skipped,
        )

    def test_normalize_help_runs(self) -> None:
        result = self._run_help_subprocess("normalize", "--help")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("normalize", result.stdout.lower())

    def _run_help_subprocess(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "app", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_normalize_prints_report(self) -> None:
        with (
            patch(
                "app.synchronization.timing.normalize_timing",
                return_value=self._result(),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["normalize", "output/ep"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("[normalize] normal    : 1", output)
        self.assertIn("normalized.json", output)

    def test_normalize_skip_message(self) -> None:
        with (
            patch(
                "app.synchronization.timing.normalize_timing",
                return_value=self._result(skipped=True),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["normalize", "output/ep"])

        self.assertEqual(exit_code, 0)
        self.assertIn("SKIP", fake_stdout.getvalue())

    def test_normalize_warns_on_missing_ids_but_exits_zero(self) -> None:
        with (
            patch(
                "app.synchronization.timing.normalize_timing",
                return_value=self._result(missing_ids=[5, 6]),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["normalize", "output/ep"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO", output)
        self.assertIn("5, 6", output)

    def test_normalize_invalid_max_tempo_errors(self) -> None:
        with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
            exit_code = cli.main(["normalize", "output/ep", "--max-tempo", "3"])

        self.assertEqual(exit_code, 1)
        self.assertIn("max_tempo", fake_stderr.getvalue())

    def test_normalize_missing_manifest_errors(self) -> None:
        with (
            patch(
                "app.synchronization.timing.normalize_timing",
                side_effect=TimingError("Không tìm thấy tts/manifest.json. Chạy `tts` trước."),
            ),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["normalize", "output/ep"])

        self.assertEqual(exit_code, 1)
        self.assertIn("manifest.json", fake_stderr.getvalue())


class TestRenderSubcommand(unittest.TestCase):
    def _result(
        self,
        *,
        missing_ids: list[int] | None = None,
        shifted_ids: list[int] | None = None,
        overlap_ids: list[int] | None = None,
    ) -> RenderResult:
        return RenderResult(
            voice_track_path=Path("output/ep/voice_track.wav"),
            output_path=Path("output/ep/output_vi.mp4"),
            render_path=Path("output/ep/render.json"),
            placed_ids=[1, 2, 3],
            silent_ids=[4],
            missing_ids=missing_ids or [],
            shifted_ids=shifted_ids or [],
            overlap_ids=overlap_ids or [],
            max_shift_seen=0.51 if shifted_ids else 0.0,
            duration=12.0,
            voice_track_skipped=False,
            output_skipped=False,
        )

    def test_render_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app", "render", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--original-volume", result.stdout)
        self.assertIn("--allow-missing", result.stdout)

    def test_render_prints_report(self) -> None:
        with (
            patch(
                "app.audio.render.render_episode",
                return_value=self._result(shifted_ids=[9, 19], overlap_ids=[9]),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["render", "output/ep"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("[render] segments     : 4", output)
        self.assertIn("[render] placed       : 3", output)
        self.assertIn("[render] silent       : 1", output)
        self.assertIn("[render] missing      : 0", output)
        self.assertIn("[render] shifted      : 2 (tối đa 0.51s)", output)
        self.assertIn("[render] overlap      : 1 (id 9)", output)
        self.assertIn("voice_track.wav", output)
        self.assertIn("output_vi.mp4", output)
        self.assertNotIn("CẢNH BÁO", output)

    def test_render_warns_when_missing_ids_allowed(self) -> None:
        with (
            patch(
                "app.audio.render.render_episode",
                return_value=self._result(missing_ids=[5, 6]),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["render", "output/ep", "--allow-missing"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO", output)
        self.assertIn("5, 6", output)

    def test_render_passes_flags_to_render_episode(self) -> None:
        with (
            patch(
                "app.audio.render.render_episode", return_value=self._result()
            ) as fake_render,
            patch("sys.stdout", new_callable=StringIO),
        ):
            exit_code = cli.main(
                [
                    "render", "output/ep",
                    "--original-volume", "0.5",
                    "--max-shift", "0",
                    "--allow-missing",
                    "--force",
                ]
            )

        self.assertEqual(exit_code, 0)
        kwargs = fake_render.call_args.kwargs
        self.assertEqual(kwargs["original_volume"], 0.5)
        self.assertEqual(kwargs["max_shift"], 0.0)
        self.assertTrue(kwargs["allow_missing"])
        self.assertTrue(kwargs["force"])

    def test_render_defaults_do_not_allow_missing_or_force(self) -> None:
        with (
            patch(
                "app.audio.render.render_episode", return_value=self._result()
            ) as fake_render,
            patch("sys.stdout", new_callable=StringIO),
        ):
            cli.main(["render", "output/ep"])

        kwargs = fake_render.call_args.kwargs
        self.assertFalse(kwargs["allow_missing"])
        self.assertFalse(kwargs["force"])

    def test_render_invalid_original_volume_errors(self) -> None:
        with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
            exit_code = cli.main(["render", "output/ep", "--original-volume", "2"])

        self.assertEqual(exit_code, 1)
        self.assertIn("original_volume", fake_stderr.getvalue())

    def test_render_negative_max_shift_errors(self) -> None:
        with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
            exit_code = cli.main(["render", "output/ep", "--max-shift=-1"])

        self.assertEqual(exit_code, 1)
        self.assertIn("max_shift_seconds", fake_stderr.getvalue())

    def test_render_missing_normalized_errors(self) -> None:
        # Không patch render_episode: thư mục không tồn tại phải ra RenderError thật.
        with (
            TemporaryDirectory() as tmp,
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["render", str(Path(tmp) / "no_such_episode")])

        self.assertEqual(exit_code, 1)
        self.assertIn("[render] LỖI", fake_stderr.getvalue())
        self.assertIn("normalize", fake_stderr.getvalue())

    def test_render_error_exits_one(self) -> None:
        with (
            patch(
                "app.audio.render.render_episode",
                side_effect=RenderError("2 segment thiếu audio (id 5, 6)"),
            ),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["render", "output/ep"])

        self.assertEqual(exit_code, 1)
        self.assertIn("[render] LỖI", fake_stderr.getvalue())
        self.assertIn("5, 6", fake_stderr.getvalue())


class TestGlossarySubcommand(unittest.TestCase):
    """CP6.5: subcommand ``glossary`` (patch ``draft_glossary_file``, không gọi model)."""

    def _result(self, skipped: bool = False, backup: Path | None = None) -> GlossaryDraftResult:
        return GlossaryDraftResult(
            glossary_path=Path("output/ep/glossary.yaml"),
            glossary=parse_glossary(
                {
                    "characters": [{"name": "A"}, {"name": "B"}],
                    "address": [
                        {"speaker": "A", "listener": "B", "self": "con", "other": "ba"},
                        {"speaker": "B", "listener": "A", "self": "ba", "other": "con"},
                    ],
                }
            ),
            skipped=skipped,
            backup_path=backup,
        )

    def test_glossary_help_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app", "glossary", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for flag in ("--model", "--max-chars", "--force", "--config"):
            self.assertIn(flag, result.stdout)

    def test_glossary_prints_summary_and_draft_notice(self) -> None:
        with (
            patch("app.translation.glossary_draft.draft_glossary_file", return_value=self._result()),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["glossary", "output/ep", "--model", "m"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("[glossary] glossary   : ", output)
        self.assertIn("[glossary] characters : 2", output)
        self.assertIn("[glossary] address    : 2", output)
        self.assertIn("[glossary] terms      : 0", output)
        self.assertIn("[glossary] LƯU Ý", output)
        self.assertIn("bản nháp", output)
        self.assertIn("python -m app translate", output)
        self.assertNotIn("SKIP", output)

    def test_glossary_skip_message(self) -> None:
        with (
            patch(
                "app.translation.glossary_draft.draft_glossary_file",
                return_value=self._result(skipped=True),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["glossary", "output/ep", "--model", "m"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn(
            "[glossary] SKIP: glossary.yaml đã tồn tại (dùng --force để tạo lại; "
            "bản cũ được lưu ở glossary.yaml.bak).",
            output,
        )
        # Vẫn in bốn dòng tổng kết, nhưng không nhắc "bản nháp" vì không tạo mới.
        self.assertIn("[glossary] characters : 2", output)
        self.assertNotIn("LƯU Ý", output)

    def test_glossary_force_prints_backup_path(self) -> None:
        with (
            patch(
                "app.translation.glossary_draft.draft_glossary_file",
                return_value=self._result(backup=Path("output/ep/glossary.yaml.bak")),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["glossary", "output/ep", "--model", "m", "--force"])

        self.assertEqual(exit_code, 0)
        self.assertIn("glossary.yaml.bak", fake_stdout.getvalue())

    def test_glossary_passes_options_to_draft(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text(
                "target_language: vi\ntranslation:\n  model: from-config\n"
                "  glossary_max_chars: 5000\n  max_attempts: 2\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "app.translation.glossary_draft.draft_glossary_file", return_value=self._result()
                ) as mock_draft,
                patch("sys.stdout", new_callable=StringIO),
            ):
                cli.main(["glossary", "output/ep", "--config", str(config_path)])
                config_kwargs = mock_draft.call_args.kwargs
                config_model = mock_draft.call_args.args[1].model

                cli.main(
                    [
                        "glossary", "output/ep", "--config", str(config_path),
                        "--model", "from-cli", "--max-chars", "1234", "--force",
                    ]
                )
                cli_kwargs = mock_draft.call_args.kwargs
                cli_model = mock_draft.call_args.args[1].model

        self.assertEqual(config_model, "from-config")
        self.assertEqual(config_kwargs["max_chars"], 5000)
        self.assertEqual(config_kwargs["max_attempts"], 2)
        self.assertEqual(config_kwargs["target_language"], "vi")
        self.assertFalse(config_kwargs["force"])
        self.assertEqual(cli_model, "from-cli")
        self.assertEqual(cli_kwargs["max_chars"], 1234)
        self.assertTrue(cli_kwargs["force"])

    def test_glossary_error_exits_one(self) -> None:
        with (
            patch(
                "app.translation.glossary_draft.draft_glossary_file",
                side_effect=GlossaryError("Không tìm thấy transcript.json. Chạy `transcribe`."),
            ),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["glossary", "output/ep", "--model", "m"])

        self.assertEqual(exit_code, 1)
        self.assertIn("[glossary] LỖI", fake_stderr.getvalue())
        self.assertIn("transcribe", fake_stderr.getvalue())

    def test_glossary_without_model_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text("translation:\n  batch_size: 20\n", encoding="utf-8")
            with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
                exit_code = cli.main(["glossary", "output/ep", "--config", str(config_path)])

        self.assertEqual(exit_code, 1)
        self.assertIn("[glossary] LỖI", fake_stderr.getvalue())
        self.assertIn("--model", fake_stderr.getvalue())

    def test_glossary_invalid_max_chars_errors(self) -> None:
        with patch("sys.stderr", new_callable=StringIO) as fake_stderr:
            exit_code = cli.main(["glossary", "output/ep", "--model", "m", "--max-chars", "0"])

        self.assertEqual(exit_code, 1)
        self.assertIn("--max-chars", fake_stderr.getvalue())


class TestTranslateGlossaryOption(unittest.TestCase):
    """CP6.5: ``translate`` gộp ``--glossary``/config với ``<ep>/glossary.yaml``."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.episode = self.root / "ep"
        self.episode.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _result(self) -> TranslationResult:
        return TranslationResult(
            translated_path=self.episode / "translated.json",
            source_language="en",
            target_language="vi",
            segments=[TranslatedSegment(1, 0.0, 1.0, "Hi", "Chào")],
            skipped=False,
            failed_ids=[],
        )

    def _translate(self, *extra: str) -> tuple[int, str, str, object]:
        with (
            patch(
                "app.translation.translate.translate_transcript", return_value=self._result()
            ) as mock_translate,
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["translate", str(self.episode), "--model", "m", *extra])
        return exit_code, fake_stdout.getvalue(), fake_stderr.getvalue(), mock_translate

    def test_no_glossary_prints_no_glossary_line_and_passes_none(self) -> None:
        exit_code, out, _, mock_translate = self._translate()
        self.assertEqual(exit_code, 0)
        self.assertNotIn("glossary", out)
        self.assertIsNone(mock_translate.call_args.kwargs["glossary"])

    def test_episode_glossary_is_picked_up_automatically(self) -> None:
        path = self.episode / "glossary.yaml"
        path.write_text("terms: {hare: thỏ rừng}\n", encoding="utf-8")
        exit_code, out, _, mock_translate = self._translate()

        self.assertEqual(exit_code, 0)
        self.assertIn(f"[translate] glossary : {path}", out)
        self.assertEqual(mock_translate.call_args.kwargs["glossary"].terms, (("hare", "thỏ rừng"),))

    def test_empty_glossary_file_behaves_like_none(self) -> None:
        (self.episode / "glossary.yaml").write_text("# chỉ có comment\n", encoding="utf-8")
        exit_code, out, _, mock_translate = self._translate()
        self.assertEqual(exit_code, 0)
        self.assertNotIn("glossary", out)
        self.assertIsNone(mock_translate.call_args.kwargs["glossary"])

    def test_glossary_flag_merges_shared_then_episode(self) -> None:
        shared = self.root / "shared.yaml"
        shared.write_text("context: chung\nterms: {a: mot}\n", encoding="utf-8")
        episode_file = self.episode / "glossary.yaml"
        episode_file.write_text("terms: {b: hai}\n", encoding="utf-8")
        exit_code, out, _, mock_translate = self._translate("--glossary", str(shared))

        self.assertEqual(exit_code, 0)
        self.assertIn(f"[translate] glossary : {shared}, {episode_file}", out)
        glossary = mock_translate.call_args.kwargs["glossary"]
        self.assertEqual(glossary.context, "chung")
        self.assertEqual(glossary.terms, (("a", "mot"), ("b", "hai")))

    def test_config_glossary_used_and_flag_overrides_it(self) -> None:
        config_shared = self.root / "config-shared.yaml"
        config_shared.write_text("terms: {c: ba}\n", encoding="utf-8")
        flag_shared = self.root / "flag-shared.yaml"
        flag_shared.write_text("terms: {f: sau}\n", encoding="utf-8")
        config_path = self.root / "c.yaml"
        config_path.write_text(
            f"translation:\n  model: m\n  glossary: {config_shared.as_posix()}\n", encoding="utf-8"
        )

        _, out, _, mock_translate = self._translate("--config", str(config_path))
        self.assertEqual(mock_translate.call_args.kwargs["glossary"].terms, (("c", "ba"),))
        self.assertIn(str(config_shared), out)

        _, out, _, mock_translate = self._translate(
            "--config", str(config_path), "--glossary", str(flag_shared)
        )
        self.assertEqual(mock_translate.call_args.kwargs["glossary"].terms, (("f", "sau"),))
        self.assertNotIn(str(config_shared), out)

    def test_missing_shared_glossary_exits_one(self) -> None:
        exit_code, out, err, mock_translate = self._translate(
            "--glossary", str(self.root / "khong-co.yaml")
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("[translate] LỖI", err)
        self.assertIn("khong-co.yaml", err)
        mock_translate.assert_not_called()

    def test_broken_episode_glossary_exits_one(self) -> None:
        (self.episode / "glossary.yaml").write_text("characterz: []\n", encoding="utf-8")
        exit_code, _, err, mock_translate = self._translate()
        self.assertEqual(exit_code, 1)
        self.assertIn("[translate] LỖI", err)
        self.assertIn("characterz", err)
        mock_translate.assert_not_called()


class TestDubSubcommand(unittest.TestCase):
    """CP7: subcommand ``dub`` (patch ``run_dub``, không chạy pipeline thật)."""

    def _result(self, **overrides: object) -> DubResult:
        base: dict[str, object] = dict(
            episode_dir=Path("output/ep"),
            output_path=Path("output/ep/output_vi.mp4"),
            source_language="en",
            segments=58,
            translate_failed_ids=[],
            missing_ids=[],
            too_long_ids=[],
            repair_rounds_used=0,
            glossary_paths=[],
            stage_seconds={
                "download": 3.1,
                "transcribe": 0.0,
                "translate": 0.0,
                "tts": 0.1,
                "normalize": 0.2,
                "render": 0.3,
            },
            skipped_stages=[],
        )
        base.update(overrides)
        return DubResult(**base)  # type: ignore[arg-type]

    def test_dub_help_lists_flags(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app", "dub", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for flag in (
            "--workspace", "--source-lang", "--glossary",
            "--original-volume", "--allow-missing", "--force", "--config",
        ):
            self.assertIn(flag, result.stdout)

    def test_dub_parse_defaults(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["dub", "https://youtu.be/x"])
        self.assertEqual(args.source_lang, "auto")
        self.assertFalse(args.force)
        self.assertFalse(args.allow_missing)

    def test_dub_success_prints_summary(self) -> None:
        with (
            patch("app.pipeline.dub.run_dub", return_value=self._result()) as mock_run,
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["dub", "https://youtu.be/x"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("[dub] episode    :", output)
        self.assertIn("en -> vi", output)
        self.assertIn("[dub] segments   : 58", output)
        self.assertIn("output_vi.mp4", output)
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args.args[0], "https://youtu.be/x")

    def test_dub_flags_override_config(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text(
                "translation:\n  model: m\n  glossary: from-config.yaml\n"
                "mixing:\n  original_volume: 0.2\n",
                encoding="utf-8",
            )
            with (
                patch("app.pipeline.dub.run_dub", return_value=self._result()) as mock_run,
                patch("sys.stdout", new_callable=StringIO),
            ):
                exit_code = cli.main(
                    [
                        "dub", "https://youtu.be/x",
                        "--config", str(config_path),
                        "--workspace", "output/custom",
                        "--original-volume", "0.5",
                        "--glossary", "shared.yaml",
                        "--source-lang", "auto",
                    ]
                )

        self.assertEqual(exit_code, 0)
        options = mock_run.call_args.args[2]
        self.assertEqual(options.workspace, Path("output/custom"))
        self.assertEqual(options.original_volume, 0.5)
        self.assertEqual(options.shared_glossary, Path("shared.yaml"))
        self.assertIsNone(options.source_lang)

    def test_dub_source_lang_flag_passthrough(self) -> None:
        with (
            patch("app.pipeline.dub.run_dub", return_value=self._result()) as mock_run,
            patch("sys.stdout", new_callable=StringIO),
        ):
            cli.main(["dub", "https://youtu.be/x", "--source-lang", "zh"])

        options = mock_run.call_args.args[2]
        self.assertEqual(options.source_lang, "zh")

    def test_dub_invalid_original_volume_errors_without_calling_run_dub(self) -> None:
        with (
            patch("app.pipeline.dub.run_dub") as mock_run,
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["dub", "https://youtu.be/x", "--original-volume", "1.5"])

        self.assertEqual(exit_code, 1)
        self.assertIn("[dub] LỖI", fake_stderr.getvalue())
        mock_run.assert_not_called()

    def test_dub_error_exits_one(self) -> None:
        with (
            patch("app.pipeline.dub.run_dub", side_effect=DubError("translate", "boom")),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["dub", "https://youtu.be/x"])

        self.assertEqual(exit_code, 1)
        output = fake_stderr.getvalue()
        self.assertIn("[dub] LỖI", output)
        self.assertIn("boom", output)

    def test_dub_warns_on_translate_failed_ids(self) -> None:
        with (
            patch("app.pipeline.dub.run_dub", return_value=self._result(translate_failed_ids=[5])),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["dub", "https://youtu.be/x"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO", output)
        self.assertIn("5", output)

    def test_dub_warns_on_missing_ids(self) -> None:
        with (
            patch(
                "app.pipeline.dub.run_dub",
                return_value=self._result(missing_ids=[7], repair_rounds_used=2),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["dub", "https://youtu.be/x", "--allow-missing"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO", output)
        self.assertIn("7", output)


class TestPlaylistSubcommand(unittest.TestCase):
    """CP8: subcommand ``playlist`` (patch ``run_playlist``, không chạy thật)."""

    def _episode(self, index: int, video_id: str, outcome: str, **kwargs: object) -> EpisodeOutcome:
        return EpisodeOutcome(
            index=index, video_id=video_id, title=f"Ep {index}", outcome=outcome, **kwargs
        )

    def _dub_result(self, **overrides: object) -> DubResult:
        base: dict[str, object] = dict(
            episode_dir=Path("output/pl/vid__Ep"),
            output_path=Path("output/pl/vid__Ep/output_vi.mp4"),
            source_language="en",
            segments=10,
            translate_failed_ids=[],
            missing_ids=[],
            too_long_ids=[],
            repair_rounds_used=0,
            glossary_paths=[],
            stage_seconds={"download": 1.0},
            skipped_stages=[],
        )
        base.update(overrides)
        return DubResult(**base)  # type: ignore[arg-type]

    def _result(
        self,
        episodes: list[EpisodeOutcome],
        *,
        aborted: bool = False,
        total: int | None = None,
        selected: int | None = None,
    ) -> PlaylistResult:
        return PlaylistResult(
            playlist_dir=Path("output/PLxxx__Series"),
            total=total if total is not None else len(episodes),
            selected=selected if selected is not None else len(episodes),
            episodes=episodes,
            aborted=aborted,
        )

    def test_playlist_help_lists_flags(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "app", "playlist", "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        for flag in (
            "--workspace", "--source-lang", "--glossary", "--original-volume",
            "--allow-missing", "--force", "--items", "--recheck", "--download-only", "--config",
        ):
            self.assertIn(flag, result.stdout)

    def test_playlist_parses_flags(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "playlist", "https://youtube.com/playlist?list=PLxxx",
                "--items", "1-3,5", "--recheck", "--workspace", "custom", "--download-only",
            ]
        )
        self.assertEqual(args.items, "1-3,5")
        self.assertTrue(args.recheck)
        self.assertEqual(args.workspace, "custom")
        self.assertTrue(args.download_only)

    def test_playlist_download_only_defaults_to_false(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["playlist", "https://youtube.com/playlist?list=PLxxx"])
        self.assertFalse(args.download_only)

    def test_invalid_items_exits_one_without_calling_run_playlist(self) -> None:
        with (
            patch("app.pipeline.playlist.run_playlist") as mock_run,
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(
                ["playlist", "https://youtube.com/playlist?list=PLxxx", "--items", "abc"]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("[playlist] LỖI", fake_stderr.getvalue())
        mock_run.assert_not_called()

    def test_invalid_original_volume_exits_one_without_calling_run_playlist(self) -> None:
        with (
            patch("app.pipeline.playlist.run_playlist") as mock_run,
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(
                [
                    "playlist", "https://youtube.com/playlist?list=PLxxx",
                    "--original-volume", "1.5",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertIn("[playlist] LỖI", fake_stderr.getvalue())
        mock_run.assert_not_called()

    def test_flags_override_config(self) -> None:
        with TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "c.yaml"
            config_path.write_text(
                "translation:\n  model: m\n  glossary: from-config.yaml\n"
                "mixing:\n  original_volume: 0.2\n",
                encoding="utf-8",
            )
            with (
                patch(
                    "app.pipeline.playlist.run_playlist", return_value=self._result([])
                ) as mock_run,
                patch("sys.stdout", new_callable=StringIO),
            ):
                exit_code = cli.main(
                    [
                        "playlist", "https://youtube.com/playlist?list=PLxxx",
                        "--config", str(config_path),
                        "--workspace", "output/custom",
                        "--glossary", "shared.yaml",
                    ]
                )

        self.assertEqual(exit_code, 0)
        options = mock_run.call_args.args[2]
        self.assertEqual(options.dub.workspace, Path("output/custom"))
        self.assertEqual(options.dub.shared_glossary, Path("shared.yaml"))

    def test_exit_zero_when_no_failed_no_aborted(self) -> None:
        episodes = [
            self._episode(1, "v1", "completed", result=self._dub_result()),
            self._episode(2, "v2", "completed", result=self._dub_result()),
            self._episode(3, "v3", "skipped"),
        ]
        with (
            patch("app.pipeline.playlist.run_playlist", return_value=self._result(episodes)),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["playlist", "https://youtube.com/playlist?list=PLxxx"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("completed 2 | skipped 1 | failed 0", output)

    def test_exit_one_when_failed_present(self) -> None:
        episodes = [
            self._episode(1, "v1", "completed", result=self._dub_result()),
            self._episode(
                2, "v2", "failed",
                error_stage="translate", error="[translate] Không kết nối được Ollama",
            ),
        ]
        with (
            patch("app.pipeline.playlist.run_playlist", return_value=self._result(episodes)),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["playlist", "https://youtube.com/playlist?list=PLxxx"])

        self.assertEqual(exit_code, 1)
        output = fake_stdout.getvalue()
        self.assertIn("[playlist] LỖI  EP02 v2 [translate] Không kết nối được Ollama", output)

    def test_exit_one_when_aborted(self) -> None:
        episodes = [
            self._episode(1, "v1", "failed", error_stage="translate", error="[translate] boom")
        ]
        with (
            patch(
                "app.pipeline.playlist.run_playlist",
                return_value=self._result(episodes, aborted=True),
            ),
            patch("sys.stdout", new_callable=StringIO),
        ):
            exit_code = cli.main(["playlist", "https://youtube.com/playlist?list=PLxxx"])

        self.assertEqual(exit_code, 1)

    def test_keyboard_interrupt_exits_130(self) -> None:
        with (
            patch("app.pipeline.playlist.run_playlist", side_effect=KeyboardInterrupt()),
            patch("sys.stderr", new_callable=StringIO) as fake_stderr,
        ):
            exit_code = cli.main(["playlist", "https://youtube.com/playlist?list=PLxxx"])

        self.assertEqual(exit_code, 130)
        self.assertIn("Ctrl+C", fake_stderr.getvalue())

    def test_warns_on_translate_failed_and_missing_ids_for_completed_only(self) -> None:
        episodes = [
            self._episode(3, "v3", "completed", result=self._dub_result(translate_failed_ids=[4, 9])),
            self._episode(5, "v5", "completed", result=self._dub_result(missing_ids=[12])),
        ]
        with (
            patch(
                "app.pipeline.playlist.run_playlist",
                return_value=self._result(episodes, total=5, selected=2),
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(["playlist", "https://youtube.com/playlist?list=PLxxx"])

        self.assertEqual(exit_code, 0)
        output = fake_stdout.getvalue()
        self.assertIn("CẢNH BÁO EP03: 2 câu dịch lỗi (id 4, 9)", output)
        self.assertIn("CẢNH BÁO EP05: 1 segment thiếu audio (id 12)", output)

    def test_download_only_flag_passed_to_playlist_options(self) -> None:
        with (
            patch(
                "app.pipeline.playlist.run_playlist", return_value=self._result([])
            ) as mock_run,
            patch("sys.stdout", new_callable=StringIO),
        ):
            cli.main(
                ["playlist", "https://youtube.com/playlist?list=PLxxx", "--download-only"]
            )

        options = mock_run.call_args.args[2]
        self.assertTrue(options.download_only)

    def test_download_only_summary_uses_downloaded_failed_line(self) -> None:
        episodes = [
            self._episode(1, "v1", "downloaded"),
            self._episode(2, "v2", "failed", error_stage="download", error="[download] boom"),
        ]
        with (
            patch(
                "app.pipeline.playlist.run_playlist", return_value=self._result(episodes)
            ),
            patch("sys.stdout", new_callable=StringIO) as fake_stdout,
        ):
            exit_code = cli.main(
                ["playlist", "https://youtube.com/playlist?list=PLxxx", "--download-only"]
            )

        self.assertEqual(exit_code, 1)
        output = fake_stdout.getvalue()
        self.assertIn("downloaded 1 | failed 1", output)
        self.assertNotIn("completed", output)
        self.assertIn("[playlist] LỖI  EP02 v2 [download] boom", output)


if __name__ == "__main__":
    unittest.main()

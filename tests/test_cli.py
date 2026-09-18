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
from app.transcription.whisper import Segment, TranscriptionError, TranscriptResult
from app.translation.translate import TranslatedSegment, TranslationResult
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


if __name__ == "__main__":
    unittest.main()

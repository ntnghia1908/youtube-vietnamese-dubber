"""Unit test cho ``app.transcription.whisper``.

Không load model faster-whisper thật — ``_run_whisper`` được mock.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.transcription.whisper import (
    Segment,
    TranscriptionError,
    TranscriptResult,
    transcribe_audio,
)


class TestTranscribeAudio(unittest.TestCase):
    def _fake_segments(self) -> list[Segment]:
        return [
            Segment(id=1, start=0.0, end=1.5, text="Hello"),
            Segment(id=2, start=1.5, end=3.2, text="World"),
        ]

    def test_raises_when_audio_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaises(TranscriptionError):
                transcribe_audio(tmp_path / "audio.wav", tmp_path / "transcript.json")

    def test_transcribes_when_transcript_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio_path = tmp_path / "audio.wav"
            audio_path.write_bytes(b"fake-audio")
            transcript_path = tmp_path / "transcript.json"

            with patch(
                "app.transcription.whisper._run_whisper",
                return_value=("en", self._fake_segments()),
            ) as mock_run:
                result = transcribe_audio(audio_path, transcript_path)

            mock_run.assert_called_once()
            self.assertIsInstance(result, TranscriptResult)
            self.assertEqual(result.language, "en")
            self.assertEqual(len(result.segments), 2)
            self.assertTrue(transcript_path.exists())

            data = json.loads(transcript_path.read_text(encoding="utf-8"))
            self.assertEqual(data["language"], "en")
            self.assertEqual(data["segments"][0]["id"], 1)
            self.assertEqual(data["segments"][0]["text"], "Hello")

    def test_skips_whisper_when_transcript_already_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio_path = tmp_path / "audio.wav"
            audio_path.write_bytes(b"fake-audio")
            transcript_path = tmp_path / "transcript.json"
            transcript_path.write_text(
                json.dumps(
                    {
                        "language": "en",
                        "segments": [{"id": 1, "start": 0.0, "end": 1.0, "text": "cached"}],
                    }
                ),
                encoding="utf-8",
            )

            with patch("app.transcription.whisper._run_whisper") as mock_run:
                result = transcribe_audio(audio_path, transcript_path)
                mock_run.assert_not_called()

            self.assertEqual(result.language, "en")
            self.assertEqual(result.segments[0].text, "cached")

    def test_force_retranscribes_even_if_transcript_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio_path = tmp_path / "audio.wav"
            audio_path.write_bytes(b"fake-audio")
            transcript_path = tmp_path / "transcript.json"
            transcript_path.write_text(
                json.dumps({"language": "en", "segments": []}), encoding="utf-8"
            )

            with patch(
                "app.transcription.whisper._run_whisper",
                return_value=("en", self._fake_segments()),
            ) as mock_run:
                result = transcribe_audio(audio_path, transcript_path, force=True)
                mock_run.assert_called_once()

            self.assertEqual(len(result.segments), 2)

    def test_raises_clear_error_when_whisper_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio_path = tmp_path / "audio.wav"
            audio_path.write_bytes(b"fake-audio")
            transcript_path = tmp_path / "transcript.json"

            with patch(
                "app.transcription.whisper._run_whisper",
                side_effect=TranscriptionError("model load failed"),
            ):
                with self.assertRaises(TranscriptionError):
                    transcribe_audio(audio_path, transcript_path)


class TestSourceLanguage(unittest.TestCase):
    """Ép ngôn ngữ gốc — auto-detect từng đoán sai `zh` thành `en`."""

    def _prepare(self, tmp_path: Path) -> tuple[Path, Path]:
        audio_path = tmp_path / "audio.wav"
        audio_path.write_bytes(b"fake-audio")
        return audio_path, tmp_path / "transcript.json"

    def test_source_language_is_passed_to_whisper(self) -> None:
        with TemporaryDirectory() as tmp:
            audio_path, transcript_path = self._prepare(Path(tmp))
            with patch(
                "app.transcription.whisper._run_whisper", return_value=("zh", [])
            ) as mock_run:
                transcribe_audio(audio_path, transcript_path, language="zh")
            self.assertEqual(mock_run.call_args.kwargs["language"], "zh")

    def test_language_defaults_to_none_meaning_autodetect(self) -> None:
        with TemporaryDirectory() as tmp:
            audio_path, transcript_path = self._prepare(Path(tmp))
            with patch(
                "app.transcription.whisper._run_whisper", return_value=("en", [])
            ) as mock_run:
                transcribe_audio(audio_path, transcript_path)
            self.assertIsNone(mock_run.call_args.kwargs["language"])

    def test_writes_language_actually_used_not_the_one_requested(self) -> None:
        """Ngôn ngữ ghi ra file phải là ngôn ngữ Whisper thực dùng.

        Regression: biến cục bộ từng trùng tên với tham số ``language``,
        làm giá trị yêu cầu che mất giá trị thực tế trả về.
        """
        with TemporaryDirectory() as tmp:
            audio_path, transcript_path = self._prepare(Path(tmp))
            with patch(
                "app.transcription.whisper._run_whisper", return_value=("yue", [])
            ):
                result = transcribe_audio(audio_path, transcript_path, language="zh")

            self.assertEqual(result.language, "yue")
            data = json.loads(transcript_path.read_text(encoding="utf-8"))
            self.assertEqual(data["language"], "yue")


if __name__ == "__main__":
    unittest.main()


class TestCpuThreads(unittest.TestCase):
    def test_cpu_threads_reaches_run_whisper(self) -> None:
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.wav"
            audio.write_bytes(b"x")
            with patch(
                "app.transcription.whisper._run_whisper", return_value=("en", [])
            ) as mock_run:
                transcribe_audio(audio, Path(tmp) / "t.json", cpu_threads=12)
            self.assertEqual(mock_run.call_args.kwargs["cpu_threads"], 12)

    def test_cpu_threads_reaches_whisper_model(self) -> None:
        import sys
        import types

        calls = []

        class FakeModel:
            def __init__(self, *args, **kwargs) -> None:
                calls.append(kwargs)

            def transcribe(self, path, language=None):
                return iter(()), types.SimpleNamespace(language="en")

        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = FakeModel
        with patch.dict(sys.modules, {"faster_whisper": fake}):
            from app.transcription.whisper import _run_whisper

            _run_whisper(Path("a.wav"), model_size="tiny", device="cpu",
                         compute_type="auto", language=None, cpu_threads=12)
        self.assertEqual(calls[0]["cpu_threads"], 12)

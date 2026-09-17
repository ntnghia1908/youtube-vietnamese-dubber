"""Unit test cho ``app.audio.ffmpeg``.

Không gọi ffmpeg thật — ``subprocess.run`` và ``shutil.which`` được mock.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app.audio.ffmpeg import AudioExtractionError, extract_audio


class TestExtractAudio(unittest.TestCase):
    def test_raises_when_source_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaises(AudioExtractionError):
                extract_audio(tmp_path / "source.mp4", tmp_path / "audio.wav")

    def test_raises_clear_error_when_ffmpeg_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            source_path.write_bytes(b"fake-video")

            with patch("app.audio.ffmpeg.shutil.which", return_value=None):
                with self.assertRaises(AudioExtractionError) as ctx:
                    extract_audio(source_path, tmp_path / "audio.wav")
            self.assertIn("ffmpeg", str(ctx.exception))

    def test_extracts_when_audio_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            source_path.write_bytes(b"fake-video")
            audio_path = tmp_path / "audio.wav"

            def _fake_run(cmd, **kwargs):
                # subprocess.run thật sẽ tạo file output — giả lập lại.
                audio_path.write_bytes(b"fake-audio")
                return MagicMock(returncode=0, stderr="")

            with (
                patch("app.audio.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("app.audio.ffmpeg.subprocess.run", side_effect=_fake_run) as mock_run,
            ):
                result = extract_audio(source_path, audio_path)

            mock_run.assert_called_once()
            self.assertEqual(result, audio_path)
            self.assertTrue(audio_path.exists())

    def test_skips_when_audio_already_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            source_path.write_bytes(b"fake-video")
            audio_path = tmp_path / "audio.wav"
            audio_path.write_bytes(b"already-here")

            with patch("app.audio.ffmpeg.subprocess.run") as mock_run:
                extract_audio(source_path, audio_path)
                mock_run.assert_not_called()

    def test_force_reextracts_even_if_audio_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            source_path.write_bytes(b"fake-video")
            audio_path = tmp_path / "audio.wav"
            audio_path.write_bytes(b"already-here")

            def _fake_run(cmd, **kwargs):
                audio_path.write_bytes(b"new-audio")
                return MagicMock(returncode=0, stderr="")

            with (
                patch("app.audio.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("app.audio.ffmpeg.subprocess.run", side_effect=_fake_run) as mock_run,
            ):
                extract_audio(source_path, audio_path, force=True)
                mock_run.assert_called_once()

    def test_raises_when_ffmpeg_returns_nonzero(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.mp4"
            source_path.write_bytes(b"fake-video")
            audio_path = tmp_path / "audio.wav"

            with (
                patch("app.audio.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch(
                    "app.audio.ffmpeg.subprocess.run",
                    return_value=MagicMock(returncode=1, stderr="invalid data found"),
                ),
            ):
                with self.assertRaises(AudioExtractionError) as ctx:
                    extract_audio(source_path, audio_path)
            self.assertIn("invalid data found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

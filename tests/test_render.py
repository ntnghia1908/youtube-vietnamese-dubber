"""Unit test cho ``app.audio.render`` — Checkpoint 6.

ffmpeg/ffprobe không được gọi thật: ``probe_duration``, ``decode_pcm`` và
``mix_video`` bị patch ở cấp module khi test ``render_episode``; riêng
``decode_pcm``/``mix_video`` được test bằng cách mock ``subprocess.run`` +
``shutil.which``. Sample rate patch thành 100 Hz cho nhẹ (``render_episode``
đọc ``VOICE_SAMPLE_RATE_HZ`` lúc gọi nên patch được).
"""

from __future__ import annotations

import json
import subprocess
import unittest
import wave
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from app.audio.render import (
    NORMALIZED_FILENAME,
    OUTPUT_FILENAME,
    RENDER_FILENAME,
    VOICE_TRACK_FILENAME,
    Placement,
    RenderError,
    build_voice_track,
    decode_pcm,
    mix_video,
    plan_placements,
    render_episode,
)

SR = 100  # sample rate giả cho test


def _quiet(_message: str) -> None:
    # Console Windows mặc định không phải UTF-8 — tránh crash khi log có dấu.
    pass


def _seg(
    seg_id: int,
    start: float,
    duration: float | None,
    *,
    status: str = "normal",
    audio: str | None = "auto",
    cache_key: str | None = "auto",
    tempo: float = 1.0,
) -> dict[str, Any]:
    """Một segment kiểu ``normalized.json`` (chỉ các field CP6 đọc)."""
    if audio == "auto":
        audio = f"tts/{seg_id:06d}.mp3"
    if cache_key == "auto":
        cache_key = f"key{seg_id}"
    return {
        "id": seg_id,
        "start": start,
        "end": start + 2.0,
        "status": status,
        "audio": audio,
        "audio_duration": duration if audio is not None else None,
        "tts_cache_key": cache_key,
        "tempo": tempo,
    }


def _pcm(value: int, n: int) -> bytes:
    return array("h", [value] * n).tobytes()


def _samples(wav_path: Path) -> tuple[array, tuple[int, int, int, int]]:
    """Đọc WAV: (samples, (channels, sampwidth, framerate, nframes))."""
    with wave.open(str(wav_path), "rb") as wav:
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
        params = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes())
    return samples, params


def _placement(seg_id: int, placed_at: float, audio: str | None = None) -> Placement:
    return Placement(
        id=seg_id,
        audio=audio or f"tts/{seg_id:06d}.mp3",
        start=placed_at,
        placed_at=placed_at,
        audio_duration=1.0,
        shift=0.0,
        overlap=0.0,
    )


class TestPlanPlacements(unittest.TestCase):
    def test_no_overlap_keeps_original_start(self) -> None:
        segs = [_seg(1, 0.0, 2.0), _seg(2, 3.0, 2.0), _seg(3, 6.0, 1.0)]
        placements = plan_placements(segs, max_shift=1.0)
        self.assertEqual([p.placed_at for p in placements], [0.0, 3.0, 6.0])
        self.assertEqual([p.shift for p in placements], [0.0, 0.0, 0.0])
        self.assertEqual([p.overlap for p in placements], [0.0, 0.0, 0.0])

    def test_overflow_shifts_next_then_recovers(self) -> None:
        segs = [_seg(1, 0.0, 3.5), _seg(2, 3.0, 2.0), _seg(3, 5.5, 1.0)]
        a, b, c = plan_placements(segs, max_shift=1.0)
        self.assertAlmostEqual(b.placed_at, 3.5)
        self.assertAlmostEqual(b.shift, 0.5)
        self.assertEqual(b.overlap, 0.0)
        # cursor sau B = 5.5 = start của C -> hồi phục, không dời nữa.
        self.assertAlmostEqual(c.placed_at, 5.5)
        self.assertAlmostEqual(c.shift, 0.0)
        self.assertEqual(a.shift, 0.0)

    def test_max_shift_cap_creates_overlap(self) -> None:
        segs = [_seg(1, 0.0, 3.5), _seg(2, 3.0, 2.0)]
        _a, b = plan_placements(segs, max_shift=0.3)
        self.assertAlmostEqual(b.placed_at, 3.3)
        self.assertAlmostEqual(b.shift, 0.3)
        self.assertAlmostEqual(b.overlap, 0.2)

    def test_zero_max_shift_means_pure_overlap(self) -> None:
        segs = [_seg(1, 0.0, 3.5), _seg(2, 3.0, 2.0)]
        _a, b = plan_placements(segs, max_shift=0)
        self.assertEqual(b.placed_at, 3.0)
        self.assertEqual(b.shift, 0.0)
        self.assertAlmostEqual(b.overlap, 0.5)

    def test_chain_of_too_long_never_exceeds_max_shift(self) -> None:
        # Mỗi câu dài 3.0s trong slot 2.0s: drift tích luỹ rất nhanh nếu không có trần.
        segs = [_seg(i, i * 2.0, 3.0) for i in range(1, 9)]
        placements = plan_placements(segs, max_shift=1.0)
        for p in placements:
            self.assertGreaterEqual(p.shift, 0.0)
            self.assertLessEqual(p.shift, 1.0 + 1e-9)
        # Chạm trần thì phải đè (drift không thể vượt trần mà không có overlap).
        self.assertTrue(any(p.overlap > 0 for p in placements))

    def test_skips_segments_without_audio(self) -> None:
        segs = [_seg(1, 0.0, 1.0), _seg(2, 2.0, None, status="silent", audio=None), _seg(3, 4.0, 1.0)]
        placements = plan_placements(segs, max_shift=1.0)
        self.assertEqual([p.id for p in placements], [1, 3])

    def test_sorts_by_start_then_id(self) -> None:
        segs = [_seg(3, 4.0, 1.0), _seg(2, 2.0, 1.0), _seg(1, 2.0, 1.0)]
        placements = plan_placements(segs, max_shift=1.0)
        self.assertEqual([p.id for p in placements], [1, 2, 3])

    def test_uses_audio_duration_not_tempo(self) -> None:
        # tempo/tts_duration không có trong input vẫn phải chạy; chỉ audio_duration được dùng.
        segs = [_seg(1, 0.0, 2.0, tempo=1.25), _seg(2, 1.0, 1.0)]
        _a, b = plan_placements(segs, max_shift=5.0)
        self.assertAlmostEqual(b.placed_at, 2.0)


class TestBuildVoiceTrack(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ep = Path(self._tmp.name)
        self.dst = self.ep / VOICE_TRACK_FILENAME

    def _build(self, placements: list[Placement], pcms: dict[str, bytes], total: float) -> None:
        def fake_decode(path: Path, sample_rate: int) -> bytes:
            self.assertEqual(sample_rate, SR)
            return pcms[Path(path).name]

        with patch("app.audio.render.decode_pcm", side_effect=fake_decode):
            build_voice_track(
                self.ep, placements, self.dst, total_seconds=total, sample_rate=SR, log=_quiet
            )

    def test_places_audio_at_exact_position(self) -> None:
        self._build([_placement(1, 1.0)], {"000001.mp3": _pcm(1000, 50)}, total=3.0)
        samples, (channels, width, rate, frames) = _samples(self.dst)
        self.assertEqual((channels, width, rate), (1, 2, SR))
        self.assertEqual(frames, 300)
        self.assertTrue(all(v == 1000 for v in samples[100:150]))
        self.assertTrue(all(v == 0 for v in samples[:100]))
        self.assertTrue(all(v == 0 for v in samples[150:]))

    def test_frame_count_is_ceil_of_total(self) -> None:
        self._build([], {}, total=2.501)  # 250.1 -> 251 frame
        _samples_, (_c, _w, _r, frames) = _samples(self.dst)
        self.assertEqual(frames, 251)

    def test_overlap_region_is_summed(self) -> None:
        self._build(
            [_placement(1, 1.0), _placement(2, 1.5)],
            {"000001.mp3": _pcm(1000, 100), "000002.mp3": _pcm(2000, 100)},
            total=4.0,
        )
        samples, _params = _samples(self.dst)
        self.assertTrue(all(v == 1000 for v in samples[100:150]))
        self.assertTrue(all(v == 3000 for v in samples[150:200]))
        self.assertTrue(all(v == 2000 for v in samples[200:250]))
        self.assertTrue(all(v == 0 for v in samples[250:]))

    def test_overlap_is_clamped_to_int16(self) -> None:
        self._build(
            [_placement(1, 0.0), _placement(2, 0.0), _placement(3, 2.0), _placement(4, 2.0)],
            {
                "000001.mp3": _pcm(30000, 100),
                "000002.mp3": _pcm(30000, 100),
                "000003.mp3": _pcm(-30000, 100),
                "000004.mp3": _pcm(-30000, 100),
            },
            total=4.0,
        )
        samples, _params = _samples(self.dst)
        self.assertTrue(all(v == 32767 for v in samples[0:100]))
        self.assertTrue(all(v == -32768 for v in samples[200:300]))

    def test_pcm_longer_than_track_is_truncated(self) -> None:
        self._build([_placement(1, 2.5)], {"000001.mp3": _pcm(500, 100)}, total=3.0)
        samples, (_c, _w, _r, frames) = _samples(self.dst)
        self.assertEqual(frames, 300)
        self.assertTrue(all(v == 500 for v in samples[250:300]))

    def test_placement_entirely_beyond_track_is_skipped(self) -> None:
        self._build([_placement(1, 5.0)], {"000001.mp3": _pcm(500, 10)}, total=3.0)
        samples, (_c, _w, _r, frames) = _samples(self.dst)
        self.assertEqual(frames, 300)
        self.assertTrue(all(v == 0 for v in samples))

    def test_decode_error_leaves_no_files(self) -> None:
        with patch("app.audio.render.decode_pcm", side_effect=RenderError("hỏng")):
            with self.assertRaises(RenderError):
                build_voice_track(
                    self.ep, [_placement(1, 0.0)], self.dst, total_seconds=2.0, sample_rate=SR,
                    log=_quiet,
                )
        self.assertFalse(self.dst.exists())
        self.assertFalse(self.dst.with_name("voice_track.tmp.wav").exists())

    def test_no_tmp_left_after_success(self) -> None:
        self._build([_placement(1, 0.0)], {"000001.mp3": _pcm(1, 10)}, total=1.0)
        self.assertTrue(self.dst.exists())
        self.assertFalse(self.dst.with_name("voice_track.tmp.wav").exists())


class TestDecodePcm(unittest.TestCase):
    def _run(self, *, returncode: int = 0, stdout: bytes = b"\x01\x00\x02\x00", stderr: bytes = b""):
        return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)

    def test_builds_command_and_returns_stdout_bytes(self) -> None:
        with (
            patch("app.audio.render.shutil.which", return_value="ffmpeg"),
            patch("app.audio.render.subprocess.run", return_value=self._run()) as fake_run,
        ):
            data = decode_pcm(Path("x.mp3"), 24000)

        self.assertEqual(data, b"\x01\x00\x02\x00")
        cmd = fake_run.call_args.args[0]
        joined = " ".join(cmd)
        self.assertIn("s16le", joined)
        self.assertIn("-ac 1", joined)
        self.assertIn("-ar 24000", joined)
        self.assertEqual(cmd[-1], "pipe:1")
        # stdout là PCM nhị phân: không được decode thành text.
        self.assertFalse(fake_run.call_args.kwargs.get("text"))

    def test_odd_length_drops_last_byte(self) -> None:
        with (
            patch("app.audio.render.shutil.which", return_value="ffmpeg"),
            patch(
                "app.audio.render.subprocess.run",
                return_value=self._run(stdout=b"\x01\x00\x02"),
            ),
        ):
            self.assertEqual(decode_pcm(Path("x.mp3"), 24000), b"\x01\x00")

    def test_nonzero_exit_raises(self) -> None:
        with (
            patch("app.audio.render.shutil.which", return_value="ffmpeg"),
            patch(
                "app.audio.render.subprocess.run",
                return_value=self._run(returncode=1, stdout=b"", stderr=b"Invalid data"),
            ),
        ):
            with self.assertRaisesRegex(RenderError, "Invalid data"):
                decode_pcm(Path("x.mp3"), 24000)

    def test_empty_stdout_raises(self) -> None:
        with (
            patch("app.audio.render.shutil.which", return_value="ffmpeg"),
            patch("app.audio.render.subprocess.run", return_value=self._run(stdout=b"")),
        ):
            with self.assertRaises(RenderError):
                decode_pcm(Path("x.mp3"), 24000)

    def test_missing_ffmpeg_raises(self) -> None:
        with patch("app.audio.render.shutil.which", return_value=None):
            with self.assertRaisesRegex(RenderError, "ffmpeg"):
                decode_pcm(Path("x.mp3"), 24000)


class TestMixVideo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ep = Path(self._tmp.name)
        self.dst = self.ep / OUTPUT_FILENAME

    def _mix(self) -> None:
        mix_video(
            self.ep / "source.mp4",
            self.ep / VOICE_TRACK_FILENAME,
            self.dst,
            original_volume=0.3,
            speech_volume=1.0,
        )

    def test_builds_command_and_replaces_tmp(self) -> None:
        seen: dict[str, Any] = {}

        def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            seen["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"mp4-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch("app.audio.render.shutil.which", return_value="ffmpeg"),
            patch("app.audio.render.subprocess.run", side_effect=fake_run),
        ):
            self._mix()

        cmd = seen["cmd"]
        joined = " ".join(cmd)
        self.assertIn("-c:v copy", joined)
        self.assertIn("-map 0:v:0", joined)
        self.assertIn("amix=inputs=2:duration=first:normalize=0", joined)
        self.assertIn("volume=0.3000", joined)
        self.assertEqual(Path(cmd[-1]).name, "output_vi.tmp.mp4")
        self.assertEqual(self.dst.read_bytes(), b"mp4-bytes")
        self.assertFalse((self.ep / "output_vi.tmp.mp4").exists())

    def test_ffmpeg_error_raises_and_removes_tmp(self) -> None:
        def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            Path(cmd[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Filter graph lỗi")

        with (
            patch("app.audio.render.shutil.which", return_value="ffmpeg"),
            patch("app.audio.render.subprocess.run", side_effect=fake_run),
        ):
            with self.assertRaisesRegex(RenderError, "Filter graph lỗi"):
                self._mix()

        self.assertFalse(self.dst.exists())
        self.assertFalse((self.ep / "output_vi.tmp.mp4").exists())

    def test_missing_ffmpeg_raises(self) -> None:
        with patch("app.audio.render.shutil.which", return_value=None):
            with self.assertRaisesRegex(RenderError, "ffmpeg"):
                self._mix()


class _RenderTestBase(unittest.TestCase):
    """Dựng episode giả + patch ffprobe/decode/mux."""

    SOURCE_DURATION = 20.0

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ep = Path(self._tmp.name)
        (self.ep / "source.mp4").write_bytes(b"fake-video")
        self.segments = [
            _seg(1, 0.0, 3.5),
            _seg(2, 3.0, 2.0, status="too_long", tempo=1.25),
            _seg(3, 5.5, 1.0),
            _seg(4, 7.0, None, status="silent", audio=None, cache_key=None),
        ]
        self._write_normalized()

        self.probe = patch(
            "app.audio.render.probe_duration", return_value=self.SOURCE_DURATION
        ).start()
        self.decode = patch(
            "app.audio.render.decode_pcm",
            side_effect=lambda path, sample_rate: _pcm(1000, sample_rate),  # 1.0s
        ).start()
        self.mix = patch("app.audio.render.mix_video", side_effect=self._fake_mix).start()
        patch("app.audio.render.VOICE_SAMPLE_RATE_HZ", SR).start()
        self.addCleanup(patch.stopall)

    def _fake_mix(self, source: Path, voice_track: Path, dst: Path, **_kwargs: Any) -> None:
        self.assertTrue(Path(voice_track).exists())
        Path(dst).write_bytes(b"fake-output")

    def _write_normalized(self) -> None:
        for seg in self.segments:
            if seg.get("audio") is not None:
                path = self.ep / seg["audio"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fake-audio")
        (self.ep / NORMALIZED_FILENAME).write_text(
            json.dumps({"segments": self.segments}, ensure_ascii=False), encoding="utf-8"
        )

    def _render(self, **kwargs: Any):
        kwargs.setdefault("log", _quiet)
        return render_episode(self.ep, **kwargs)

    def _reset_mocks(self) -> None:
        self.decode.reset_mock()
        self.mix.reset_mock()

    def _render_json(self) -> dict[str, Any]:
        return json.loads((self.ep / RENDER_FILENAME).read_text(encoding="utf-8"))


class TestRenderEpisode(_RenderTestBase):
    def test_first_run_builds_voice_track_and_output(self) -> None:
        result = self._render()

        self.assertFalse(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.assertEqual(self.decode.call_count, 3)
        self.assertEqual(self.mix.call_count, 1)
        self.assertEqual(result.placed_ids, [1, 2, 3])
        self.assertEqual(result.silent_ids, [4])
        self.assertEqual(result.missing_ids, [])
        self.assertEqual(result.shifted_ids, [2])
        self.assertEqual(result.overlap_ids, [])
        self.assertAlmostEqual(result.max_shift_seen, 0.5)
        self.assertEqual(result.duration, self.SOURCE_DURATION)
        self.assertEqual(result.output_path, self.ep / OUTPUT_FILENAME)

        _samples_, (channels, width, rate, frames) = _samples(self.ep / VOICE_TRACK_FILENAME)
        self.assertEqual((channels, width, rate), (1, 2, SR))
        self.assertEqual(frames, 2000)
        self.assertTrue((self.ep / OUTPUT_FILENAME).exists())

        data = self._render_json()
        self.assertIn("fingerprint", data["voice_track"])
        self.assertEqual(data["voice_track"]["sample_rate"], SR)
        self.assertEqual(data["voice_track"]["duration"], 20.0)
        self.assertEqual(data["voice_track"]["params"], {"max_shift_seconds": 1.0})
        self.assertEqual(
            data["voice_track"]["summary"],
            {"placed": 3, "silent": 1, "missing": 0, "shifted": 1, "overlap": 0,
             "max_shift_seen": 0.5},
        )
        placements = data["voice_track"]["placements"]
        self.assertEqual([p["id"] for p in placements], [1, 2, 3])
        self.assertEqual(placements[1]["placed_at"], 3.5)
        self.assertEqual(placements[1]["shift"], 0.5)
        self.assertEqual(
            data["output"]["params"], {"original_volume": 0.3, "speech_volume": 1.0}
        )
        self.assertIn("fingerprint", data["output"])

    def test_voice_samples_are_at_planned_positions(self) -> None:
        self._render()
        samples, _params = _samples(self.ep / VOICE_TRACK_FILENAME)
        # Mỗi file giả dài 1.0s (sample_rate sample). id 2 bị dời từ 3.0 -> 3.5s
        # nên [300, 350) phải im lặng; id 3 không bị dời (đặt đúng 5.5s).
        self.assertTrue(all(v == 1000 for v in samples[350:450]))  # id 2 tại 3.5s
        self.assertTrue(all(v == 0 for v in samples[300:350]))
        self.assertTrue(all(v == 1000 for v in samples[550:650]))  # id 3 tại 5.5s

    def test_second_run_skips_both(self) -> None:
        self._render()
        self._reset_mocks()

        result = self._render()

        self.assertTrue(result.voice_track_skipped)
        self.assertTrue(result.output_skipped)
        self.decode.assert_not_called()
        self.mix.assert_not_called()
        self.assertEqual(result.placed_ids, [1, 2, 3])
        self.assertEqual(result.shifted_ids, [2])

    def test_force_rebuilds_both(self) -> None:
        self._render()
        self._reset_mocks()

        result = self._render(force=True)

        self.assertFalse(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.assertEqual(self.decode.call_count, 3)
        self.assertEqual(self.mix.call_count, 1)

    def test_changing_original_volume_only_remuxes(self) -> None:
        self._render()
        self._reset_mocks()

        result = self._render(original_volume=0.5)

        self.assertTrue(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.decode.assert_not_called()
        self.assertEqual(self.mix.call_count, 1)
        self.assertEqual(self.mix.call_args.kwargs["original_volume"], 0.5)
        self.assertEqual(self._render_json()["output"]["params"]["original_volume"], 0.5)
        self.assertIn("voice_track", self._render_json())

    def test_changing_max_shift_rebuilds_even_if_placements_same(self) -> None:
        self._render(max_shift=1.0)
        self._reset_mocks()

        # max_shift 0.5 vẫn đủ để dời id 2 đúng 0.5s -> placement không đổi, nhưng
        # tham số đổi nên fingerprint phải đổi.
        result = self._render(max_shift=0.5)

        self.assertFalse(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.assertEqual(self.decode.call_count, 3)
        self.assertEqual(self.mix.call_count, 1)

    def test_int_and_float_max_shift_share_fingerprint(self) -> None:
        # `max_shift_seconds: 1` trong YAML là int, CLI là float — không được dựng lại oan.
        self._render(max_shift=1)
        self._reset_mocks()

        result = self._render(max_shift=1.0)

        self.assertTrue(result.voice_track_skipped)
        self.assertTrue(result.output_skipped)

    def test_changed_audio_duration_rebuilds_both(self) -> None:
        self._render()
        self._reset_mocks()
        self.segments[1]["audio_duration"] = 2.4
        self._write_normalized()

        result = self._render()

        self.assertFalse(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.assertEqual(self.mix.call_count, 1)

    def test_changed_tts_cache_key_rebuilds_both(self) -> None:
        self._render()
        self._reset_mocks()
        self.segments[0]["tts_cache_key"] = "another-key"
        self._write_normalized()

        result = self._render()

        self.assertFalse(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)

    def test_deleted_output_only_remuxes(self) -> None:
        self._render()
        self._reset_mocks()
        (self.ep / OUTPUT_FILENAME).unlink()

        result = self._render()

        self.assertTrue(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.decode.assert_not_called()
        self.assertEqual(self.mix.call_count, 1)

    def test_deleted_voice_track_rebuilds_but_keeps_matching_output(self) -> None:
        self._render()
        self._reset_mocks()
        (self.ep / VOICE_TRACK_FILENAME).unlink()

        result = self._render()

        self.assertFalse(result.voice_track_skipped)
        self.assertTrue(result.output_skipped)
        self.assertEqual(self.decode.call_count, 3)
        self.mix.assert_not_called()
        # Section output cũ phải được ghi lại sau khi voice bị bỏ tạm.
        data = self._render_json()
        self.assertIn("voice_track", data)
        self.assertIn("output", data)

    def test_corrupt_render_json_rebuilds_both(self) -> None:
        self._render()
        self._reset_mocks()
        (self.ep / RENDER_FILENAME).write_text("{cụt", encoding="utf-8")

        result = self._render()

        self.assertFalse(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.assertIn("output", self._render_json())

    def test_orphan_tmp_files_are_cleaned(self) -> None:
        (self.ep / "voice_track.tmp.wav").write_bytes(b"junk")
        (self.ep / "output_vi.tmp.mp4").write_bytes(b"junk")

        self._render()

        self.assertFalse((self.ep / "voice_track.tmp.wav").exists())
        self.assertFalse((self.ep / "output_vi.tmp.mp4").exists())

    def test_mux_failure_keeps_voice_section_only_then_resumes(self) -> None:
        self.mix.side_effect = RenderError("mux hỏng")
        with self.assertRaises(RenderError):
            self._render()

        data = self._render_json()
        self.assertIn("voice_track", data)
        self.assertNotIn("output", data)
        self.assertTrue((self.ep / VOICE_TRACK_FILENAME).exists())

        self._reset_mocks()
        self.mix.side_effect = self._fake_mix
        result = self._render()

        self.assertTrue(result.voice_track_skipped)
        self.assertFalse(result.output_skipped)
        self.decode.assert_not_called()
        self.assertIn("output", self._render_json())

    def test_missing_segment_raises_by_default(self) -> None:
        self.segments.append(_seg(5, 9.0, None, status="missing", audio=None))
        self.segments.append(_seg(6, 11.0, None, status="missing", audio=None))
        self._write_normalized()

        with self.assertRaises(RenderError) as ctx:
            self._render()

        message = str(ctx.exception)
        self.assertIn("5, 6", message)
        self.assertIn("`tts`", message)
        self.assertIn("`normalize`", message)
        self.assertIn("--allow-missing", message)
        self.mix.assert_not_called()

    def test_allow_missing_inserts_silence_and_reports_ids(self) -> None:
        self.segments.append(_seg(5, 9.0, None, status="missing", audio=None))
        self._write_normalized()

        result = self._render(allow_missing=True)

        self.assertEqual(result.missing_ids, [5])
        self.assertEqual(result.silent_ids, [4])
        self.assertEqual(result.placed_ids, [1, 2, 3])
        data = self._render_json()
        self.assertEqual(data["voice_track"]["summary"]["missing"], 1)
        self.assertNotIn(5, [p["id"] for p in data["voice_track"]["placements"]])

    def test_silent_segment_is_not_placed_and_not_an_error(self) -> None:
        result = self._render()

        self.assertEqual(result.silent_ids, [4])
        data = self._render_json()
        self.assertNotIn(4, [p["id"] for p in data["voice_track"]["placements"]])

    def test_audio_file_missing_on_disk_raises_even_when_allow_missing(self) -> None:
        (self.ep / "tts" / "000003.mp3").unlink()

        for allow in (False, True):
            with self.subTest(allow_missing=allow):
                with self.assertRaisesRegex(RenderError, r"id 3.*normalize"):
                    self._render(allow_missing=allow)

    def test_audio_without_duration_raises(self) -> None:
        self.segments[0]["audio_duration"] = None
        self._write_normalized()

        with self.assertRaisesRegex(RenderError, "id 1"):
            self._render()

    def test_missing_normalized_json_raises(self) -> None:
        (self.ep / NORMALIZED_FILENAME).unlink()

        with self.assertRaisesRegex(RenderError, "normalize"):
            self._render()

    def test_corrupt_normalized_json_raises(self) -> None:
        (self.ep / NORMALIZED_FILENAME).write_text("{cụt", encoding="utf-8")

        with self.assertRaises(RenderError):
            self._render()

    def test_normalized_json_without_segments_raises(self) -> None:
        (self.ep / NORMALIZED_FILENAME).write_text(json.dumps({"summary": {}}), encoding="utf-8")

        with self.assertRaisesRegex(RenderError, "segments"):
            self._render()

    def test_missing_source_raises(self) -> None:
        (self.ep / "source.mp4").unlink()

        with self.assertRaisesRegex(RenderError, "download"):
            self._render()

    def test_all_silent_still_builds_silent_track_and_muxes(self) -> None:
        self.segments = [
            _seg(1, 0.0, None, status="silent", audio=None, cache_key=None),
            _seg(2, 2.0, None, status="silent", audio=None, cache_key=None),
        ]
        self._write_normalized()

        result = self._render()

        self.assertEqual(result.placed_ids, [])
        self.assertEqual(result.silent_ids, [1, 2])
        self.decode.assert_not_called()
        self.assertEqual(self.mix.call_count, 1)
        samples, (_c, _w, _r, frames) = _samples(self.ep / VOICE_TRACK_FILENAME)
        self.assertEqual(frames, 2000)
        self.assertTrue(all(v == 0 for v in samples))
        self.assertEqual(self._render_json()["voice_track"]["placements"], [])

    def test_audio_longer_than_video_extends_track_and_warns(self) -> None:
        self.probe.return_value = 5.0  # video 5s, audio id 3 kết thúc ở 6.5s
        logs: list[str] = []

        self._render(log=logs.append)

        _samples_, (_c, _w, _r, frames) = _samples(self.ep / VOICE_TRACK_FILENAME)
        self.assertEqual(frames, 650)
        self.assertTrue(any("bị cắt" in line for line in logs))

    def test_passes_mix_parameters_to_mix_video(self) -> None:
        self._render(original_volume=0.4, speech_volume=1.2)

        args = self.mix.call_args.args
        self.assertEqual(args[0], self.ep / "source.mp4")
        self.assertEqual(args[1], self.ep / VOICE_TRACK_FILENAME)
        self.assertEqual(args[2], self.ep / OUTPUT_FILENAME)
        self.assertEqual(self.mix.call_args.kwargs["original_volume"], 0.4)
        self.assertEqual(self.mix.call_args.kwargs["speech_volume"], 1.2)

    def test_stretched_audio_path_is_used_instead_of_tts_file(self) -> None:
        # CP5: `audio` mới là file cuối cùng (timing/*.wav), `tts_file` là bản chưa co giãn.
        (self.ep / "timing").mkdir()
        (self.ep / "timing" / "000002.wav").write_bytes(b"fake")
        self.segments[1]["audio"] = "timing/000002.wav"
        self.segments[1]["tts_file"] = "tts/000002.mp3"
        self._write_normalized()

        self._render()

        decoded = [Path(call.args[0]).as_posix() for call in self.decode.call_args_list]
        self.assertTrue(any(p.endswith("timing/000002.wav") for p in decoded))
        self.assertFalse(any(p.endswith("tts/000002.mp3") for p in decoded))


if __name__ == "__main__":
    unittest.main()

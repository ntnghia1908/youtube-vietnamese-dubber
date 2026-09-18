"""Unit test cho ``app.synchronization.timing`` — Checkpoint 5.

``probe_duration``/``stretch_audio`` được mock ở cấp module (không gọi
ffmpeg/ffprobe thật) khi test ``normalize_timing``; hai hàm này được test
riêng bằng cách mock ``subprocess.run``/``shutil.which``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.synchronization.timing import (
    NORMALIZED_FILENAME,
    TimingError,
    classify,
    normalize_timing,
    probe_duration,
    stretch_audio,
)


def _quiet(_message: str) -> None:
    # Console Windows mặc định không phải UTF-8 — tránh crash khi log có dấu.
    pass


def _write_translated(path: Path, segments: list[tuple[int, float, float, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_language": "en",
                "target_language": "vi",
                "segments": [
                    {"id": i, "start": s, "end": e, "source_text": src, "translated_text": tr}
                    for (i, s, e, src, tr) in segments
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_manifest(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "edge",
                "voice": "vi-VN-HoaiMyNeural",
                "rate": "+0%",
                "volume": "+0%",
                "segments": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class TestClassify(unittest.TestCase):
    def test_ratio_one_is_normal(self) -> None:
        status, ratio, tempo = classify(5.0, 5.0, normal_max_ratio=1.05, max_tempo=1.25)
        self.assertEqual(status, "normal")
        self.assertEqual(ratio, 1.0)
        self.assertEqual(tempo, 1.0)

    def test_ratio_exactly_normal_max_ratio_is_normal(self) -> None:
        status, _ratio, tempo = classify(5.25, 5.0, normal_max_ratio=1.05, max_tempo=1.25)
        self.assertEqual(status, "normal")
        self.assertEqual(tempo, 1.0)

    def test_ratio_1_10_is_stretched_with_matching_tempo(self) -> None:
        status, ratio, tempo = classify(5.5, 5.0, normal_max_ratio=1.05, max_tempo=1.25)
        self.assertEqual(status, "stretched")
        self.assertAlmostEqual(ratio, 1.10)
        self.assertAlmostEqual(tempo, 1.10)

    def test_ratio_exactly_max_tempo_is_stretched(self) -> None:
        status, _ratio, tempo = classify(6.25, 5.0, normal_max_ratio=1.05, max_tempo=1.25)
        self.assertEqual(status, "stretched")
        self.assertAlmostEqual(tempo, 1.25)

    def test_ratio_1_30_is_too_long_capped_at_max_tempo(self) -> None:
        status, ratio, tempo = classify(6.5, 5.0, normal_max_ratio=1.05, max_tempo=1.25)
        self.assertEqual(status, "too_long")
        self.assertAlmostEqual(ratio, 1.30)
        self.assertEqual(tempo, 1.25)

    def test_zero_slot_is_too_long_with_none_ratio(self) -> None:
        status, ratio, tempo = classify(3.0, 0.0, normal_max_ratio=1.05, max_tempo=1.25)
        self.assertEqual(status, "too_long")
        self.assertIsNone(ratio)
        self.assertEqual(tempo, 1.25)


# Bảng tra ffprobe giả: tên file (không kèm thư mục) -> độ dài (giây).
_DURATIONS = {
    "000001.mp3": 5.0,   # slot 6.0 -> ratio 0.833 -> normal
    "000002.mp3": 5.4,   # slot 5.0 -> ratio 1.08 -> stretched
    "000003.mp3": 5.6,   # slot 4.0 -> ratio 1.4  -> too_long (cap 1.25)
    "000002.wav": 5.003,
    "000003.wav": 4.48,
}


def _make_fake_probe(durations: dict[str, float], fail_names: set[str] | None = None):
    fail_names = fail_names or set()
    calls: list[str] = []

    def fake_probe(path: Path) -> float:
        calls.append(path.name)
        if path.name in fail_names:
            raise TimingError(f"ffprobe giả lỗi cho {path.name}")
        try:
            return durations[path.name]
        except KeyError as exc:
            raise AssertionError(f"probe_duration gọi bất ngờ cho {path.name}") from exc

    return fake_probe, calls


def _make_fake_stretch():
    calls: list[tuple[str, str, float]] = []

    def fake_stretch(src: Path, dst: Path, tempo: float) -> None:
        calls.append((src.name, dst.name, tempo))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"WAV")

    return fake_stretch, calls


class TestNormalizeTimingMixedEpisode(unittest.TestCase):
    """Episode 7 segment bao phủ mọi status: normal/stretched/too_long/
    silent(empty)/missing(failed, thiếu entry, file bị xoá)."""

    def _setup(self, tmp: str) -> Path:
        base = Path(tmp)
        _write_translated(
            base / "translated.json",
            [
                (1, 0.0, 6.0, "A", "Một"),
                (2, 6.0, 11.0, "B", "Hai"),
                (3, 11.0, 15.0, "C", "Ba"),
                (4, 15.0, 16.0, "", ""),
                (5, 16.0, 17.0, "E", "Năm"),
                (6, 17.0, 18.0, "F", "Sáu"),
                (7, 18.0, 19.0, "G", "Bảy"),
            ],
        )
        _write_manifest(
            base / "tts" / "manifest.json",
            [
                {"id": 1, "status": "ok", "file": "000001.mp3", "cache_key": "key1", "text": "Một"},
                {"id": 2, "status": "ok", "file": "000002.mp3", "cache_key": "key2", "text": "Hai"},
                {"id": 3, "status": "ok", "file": "000003.mp3", "cache_key": "key3", "text": "Ba"},
                {"id": 4, "status": "empty", "file": None, "cache_key": None, "text": ""},
                {"id": 5, "status": "failed", "file": None, "cache_key": None, "text": "Năm", "error": "lỗi giả"},
                # id 6: không có entry trong manifest.
                {"id": 7, "status": "ok", "file": "000007.mp3", "cache_key": "key7", "text": "Bảy"},
            ],
        )
        tts_dir = base / "tts"
        for name in ("000001.mp3", "000002.mp3", "000003.mp3"):
            (tts_dir / name).write_bytes(b"MP3")
        # id 7: manifest nói "ok" nhưng file thật đã mất (đĩa bị dọn tay).
        return base

    def test_mixed_statuses_and_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS)
            fake_stretch, stretch_calls = _make_fake_stretch()

            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result = normalize_timing(base, log=_quiet)

            self.assertEqual(result.normal_ids, [1])
            self.assertEqual(result.stretched_ids, [2])
            self.assertEqual(result.too_long_ids, [3])
            self.assertEqual(result.silent_ids, [4])
            self.assertEqual(sorted(result.missing_ids), [5, 6, 7])
            self.assertFalse(result.skipped)

            # stretch_audio chỉ gọi cho id 2 (tempo 1.08) và id 3 (tempo 1.25).
            self.assertEqual(len(stretch_calls), 2)
            tempos = {name: tempo for (name, _dst, tempo) in stretch_calls}
            self.assertAlmostEqual(tempos["000002.mp3"], 1.08, places=4)
            self.assertAlmostEqual(tempos["000003.mp3"], 1.25, places=4)

            data = json.loads((base / NORMALIZED_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(data["summary"], {
                "segments": 7, "normal": 1, "stretched": 1, "too_long": 1, "silent": 1, "missing": 3,
            })
            self.assertEqual(data["too_long_ids"], [3])
            self.assertEqual(sorted(data["missing_ids"]), [5, 6, 7])

            by_id = {s["id"]: s for s in data["segments"]}
            self.assertEqual(by_id[1]["audio"], "tts/000001.mp3")
            self.assertEqual(by_id[1]["status"], "normal")
            self.assertEqual(by_id[2]["audio"], "timing/000002.wav")
            self.assertEqual(by_id[2]["status"], "stretched")
            self.assertEqual(by_id[3]["audio"], "timing/000003.wav")
            self.assertEqual(by_id[3]["status"], "too_long")
            self.assertGreater(by_id[3]["overflow"], 0.0)
            self.assertIsNone(by_id[4]["audio"])
            self.assertEqual(by_id[4]["status"], "silent")
            for missing_id in (5, 6, 7):
                self.assertEqual(by_id[missing_id]["status"], "missing")
                self.assertIsNone(by_id[missing_id]["audio"])
                self.assertIn("error", by_id[missing_id])

            self.assertTrue((base / "timing" / "000002.wav").exists())
            self.assertTrue((base / "timing" / "000003.wav").exists())

    def test_second_run_unchanged_skips_probe_and_stretch(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS)
            fake_stretch, stretch_calls = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                normalize_timing(base, log=_quiet)

            probe_calls.clear()
            stretch_calls.clear()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result2 = normalize_timing(base, log=_quiet)

            self.assertTrue(result2.skipped)
            self.assertEqual(probe_calls, [])
            self.assertEqual(stretch_calls, [])
            self.assertEqual(result2.normal_ids, [1])
            self.assertEqual(result2.stretched_ids, [2])
            self.assertEqual(result2.too_long_ids, [3])

    def test_force_reprobes_and_restretches_all_ok_segments(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS)
            fake_stretch, stretch_calls = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                normalize_timing(base, log=_quiet)

            probe_calls.clear()
            stretch_calls.clear()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result2 = normalize_timing(base, force=True, log=_quiet)

            self.assertFalse(result2.skipped)
            # --force bỏ qua cache: cả 3 file mp3 đều được ffprobe lại (cộng
            # thêm ffprobe trên 2 file .wav vừa co giãn để lấy audio_duration).
            mp3_probes = [name for name in probe_calls if name.endswith(".mp3")]
            self.assertEqual(sorted(mp3_probes), ["000001.mp3", "000002.mp3", "000003.mp3"])
            self.assertEqual(len(stretch_calls), 2)

    def test_changing_cache_key_reprobes_only_that_segment(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS)
            fake_stretch, stretch_calls = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                normalize_timing(base, log=_quiet)

            manifest_path = base / "tts" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest["segments"]:
                if entry["id"] == 1:
                    entry["cache_key"] = "key1-new"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            probe_calls.clear()
            stretch_calls.clear()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result2 = normalize_timing(base, log=_quiet)

            self.assertFalse(result2.skipped)
            self.assertEqual(probe_calls, ["000001.mp3"])
            self.assertEqual(stretch_calls, [])  # id 1 vẫn "normal", không cần ffmpeg.

    def test_changing_max_tempo_does_not_reprobe_only_restretches_changed_tempo(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS)
            fake_stretch, stretch_calls = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                normalize_timing(base, log=_quiet)

            probe_calls.clear()
            stretch_calls.clear()
            # id3 ratio 1.4: với max_tempo=1.4 chuyển too_long(tempo1.25) -> stretched(tempo1.4)
            # -> tempo đổi -> phải stretch lại. id2 ratio 1.08 vẫn <= 1.4 -> tempo giữ 1.08 -> không stretch lại.
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result2 = normalize_timing(base, max_tempo=1.4, log=_quiet)

            self.assertFalse(result2.skipped)
            # Không ffprobe lại file mp3 gốc (cache theo tts_cache_key); chỉ
            # ffprobe file .wav vừa co giãn lại (id 3, tempo đổi) để lấy
            # audio_duration thật.
            self.assertEqual(probe_calls, ["000003.wav"])
            self.assertEqual(len(stretch_calls), 1)
            self.assertEqual(stretch_calls[0][0], "000003.mp3")
            self.assertAlmostEqual(stretch_calls[0][2], 1.4, places=4)
            self.assertEqual(result2.stretched_ids, [2, 3])
            self.assertEqual(result2.too_long_ids, [])

    def test_manually_deleted_timing_file_is_recreated_without_reprobing(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS)
            fake_stretch, stretch_calls = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                normalize_timing(base, log=_quiet)

            (base / "timing" / "000002.wav").unlink()

            probe_calls.clear()
            stretch_calls.clear()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result2 = normalize_timing(base, log=_quiet)

            self.assertFalse(result2.skipped)
            self.assertEqual(stretch_calls, [("000002.mp3", "000002.wav", 1.08)])
            self.assertTrue((base / "timing" / "000002.wav").exists())

    def test_orphan_and_tmp_files_in_timing_dir_are_cleaned(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            timing_dir = base / "timing"
            timing_dir.mkdir()
            (timing_dir / "000099.wav").write_bytes(b"orphan")
            (timing_dir / "000001.tmp.wav").write_bytes(b"leftover")

            fake_probe, _ = _make_fake_probe(_DURATIONS)
            fake_stretch, _ = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                normalize_timing(base, log=_quiet)

            self.assertFalse((timing_dir / "000099.wav").exists())
            self.assertFalse((timing_dir / "000001.tmp.wav").exists())

    def test_ffprobe_error_on_one_file_marks_missing_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            base = self._setup(tmp)
            fake_probe, probe_calls = _make_fake_probe(_DURATIONS, fail_names={"000001.mp3"})
            fake_stretch, stretch_calls = _make_fake_stretch()
            with (
                patch("app.synchronization.timing.probe_duration", side_effect=fake_probe),
                patch("app.synchronization.timing.stretch_audio", side_effect=fake_stretch),
            ):
                result = normalize_timing(base, log=_quiet)

            self.assertEqual(result.normal_ids, [])
            self.assertIn(1, result.missing_ids)


class TestNormalizeTimingErrors(unittest.TestCase):
    def test_missing_translated_json_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "tts").mkdir()
            _write_manifest(base / "tts" / "manifest.json", [])
            with self.assertRaises(TimingError):
                normalize_timing(base, log=_quiet)

    def test_missing_manifest_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_translated(base / "translated.json", [(1, 0.0, 1.0, "A", "Một")])
            with self.assertRaises(TimingError):
                normalize_timing(base, log=_quiet)

    def test_corrupt_manifest_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_translated(base / "translated.json", [(1, 0.0, 1.0, "A", "Một")])
            (base / "tts").mkdir()
            (base / "tts" / "manifest.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(TimingError):
                normalize_timing(base, log=_quiet)


class TestProbeDuration(unittest.TestCase):
    def test_parses_stdout(self) -> None:
        fake_result = type("R", (), {"returncode": 0, "stdout": "5.208000\n", "stderr": ""})()
        with (
            patch("app.synchronization.timing.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("app.synchronization.timing.subprocess.run", return_value=fake_result),
        ):
            self.assertAlmostEqual(probe_duration(Path("x.mp3")), 5.208)

    def test_nonzero_exit_raises(self) -> None:
        fake_result = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        with (
            patch("app.synchronization.timing.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("app.synchronization.timing.subprocess.run", return_value=fake_result),
        ):
            with self.assertRaises(TimingError):
                probe_duration(Path("x.mp3"))

    def test_missing_ffprobe_raises(self) -> None:
        with patch("app.synchronization.timing.shutil.which", return_value=None):
            with self.assertRaises(TimingError):
                probe_duration(Path("x.mp3"))

    def test_non_numeric_output_raises(self) -> None:
        fake_result = type("R", (), {"returncode": 0, "stdout": "N/A\n", "stderr": ""})()
        with (
            patch("app.synchronization.timing.shutil.which", return_value="/usr/bin/ffprobe"),
            patch("app.synchronization.timing.subprocess.run", return_value=fake_result),
        ):
            with self.assertRaises(TimingError):
                probe_duration(Path("x.mp3"))


class TestStretchAudio(unittest.TestCase):
    def test_builds_atempo_filter_and_writes_via_tmp(self) -> None:
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "000001.mp3"
            src.write_bytes(b"MP3")
            dst = Path(tmp) / "timing" / "000001.wav"

            captured_cmd: list[str] = []

            def fake_run(cmd, **kwargs):
                captured_cmd.extend(cmd)
                # Mô phỏng ffmpeg ghi ra đúng đường dẫn .tmp.wav được truyền.
                tmp_path = dst.with_name(dst.stem + ".tmp.wav")
                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.write_bytes(b"WAV")
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with (
                patch("app.synchronization.timing.shutil.which", return_value="/usr/bin/ffmpeg"),
                patch("app.synchronization.timing.subprocess.run", side_effect=fake_run),
            ):
                stretch_audio(src, dst, 1.1)

            self.assertIn("atempo=1.1000", " ".join(captured_cmd))
            self.assertTrue(dst.exists())
            self.assertFalse(dst.with_name(dst.stem + ".tmp.wav").exists())

    def test_missing_ffmpeg_raises(self) -> None:
        with patch("app.synchronization.timing.shutil.which", return_value=None):
            with self.assertRaises(TimingError):
                stretch_audio(Path("a.mp3"), Path("b.wav"), 1.1)


if __name__ == "__main__":
    unittest.main()

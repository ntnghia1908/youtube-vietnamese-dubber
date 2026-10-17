"""Test ``app.hardware`` — bảng auto theo CPU/GPU (WEB-PARALLEL AC8)."""

from __future__ import annotations

import builtins
import os
import unittest
from unittest.mock import patch

from app import hardware


class TestResolve(unittest.TestCase):
    def test_table(self) -> None:
        # (cpus, device, cuda, max_jobs, cpu_threads)
        cases = [
            (32, "cpu", 0, 2, 12),
            (16, "auto", 0, 2, 8),
            (8, "auto", 0, 2, 4),
            (4, "auto", 0, 1, 2),
            (1, "auto", 0, 1, 1),
            (32, "auto", 1, 1, 12),
            (32, "cuda", 0, 1, 12),
        ]
        for cpus, device, cuda, jobs, threads in cases:
            with self.subTest(cpus=cpus, device=device, cuda=cuda):
                got, _ = hardware.resolve_web_max_jobs(
                    "auto", whisper_device=device, cpus=cpus, cuda_devices=cuda
                )
                self.assertEqual(got, jobs)
                self.assertEqual(hardware.resolve_whisper_cpu_threads("auto", cpus=cpus), threads)

    def test_explicit_values_pass_through(self) -> None:
        self.assertEqual(hardware.resolve_whisper_cpu_threads(0), 0)
        self.assertEqual(hardware.resolve_whisper_cpu_threads(7, cpus=32), 7)
        self.assertEqual(
            hardware.resolve_web_max_jobs(2, whisper_device="cuda"), (2, "theo config")
        )

    def test_reason_text(self) -> None:
        self.assertEqual(
            hardware.resolve_web_max_jobs("auto", whisper_device="cpu", cpus=32, cuda_devices=0),
            (2, "32 CPU"),
        )
        self.assertEqual(
            hardware.resolve_web_max_jobs("auto", whisper_device="auto", cpus=32, cuda_devices=1)[1],
            "có GPU CUDA dùng chung",
        )


class TestDetect(unittest.TestCase):
    def test_cpu_count_uses_affinity(self) -> None:
        with patch.object(os, "sched_getaffinity", create=True, return_value={0, 1, 2}):
            self.assertEqual(hardware.cpu_count(), 3)

    def test_cpu_count_fallback_without_affinity(self) -> None:
        with patch.object(os, "sched_getaffinity", create=True, side_effect=AttributeError), \
                patch.object(os, "cpu_count", return_value=6):
            self.assertEqual(hardware.cpu_count(), 6)
        with patch.object(os, "sched_getaffinity", create=True, side_effect=AttributeError), \
                patch.object(os, "cpu_count", return_value=None):
            self.assertEqual(hardware.cpu_count(), 1)

    def test_cuda_zero_when_import_fails(self) -> None:
        real_import = builtins.__import__

        def fake(name, *a, **k):
            if name == "ctranslate2":
                raise ImportError(name)
            return real_import(name, *a, **k)

        with patch.object(builtins, "__import__", fake):
            self.assertEqual(hardware.cuda_device_count(), 0)


if __name__ == "__main__":
    unittest.main()

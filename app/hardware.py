"""Dò phần cứng của máy đang chạy để chọn giá trị mặc định ``auto``.

Giá trị phụ thuộc máy (số CPU, có GPU hay không) không được hard-code: cùng một
config chạy trên máy 32 core và máy 4 core phải ra số thread/số job khác nhau
(WEB-PARALLEL). Thuần stdlib; ``ctranslate2`` chỉ import lười.
"""

from __future__ import annotations

import os

from app.config import MAX_WEB_JOBS

# Trên ~12 thread/tiến trình Whisper CPU tăng tốc kém.
WHISPER_THREADS_CAP = 12
MIN_CPUS_FOR_PARALLEL = 8


def cpu_count() -> int:
    """CPU thực sự được dùng, tối thiểu 1.

    Ưu tiên ``sched_getaffinity`` vì nó tôn trọng taskset/cgroup cpuset, còn
    ``os.cpu_count()`` báo cả CPU mà tiến trình không được phép dùng.
    """
    try:
        count = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        count = os.cpu_count() or 1
    return max(1, count)


def cuda_device_count() -> int:
    """Số GPU CUDA; thiếu thư viện hay lỗi bất kỳ -> 0 (dò lỗi không được làm hỏng lệnh)."""
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def resolve_whisper_cpu_threads(value: int | str, *, cpus: int | None = None) -> int:
    """``auto`` -> CPU / MAX_WEB_JOBS (trần 12); số cụ thể giữ nguyên (0 = thư viện tự chọn).

    Chia cố định cho MAX_WEB_JOBS: tiến trình pipeline không biết nó chạy từ
    web hay CLI nên giả định xấu nhất là 2 job song song.
    """
    if value != "auto":
        return int(value)
    if cpus is None:
        cpus = cpu_count()
    return max(1, min(WHISPER_THREADS_CAP, cpus // MAX_WEB_JOBS))


def resolve_web_max_jobs(
    value: int | str,
    *,
    whisper_device: str,
    cpus: int | None = None,
    cuda_devices: int | None = None,
) -> tuple[int, str]:
    """Trả ``(số job, lý do)``. ``auto``: có GPU dùng chung hoặc máy ít CPU -> 1."""
    if value != "auto":
        return int(value), "theo config"
    if whisper_device == "cuda":
        return 1, "có GPU CUDA dùng chung"
    if whisper_device == "auto":
        if cuda_devices is None:
            cuda_devices = cuda_device_count()
        if cuda_devices > 0:
            return 1, "có GPU CUDA dùng chung"
    if cpus is None:
        cpus = cpu_count()
    if cpus < MIN_CPUS_FOR_PARALLEL:
        return 1, f"{cpus} CPU"
    return MAX_WEB_JOBS, f"{cpus} CPU"

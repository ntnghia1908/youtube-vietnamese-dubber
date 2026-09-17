"""YouTube Vietnamese Dubber — project skeleton.

Công cụ local để tạo bản thuyết minh tiếng Việt cho video/playlist YouTube.
Xem docs/IMPLEMENTATION_PLAN.md để biết kiến trúc pipeline đầy đủ và lộ
trình các checkpoint.

Đã implement: tải video (Checkpoint 1), trích audio + speech-to-text
(Checkpoint 2), dịch transcript + config loader (Checkpoint 3). Chưa
implement: TTS, timing normalization, render, pipeline end-to-end, playlist.
"""

__version__ = "0.1.0"

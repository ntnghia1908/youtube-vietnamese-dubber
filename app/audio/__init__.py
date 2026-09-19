"""Stage: xử lý audio/video qua FFmpeg.

- ``ffmpeg.py`` (CP2): trích audio từ ``source.mp4`` ra ``audio.wav`` cho STT.
- ``render.py`` (CP6): dựng ``voice_track.wav`` từ ``normalized.json``, mix với
  audio gốc và xuất ``output_vi.mp4``.
"""

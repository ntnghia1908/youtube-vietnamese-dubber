"""Stage: text-to-speech tiếng Việt — Checkpoint 4.

- ``base``: abstraction ``TTSEngine`` + ``cache_key``.
- ``edge``: ``EdgeTTSEngine`` (edge-tts, miễn phí, không cần API key).
- ``synthesize``: stage translated.json -> tts/*.mp3, có resume/cache.
"""

from __future__ import annotations

from app.config import TTSConfig
from app.tts.base import TTSEngine, TTSError


def create_tts_engine(config: TTSConfig) -> TTSEngine:
    """Tạo engine theo ``config.provider`` — pipeline không gắn cứng provider."""
    if config.provider == "edge":
        from app.tts.edge import EdgeTTSEngine

        return EdgeTTSEngine(
            config.voice,
            config.rate,
            config.volume,
            timeout_seconds=config.timeout_seconds,
        )
    raise TTSError(f"TTS provider không hỗ trợ: {config.provider!r}")

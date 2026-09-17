"""Stage: dịch thuật (adapter cho nhiều backend) — Checkpoint 3.

- ``base``: abstraction ``Translator`` + validate output.
- ``prompt``: prompt và JSON schema dùng chung cho translator dạng LLM.
- ``ollama``: ``OllamaTranslator`` (Ollama local).
- ``translate``: stage transcript.json -> translated.json, có resume.
"""

from __future__ import annotations

from app.config import TranslationConfig
from app.translation.base import TranslationError, Translator


def create_translator(config: TranslationConfig) -> Translator:
    """Tạo translator theo ``config.provider`` — pipeline không gắn cứng provider."""
    if config.provider == "ollama":
        from app.translation.ollama import OllamaTranslator

        return OllamaTranslator(
            config.model or "",
            host=config.host,
            temperature=config.temperature,
            num_ctx=config.num_ctx,
            timeout_seconds=config.timeout_seconds,
            think=config.think,
        )
    raise TranslationError(f"Translator provider không hỗ trợ: {config.provider!r}")

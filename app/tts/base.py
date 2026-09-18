"""Abstraction ``TTSEngine`` — Checkpoint 4.

Mỗi provider (edge, sau này có thể Piper/Azure) implement ``synthesize``.
Retry, cache, ghi manifest KHÔNG nằm ở đây mà ở ``app.tts.synthesize`` —
engine chỉ lo tổng hợp một câu, giống cách ``Translator`` chỉ lo gọi model
một lần (xem ``app/translation/base.py``).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path


class TTSError(RuntimeError):
    """Lỗi tổng hợp giọng nói — không tự khắc phục được, báo cho người dùng."""


class TTSEngine(ABC):
    """Backend TTS. Mỗi provider là một subclass."""

    provider: str = ""

    def __init__(self, voice: str, rate: str, volume: str) -> None:
        self.voice = voice
        self.rate = rate
        self.volume = volume

    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> None:
        """Ghi audio ra ``output_path``. Raise ``TTSError`` nếu lỗi.

        Bao gồm cả trường hợp không nhận được audio (edge-tts trả
        ``NoAudioReceived`` với input toàn dấu câu) — đó vẫn là lỗi, không
        phải thành công lặng lẽ với file rỗng.
        """

    def cache_key(self, text: str) -> str:
        """Khoá cache: đổi provider/voice/rate/volume/text đều đổi khoá.

        Nhờ vậy sửa một câu dịch chỉ tổng hợp lại đúng câu đó, còn đổi
        voice/rate/volume thì toàn bộ segment bị tổng hợp lại (plan §13).
        """
        raw = "\n".join([self.provider, self.voice, self.rate, self.volume, text])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

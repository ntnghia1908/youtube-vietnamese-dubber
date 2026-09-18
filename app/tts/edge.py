"""``EdgeTTSEngine`` — tổng hợp giọng nói bằng edge-tts — Checkpoint 4.

edge-tts gọi dịch vụ giọng đọc của Microsoft Edge qua WebSocket (miễn phí,
không cần API key), chạy bất đồng bộ nên bọc trong ``asyncio.run``.
"""

from __future__ import annotations

from pathlib import Path

from app.tts.base import TTSEngine, TTSError


class EdgeTTSEngine(TTSEngine):
    provider = "edge"

    def __init__(self, voice: str, rate: str, volume: str, *, timeout_seconds: float) -> None:
        super().__init__(voice, rate, volume)
        self.timeout_seconds = timeout_seconds

    def synthesize(self, text: str, output_path: Path) -> None:
        # Import cục bộ: lệnh khác (download/transcribe/translate) không
        # cần cài edge-tts (và không cần mạng) để chạy.
        import asyncio

        import edge_tts

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text,
                self.voice,
                rate=self.rate,
                volume=self.volume,
                receive_timeout=int(self.timeout_seconds),
            )
            await communicate.save(str(output_path))

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001 — mọi lỗi của edge_tts/aiohttp/asyncio đều bọc lại
            raise TTSError(str(exc)) from exc

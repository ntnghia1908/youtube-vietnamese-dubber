"""Translator gọi Ollama local qua HTTP API ``/api/chat`` — Checkpoint 3.

Dùng ``urllib`` của thư viện chuẩn thay vì thêm dependency HTTP.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any

from app.translation.base import (
    TranslationError,
    Translator,
    TranslatorConnectionError,
    TranslatorOutputError,
)

DEFAULT_HOST = "http://localhost:11434"

# Trần số token output cho mỗi dòng (JSON bao quanh + câu tiếng Việt, vốn
# tốn token hơn tiếng Anh). Không đặt trần thì model 8B đôi khi lặp vô hạn
# trong structured output, treo tới hết timeout rồi retry y hệt; có trần
# thì nó dừng với done_reason="length" -> lỗi output -> batch được chia nhỏ.
_TOKENS_PER_LINE = 80
_TOKENS_OVERHEAD = 100


def resolve_host(host: str | None) -> str:
    """Host từ config > biến môi trường OLLAMA_HOST > localhost."""
    value = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).strip().rstrip("/")
    if "://" not in value:
        value = "http://" + value
    # OLLAMA_HOST thường được đặt là địa chỉ bind của server (0.0.0.0:11434);
    # client trên Windows không kết nối tới 0.0.0.0 được.
    return value.replace("://0.0.0.0", "://127.0.0.1")


class OllamaTranslator(Translator):
    provider = "ollama"

    def __init__(
        self,
        model: str,
        *,
        host: str | None = None,
        temperature: float = 0.3,
        num_ctx: int = 8192,
        timeout_seconds: float = 300.0,
        think: bool | None = False,
    ) -> None:
        super().__init__(model)
        self.host = resolve_host(host)
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.timeout_seconds = timeout_seconds
        self.think = think

    def _complete_json(
        self, messages: list[dict[str, str]], *, schema: dict[str, Any], item_count: int
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "options": {
                # temperature > 0 để retry thật sự ra output khác lần trước.
                "temperature": self.temperature,
                # Mặc định của Ollama có thể chỉ 2048/4096; prompt vượt quá sẽ
                # bị cắt đầu một cách im lặng -> mất luôn system prompt.
                "num_ctx": self.num_ctx,
                "num_predict": _TOKENS_OVERHEAD + _TOKENS_PER_LINE * item_count,
            },
        }
        # qwen3 mặc định "suy nghĩ" trước khi trả lời: chậm hơn nhiều lần mà
        # không cải thiện rõ bản dịch thoại ngắn. None = không gửi field này.
        if self.think is not None:
            body["think"] = self.think

        response = self._post("/api/chat", body)

        if response.get("done_reason") == "length":
            raise TranslatorOutputError(
                "Output bị cắt vì chạm giới hạn độ dài (num_predict/num_ctx)."
            )
        content = (response.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise TranslatorOutputError(f"Response Ollama không có message.content: {response!r}")
        return content

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self.host + path
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code >= 500:
                raise TranslatorConnectionError(
                    f"Ollama lỗi HTTP {exc.code}: {detail}"
                ) from exc
            # 4xx là lỗi cấu hình (sai tên model, option không hỗ trợ...):
            # gọi lại bao nhiêu lần cũng vậy, báo luôn.
            hint = ""
            if exc.code == 404:
                hint = f"\nKiểm tra `ollama list`, hoặc chạy `ollama pull {self.model}`."
            raise TranslationError(f"Ollama từ chối request (HTTP {exc.code}): {detail}{hint}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise TranslatorConnectionError(
                f"Không gọi được Ollama tại {self.host} ({exc}). "
                "Ollama đã chạy chưa (`ollama serve`)?"
            ) from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TranslatorConnectionError(f"Ollama trả về response không phải JSON: {exc}") from exc


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except OSError:
        return str(exc)
    finally:
        exc.close()
    try:
        return json.loads(raw).get("error", raw)
    except (json.JSONDecodeError, AttributeError):
        return raw or str(exc)

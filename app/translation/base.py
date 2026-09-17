"""Abstraction ``Translator`` + validate output của model — Checkpoint 3.

Hợp đồng công khai là ``translate_batch``: nhận một batch dòng, trả về
``{id: bản dịch}`` đã được validate (đủ ID, không trùng, không thừa).
Translator dạng LLM chỉ cần implement ``_complete_json``; prompt và
validate dùng chung ở đây để mọi provider bị kiểm tra như nhau.

Retry, chia nhỏ batch lỗi và lưu tiến trình KHÔNG nằm ở đây mà ở
``app.translation.translate`` — provider chỉ lo gọi model một lần.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from app.translation.prompt import (
    RESPONSE_SCHEMA,
    ContextLine,
    SourceLine,
    build_messages,
)


class TranslationError(RuntimeError):
    """Lỗi dịch không tự khắc phục được — báo thẳng cho người dùng."""


class TranslatorOutputError(TranslationError):
    """Model trả về output sai (JSON hỏng, thiếu/thừa/trùng ID...).

    Gọi lại có thể ra kết quả khác (temperature > 0), và batch nhỏ hơn
    thường qua được — nên lỗi này được retry rồi chia đôi batch.
    """


class TranslatorConnectionError(TranslationError):
    """Lỗi tạm thời khi gọi backend (timeout, 5xx, mất kết nối).

    Được retry có backoff, nhưng không chia batch: batch nhỏ hơn không
    làm server sống lại.
    """


def parse_translations(raw: str, lines: Sequence[SourceLine]) -> dict[int, str]:
    """Parse + validate output của model. Raise TranslatorOutputError nếu sai."""
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TranslatorOutputError(f"Output không phải JSON hợp lệ: {exc}") from exc

    # Chấp nhận cả mảng trần như ví dụ trong plan §11, dù schema yêu cầu object.
    items = data.get("translations") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise TranslatorOutputError("Output thiếu mảng `translations`.")

    expected = {ln.id for ln in lines}
    result: dict[int, str] = {}
    duplicates: set[int] = set()
    unexpected: set[Any] = set()

    for item in items:
        if not isinstance(item, dict):
            raise TranslatorOutputError(f"Phần tử không phải object: {item!r}")
        item_id, text = item.get("id"), item.get("text")
        if isinstance(item_id, bool) or not isinstance(item_id, int):
            raise TranslatorOutputError(f"`id` không phải số nguyên: {item!r}")
        if not isinstance(text, str):
            raise TranslatorOutputError(f"`text` không phải chuỗi: {item!r}")
        if item_id not in expected:
            unexpected.add(item_id)
        elif item_id in result:
            duplicates.add(item_id)
        result[item_id] = text.strip()

    missing = expected - result.keys()
    problems = []
    if missing:
        problems.append(f"thiếu id {sorted(missing)}")
    if duplicates:
        problems.append(f"trùng id {sorted(duplicates)}")
    if unexpected:
        problems.append(f"id lạ {sorted(unexpected)}")

    # Dòng gốc có chữ mà bản dịch rỗng = model "nuốt" câu (thường do gộp
    # hai dòng vào một) — TTS sẽ im lặng đúng chỗ có thoại.
    empty = sorted(ln.id for ln in lines if ln.text.strip() and ln.id in result and not result[ln.id])
    if empty:
        problems.append(f"bản dịch rỗng ở id {empty}")

    if problems:
        raise TranslatorOutputError("Output sai: " + "; ".join(problems))
    return result


class Translator(ABC):
    """Backend dịch. Mỗi provider (Ollama, OpenAI, ...) là một subclass."""

    provider: str = ""

    def __init__(self, model: str) -> None:
        if not model:
            raise TranslationError(
                "Chưa cấu hình model dịch. Đặt `translation.model` trong "
                "config.yaml hoặc truyền `--model` (vd --model qwen3:8b)."
            )
        self.model = model

    def translate_batch(
        self,
        lines: Sequence[SourceLine],
        *,
        context: Sequence[ContextLine],
        source_language: str,
        target_language: str,
    ) -> dict[int, str]:
        """Dịch một batch, trả về ``{id: bản dịch}`` đã validate."""
        messages = build_messages(
            lines,
            context=context,
            source_language=source_language,
            target_language=target_language,
        )
        raw = self._complete_json(messages, schema=RESPONSE_SCHEMA, item_count=len(lines))
        return parse_translations(raw, lines)

    @abstractmethod
    def _complete_json(
        self, messages: list[dict[str, str]], *, schema: dict[str, Any], item_count: int
    ) -> str:
        """Gọi model một lần, trả về chuỗi JSON thô.

        ``item_count`` giúp provider đặt giới hạn độ dài output hợp lý.
        """

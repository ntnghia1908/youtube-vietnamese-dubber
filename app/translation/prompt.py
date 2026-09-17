"""Prompt + JSON schema dùng chung cho mọi translator dạng LLM.

Prompt viết bằng tiếng Anh: model local cỡ 8B bám theo chỉ dẫn tiếng Anh
ổn định hơn, còn ngôn ngữ đích vẫn nêu rõ trong prompt.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

# Chỉ để prompt dễ hiểu hơn mã ISO; mã không có trong bảng thì dùng nguyên mã.
_LANGUAGE_NAMES = {
    "en": "English",
    "vi": "Vietnamese",
    "zh": "Chinese",
    "yue": "Cantonese",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "ru": "Russian",
    "th": "Thai",
}

# Bọc mảng trong object: structured output của Ollama/OpenAI ổn định hơn
# khi gốc JSON là object thay vì array.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
            },
        }
    },
    "required": ["translations"],
}


@dataclass(frozen=True)
class SourceLine:
    """Một dòng cần dịch."""

    id: int
    text: str
    duration: float


@dataclass(frozen=True)
class ContextLine:
    """Một dòng đã dịch ở batch trước, gửi kèm để giữ mạch và xưng hô."""

    id: int
    text: str
    translation: str


def language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)


def build_messages(
    lines: Sequence[SourceLine],
    *,
    context: Sequence[ContextLine],
    source_language: str,
    target_language: str,
) -> list[dict[str, str]]:
    src = language_name(source_language)
    tgt = language_name(target_language)

    system = f"""You translate spoken lines from {src} to {tgt} for a voice-over dub.

Rules:
- Translate every input item. Keep each "id" exactly as given.
- Never add, drop, merge or split items: exactly one output item per input item.
- Use natural, conversational {tgt}; do not translate word-for-word.
- Keep it short: each translation is read aloud within "duration" seconds.
- Whisper splits sentences across lines. If a line is a fragment, translate it as a fragment so consecutive lines still read naturally together.
- Keep forms of address and pronouns consistent between the same characters.
- Keep proper names unless they have a well-known {tgt} form.
- No explanations, notes, brackets or sound descriptions unless the source has them.
- Output only JSON: {{"translations": [{{"id": <id>, "text": "<translation>"}}]}}"""

    parts = []
    if context:
        ctx = [{"id": c.id, "text": c.text, "translation": c.translation} for c in context]
        parts.append(
            "Previous lines, already translated (context only, do NOT output them):\n"
            + json.dumps(ctx, ensure_ascii=False)
        )
    items = [{"id": ln.id, "duration": round(ln.duration, 1), "text": ln.text} for ln in lines]
    parts.append("Translate these lines:\n" + json.dumps(items, ensure_ascii=False))

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]

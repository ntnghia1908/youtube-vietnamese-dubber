"""Prompt + JSON schema dùng chung cho mọi translator dạng LLM.

Prompt viết bằng tiếng Anh: model local cỡ 8B bám theo chỉ dẫn tiếng Anh
ổn định hơn, còn ngôn ngữ đích vẫn nêu rõ trong prompt.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Chỉ để type hint: glossary.py import base.py, base.py import prompt.py,
    # nên import thật ở đây sẽ tạo vòng import.
    from app.translation.glossary import Glossary

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


def glossary_prompt_block(glossary: Glossary, target_language: str) -> str:
    """Khối ngữ cảnh/nhân vật/xưng hô/thuật ngữ nối vào cuối system prompt.

    Bỏ hẳn mục rỗng để prompt ngắn: model cỡ 8–12B dễ lạc khi khối dài, và
    ``num_ctx`` là tài nguyên chung với batch dịch.
    """
    tgt = language_name(target_language)
    sections: list[str] = []

    if glossary.context:
        sections.append(
            "Story context (written by the user; follow it over your own guesses):\n"
            + glossary.context
        )

    if glossary.characters:
        lines = []
        for c in glossary.characters:
            line = f'- {c.name} -> "{c.vi}"'
            if c.note:
                line += f" ({c.note})"
            line += "."
            if c.aliases:
                line += " Often misheard as: " + ", ".join(f'"{a}"' for a in c.aliases) + "."
            lines.append(line)
        sections.append(
            "Characters (the transcript comes from speech-to-text and may misspell names; "
            "use these):\n" + "\n".join(lines)
        )

    if glossary.address:
        # Câu chữ này đã đo trên episode thật (decisions/checkpoint-6.5.md, mục D):
        # gemma3:12b dịch đúng ba–con 13/13 câu "I love you". Hai lần thử câu chữ
        # mạnh hơn ("I" = "con" tường minh; dặn suy ra ai đang nói từ câu kể
        # "said <name>") KHÔNG cải thiện qwen3:8b (vẫn 0/13, luôn dùng "mình")
        # nên giữ bản đơn giản này.
        lines = [
            f'- When {a.speaker} speaks to {a.listener}: refers to self as "{a.self_term}", '
            f'calls the listener "{a.other_term}".'
            for a in glossary.address
        ]
        sections.append(f"Forms of address (use exactly these {tgt} pronouns):\n" + "\n".join(lines))

    if glossary.terms:
        lines = [f'- "{source}" -> "{vi}"' for source, vi in glossary.terms]
        sections.append("Fixed terms (always translate like this):\n" + "\n".join(lines))

    return "\n\n".join(sections)


def build_messages(
    lines: Sequence[SourceLine],
    *,
    context: Sequence[ContextLine],
    source_language: str,
    target_language: str,
    glossary: Glossary | None = None,
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

    # Glossary None/rỗng -> system prompt giống hệt CP3 (không đổi một byte).
    if glossary is not None and not glossary.is_empty():
        system += "\n\n" + glossary_prompt_block(glossary, target_language)

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

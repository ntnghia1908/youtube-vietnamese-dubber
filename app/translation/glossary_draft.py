"""Tạo NHÁP ``glossary.yaml`` bằng model — Checkpoint 6.5.

Model đọc tiêu đề + transcript rồi đề xuất tên nhân vật (kèm các cách
Whisper nghe sai), xưng hô và thuật ngữ. Đây chỉ là bản nháp cho người dùng
sửa tay trước khi chạy ``translate``, nên hai luật bảo vệ công sức của họ:

- ``glossary.yaml`` đã có thì SKIP, không gọi model; ``force`` thì lưu bản
  cũ ra ``glossary.yaml.bak`` rồi mới ghi.
- Model KHÔNG được tự điền mục ``skip`` (bỏ câu = mất thoại, chỉ người dùng
  được quyết) — schema không có key ``skip`` và kết quả luôn có ``skip`` rỗng.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.transcription.whisper import TRANSCRIPT_FILENAME, read_transcript
from app.translation.base import (
    TranslationError,
    Translator,
    TranslatorConnectionError,
    TranslatorOutputError,
)
from app.translation.glossary import (
    GLOSSARY_FILENAME,
    Glossary,
    GlossaryError,
    load_glossary,
    parse_glossary,
    write_glossary,
)
from app.translation.prompt import language_name
from app.youtube.download import METADATA_FILENAME

# `item_count` gửi cho provider để đặt trần token output: Ollama tính
# 100 + 80 * 40 = 3300 token — đủ cho vài nhân vật + xưng hô + thuật ngữ.
_DRAFT_ITEM_COUNT = 40

# Chờ giữa các lần thử khi mất kết nối (copy từ translate.py, không import private).
_RETRY_DELAYS = (2.0, 5.0)

# Trần số mục giữ lại sau khi làm sạch: model nhỏ đôi khi liệt kê tràn lan,
# glossary quá dài chiếm hết num_ctx của bước dịch.
_MAX_CHARACTERS = 30
_MAX_TERMS = 60
_MAX_ADDRESS = 30

BACKUP_SUFFIX = ".bak"

GLOSSARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "context": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "vi": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
                "required": ["name", "vi", "aliases", "note"],
            },
        },
        "address": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "listener": {"type": "string"},
                    "self": {"type": "string"},
                    "other": {"type": "string"},
                },
                "required": ["speaker", "listener", "self", "other"],
            },
        },
        # Dạng list [{source, vi}] chứ không phải dict: JSON schema khó ép
        # dict có khoá tuỳ ý; `_clean_draft` đổi lại thành dict.
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"source": {"type": "string"}, "vi": {"type": "string"}},
                "required": ["source", "vi"],
            },
        },
    },
    "required": ["context", "characters", "address", "terms"],
}

_DRAFT_HEADER = """\
glossary.yaml — ngữ cảnh cho bước dịch (`python -m app translate`).

Đây là bản NHÁP do model tạo, hãy sửa trước khi chạy `translate`:
model có thể chép sai tên nhân vật hoặc chọn sai xưng hô.

Các mục:
  context     - 1-2 câu về thể loại, khán giả, giọng kể; model dịch đọc mục này.
  characters  - nhân vật: `name` = tên chuẩn ở ngôn ngữ gốc, `vi` = tên khi lồng tiếng,
                `aliases` = các cách Whisper nghe sai (được thay bằng `name` trước khi dịch),
                `note` = ghi chú ngắn.
  address     - xưng hô: `speaker` nói với `listener`, tự xưng `self`, gọi đối phương `other`.
  terms       - thuật ngữ cố định: "nguồn": "tiếng Việt".
  skip        - câu chứa chuỗi này (không phân biệt hoa thường) bị bỏ, không dịch, không đọc.
                App KHÔNG tự điền mục này. Muốn dùng, thay dòng `skip: []` ở cuối file
                bằng đoạn sau (bỏ dấu "# " ở đầu mỗi dòng):
skip:
  - support Storybook Nanny on Patreon

Sửa file rồi chạy lại `translate`: app tự phát hiện glossary đổi và dịch lại từ đầu."""


@dataclass(frozen=True)
class GlossaryDraftResult:
    glossary_path: Path
    glossary: Glossary
    skipped: bool
    backup_path: Path | None


def build_draft_messages(
    *, title: str, transcript_text: str, source_language: str, target_language: str
) -> list[dict[str, str]]:
    src = language_name(source_language)
    tgt = language_name(target_language)

    system = f"""You write a translation brief for a voice-over dub from {src} to {tgt}.
You get the title and the transcript of one video. A translator will later see only short chunks of the transcript, so put here what it needs to stay consistent.

Rules:
- The transcript comes from speech-to-text, so proper names are often misheard (for example "hare" written as "hair"). If a name looks misheard, put the wrong spellings you see in the transcript into "aliases" and the correct form into "name".
- Only include characters that really appear in the transcript. Never invent characters, names or facts.
- "name": the character's name in {src}, spelled correctly. "vi": the name to use when dubbing into {tgt}; keep a proper name unchanged unless it has a well-known {tgt} form. "note": a few words in {tgt} on who the character is.
- "address": for every pair of characters who talk to each other, choose the natural {tgt} pronoun pair for their relationship (parent and child, friends, ...). "self" is how the speaker refers to themselves, "other" is how the speaker calls the listener. Give both directions. Pick ONE concrete pronoun for each field (never alternatives such as "a/b") and never use a neutral pronoun like "I" or "you" when the relationship has a specific pair.
- "terms": fixed terms or phrases that must always be translated the same way ("source" -> "vi"). Leave the list empty if there are none.
- "context": 1-2 sentences in {tgt} about the genre, the audience and the narrator's tone.
- Output only JSON that matches the schema."""

    user = f"Title: {title or '(unknown)'}\n\nTranscript:\n{transcript_text}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _clip_transcript(lines: list[str], max_chars: int) -> tuple[str, bool]:
    """Nối các dòng, cắt ở RANH GIỚI DÒNG để không cụt giữa câu. Trả (text, bị cắt)."""
    kept: list[str] = []
    total = 0
    for line in lines:
        cost = len(line) + (1 if kept else 0)
        if total + cost > max_chars:
            if not kept:
                # Một dòng đơn lẻ dài hơn cả trần: đành cắt cứng dòng đó.
                kept.append(line[:max_chars])
            return "\n".join(kept), True
        kept.append(line)
        total += cost
    return "\n".join(kept), False


def _read_title(metadata_path: Path | None) -> str:
    """Tiêu đề video, hoặc chuỗi rỗng nếu thiếu/hỏng metadata (không phải lỗi)."""
    if metadata_path is None or not metadata_path.exists():
        return ""
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        title = data.get("title", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return title.strip() if isinstance(title, str) else ""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_draft(raw: str) -> Glossary:
    """Parse JSON của model -> làm sạch -> ``Glossary`` (``skip`` luôn rỗng).

    Lỗi JSON/thiếu key ném ``TranslatorOutputError``; giá trị vượt validate
    của ``parse_glossary`` ném ``GlossaryError`` — cả hai đều được gọi lại.
    """
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TranslatorOutputError(f"Output không phải JSON hợp lệ: {exc}") from exc
    if not isinstance(data, dict):
        raise TranslatorOutputError("Output phải là một object JSON.")
    missing = [k for k in ("context", "characters", "address", "terms") if k not in data]
    if missing:
        raise TranslatorOutputError(f"Output thiếu key: {', '.join(missing)}.")
    for key in ("characters", "address", "terms"):
        if not isinstance(data[key], list):
            raise TranslatorOutputError(f"`{key}` phải là danh sách.")

    characters: list[dict[str, Any]] = []
    for item in data["characters"]:
        if not isinstance(item, dict) or not _text(item.get("name")):
            continue  # nhân vật không có tên thì vô dụng
        aliases = item.get("aliases")
        characters.append(
            {
                "name": _text(item["name"]),
                "vi": _text(item.get("vi")),
                "aliases": [a for a in aliases if isinstance(a, str)] if isinstance(aliases, list) else [],
                "note": _text(item.get("note")),
            }
        )

    address: list[dict[str, str]] = []
    for item in data["address"]:
        if not isinstance(item, dict):
            continue
        entry = {key: _text(item.get(key)) for key in ("speaker", "listener", "self", "other")}
        if all(entry.values()):  # thiếu một trong 4 trường thì parse_glossary sẽ từ chối
            address.append(entry)

    terms: dict[str, str] = {}
    for item in data["terms"]:
        if not isinstance(item, dict):
            continue
        source, vi = _text(item.get("source")), _text(item.get("vi"))
        if source and vi:
            terms.setdefault(source, vi)

    cleaned = {
        "context": _text(data["context"]),
        "characters": characters[:_MAX_CHARACTERS],
        "address": address[:_MAX_ADDRESS],
        "terms": dict(list(terms.items())[:_MAX_TERMS]),
        # Không có `skip`: model không được tự quyết bỏ câu nào.
    }
    return parse_glossary(cleaned, source="glossary draft")


def generate_glossary_draft(
    transcript_path: Path,
    translator: Translator,
    *,
    metadata_path: Path | None,
    target_language: str,
    max_chars: int = 8000,
    max_attempts: int = 3,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> Glossary:
    """Hỏi model một bản nháp glossary từ transcript. Không ghi file."""
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise GlossaryError(
            f"Không tìm thấy {transcript_path}. Chạy `transcribe` cho episode này trước."
        )
    try:
        source_language, segments = read_transcript(transcript_path)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GlossaryError(f"File {transcript_path} hỏng: {exc}") from exc

    lines = [seg.text.strip() for seg in segments if seg.text.strip()]
    transcript_text, truncated = _clip_transcript(lines, max_chars)
    if truncated:
        log(
            f"[glossary] CẢNH BÁO: transcript dài hơn {max_chars} ký tự — chỉ dùng phần đầu "
            "transcript, bổ sung glossary bằng tay nếu cần."
        )

    messages = build_draft_messages(
        title=_read_title(metadata_path),
        transcript_text=transcript_text,
        source_language=source_language,
        target_language=target_language,
    )

    last_error: TranslationError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = translator.complete_json(
                messages, schema=GLOSSARY_SCHEMA, item_count=_DRAFT_ITEM_COUNT
            )
            return _clean_draft(raw)
        except (TranslatorOutputError, GlossaryError) as exc:
            last_error = exc
            log(f"[glossary] lần {attempt}/{max_attempts} lỗi: {exc}")
        except TranslatorConnectionError as exc:
            last_error = exc
            log(f"[glossary] lần {attempt}/{max_attempts} lỗi: {exc}")
            if attempt < max_attempts:
                delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
                log(f"[glossary] thử lại sau {delay:g}s")
                sleep(delay)
        # TranslationError khác (sai tên model, option không hỗ trợ...) là lỗi
        # cấu hình: gọi lại vẫn vậy, để nổi lên luôn.

    raise GlossaryError(f"Không tạo được glossary sau {max_attempts} lần thử. Lỗi cuối: {last_error}")


def draft_glossary_file(
    episode_dir: Path,
    translator: Translator,
    *,
    target_language: str,
    max_chars: int = 8000,
    max_attempts: int = 3,
    force: bool = False,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> GlossaryDraftResult:
    """Tạo ``<ep>/glossary.yaml`` nháp. SKIP nếu đã có (trừ ``force``, khi đó có ``.bak``)."""
    episode_dir = Path(episode_dir)
    glossary_path = episode_dir / GLOSSARY_FILENAME
    exists = glossary_path.exists()

    if exists and not force:
        # Người dùng có thể đã sửa tay file này: không gọi model, không đụng vào.
        return GlossaryDraftResult(
            glossary_path=glossary_path,
            glossary=load_glossary(glossary_path),
            skipped=True,
            backup_path=None,
        )

    glossary = generate_glossary_draft(
        episode_dir / TRANSCRIPT_FILENAME,
        translator,
        metadata_path=episode_dir / METADATA_FILENAME,
        target_language=target_language,
        max_chars=max_chars,
        max_attempts=max_attempts,
        log=log,
        sleep=sleep,
    )

    backup_path: Path | None = None
    if exists:
        # Sao lưu SAU khi model đã trả kết quả hợp lệ: gọi model lỗi thì không
        # đụng file cũ. copy2 ghi đè .bak cũ nhưng luôn giữ bản trước khi đè.
        backup_path = glossary_path.with_name(glossary_path.name + BACKUP_SUFFIX)
        shutil.copy2(glossary_path, backup_path)
        log(f"[glossary] đã lưu bản cũ: {backup_path}")

    episode_dir.mkdir(parents=True, exist_ok=True)
    write_glossary(glossary, glossary_path, header=_DRAFT_HEADER)
    return GlossaryDraftResult(
        glossary_path=glossary_path,
        glossary=glossary,
        skipped=False,
        backup_path=backup_path,
    )

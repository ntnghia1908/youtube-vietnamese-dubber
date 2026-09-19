"""Glossary cho bước dịch — Checkpoint 6.5.

Cho model biết ngữ cảnh mà nó không tự suy ra được: tên nhân vật (kèm các
cách Whisper hay nghe sai), quan hệ/xưng hô, thuật ngữ cố định, và các câu
cần bỏ qua (vd lời kêu gọi Patreon cuối video). File ``glossary.yaml`` do
app tạo nháp (``glossary_draft``) rồi người dùng sửa tay.

Module này chỉ lo dữ liệu: parse/validate YAML, gộp hai tầng (dùng chung +
theo tập), hash, sửa alias trong text gửi model, ghi YAML. Prompt nằm ở
``prompt.py``, logic dịch ở ``translate.py``.

``yaml`` được import cục bộ trong ``load_glossary``/``write_glossary`` để
lệnh ``translate`` không có glossary vẫn chạy y hệt CP3 và không phụ thuộc
thêm thư viện.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.translation.base import TranslationError

GLOSSARY_FILENAME = "glossary.yaml"

_TOP_LEVEL_KEYS = ("context", "characters", "address", "terms", "skip")
_CHARACTER_KEYS = ("name", "vi", "aliases", "note")
_ADDRESS_KEYS = ("speaker", "listener", "self", "other")


class GlossaryError(TranslationError):
    """File glossary không đọc được hoặc có giá trị không hợp lệ."""


@dataclass(frozen=True)
class Character:
    name: str  # tên chuẩn ở ngôn ngữ nguồn
    vi: str  # tên/cách gọi tiếng Việt (bỏ trống -> = name)
    aliases: tuple[str, ...] = ()  # các cách Whisper nghe sai
    note: str = ""


@dataclass(frozen=True)
class Address:
    """Cách ``speaker`` xưng hô khi nói với ``listener`` (YAML: self/other)."""

    speaker: str
    listener: str
    self_term: str  # speaker tự xưng, vd "con"
    other_term: str  # speaker gọi listener, vd "ba"


@functools.lru_cache(maxsize=32)
def _alias_regex(characters: tuple[Character, ...]) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    """Dựng MỘT regex ghép mọi alias + bảng ``alias.casefold() -> name``.

    Alias dài xếp trước: nếu có cả "Big Nut Brown Hair" lẫn "Nut Brown Hair"
    thì regex phải thử cái dài trước, không thì alias ngắn ăn mất một phần
    của alias dài rồi để lại "Big " thừa. Alias trùng giữa hai nhân vật thì
    nhân vật khai báo trước thắng.
    """
    mapping: dict[str, str] = {}
    for character in characters:
        for alias in character.aliases:
            mapping.setdefault(alias.casefold(), character.name)
    if not mapping:
        return None, {}
    aliases = sorted(mapping, key=len, reverse=True)
    # (?<!\w)/(?!\w): khớp theo ranh giới từ để alias "Hair" không ăn vào "Hairy".
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(a) for a in aliases) + r")(?!\w)",
        re.IGNORECASE,
    )
    return pattern, mapping


@dataclass(frozen=True)
class Glossary:
    context: str = ""
    characters: tuple[Character, ...] = ()
    address: tuple[Address, ...] = ()
    terms: tuple[tuple[str, str], ...] = ()  # (nguồn, tiếng Việt), giữ thứ tự
    skip: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (self.context or self.characters or self.address or self.terms or self.skip)

    def to_dict(self) -> dict[str, Any]:
        """Đủ 5 key, kể cả rỗng — dùng cho hash và ghi YAML."""
        return {
            "context": self.context,
            "characters": [
                {"name": c.name, "vi": c.vi, "aliases": list(c.aliases), "note": c.note}
                for c in self.characters
            ],
            "address": [
                {
                    "speaker": a.speaker,
                    "listener": a.listener,
                    "self": a.self_term,
                    "other": a.other_term,
                }
                for a in self.address
            ],
            "terms": {source: vi for source, vi in self.terms},
            "skip": list(self.skip),
        }

    def sha256(self) -> str:
        """Hash nội dung đã chuẩn hoá: sửa comment/khoảng trắng/thứ tự key YAML
        không đổi hash, nên không kích hoạt dịch lại oan."""
        canonical = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def apply_aliases(self, text: str) -> str:
        """Thay mọi alias (cách nghe sai) trong ``text`` bằng tên chuẩn.

        Một lượt ``re.sub`` duy nhất: phần vừa thay không bị quét lại. Chỉ
        dùng cho text gửi model, không đụng ``transcript.json``.
        """
        pattern, mapping = _alias_regex(self.characters)
        if pattern is None:
            return text
        return pattern.sub(lambda m: mapping.get(m.group(0).casefold(), m.group(0)), text)

    def should_skip(self, text: str) -> bool:
        """Có ít nhất một chuỗi ``skip`` nằm trong ``text`` (không phân biệt hoa thường)."""
        folded = text.casefold()
        return any(item.casefold() in folded for item in self.skip)


# ---------------------------------------------------------------- parse


def _error(source: str, message: str) -> GlossaryError:
    return GlossaryError(f"{source}: {message}")


def _check_keys(mapping: dict[Any, Any], valid: tuple[str, ...], where: str, source: str) -> None:
    unknown = sorted(str(k) for k in mapping if k not in valid)
    if unknown:
        raise _error(
            source,
            f"key không hợp lệ trong {where}: {', '.join(unknown)}. Key hợp lệ: {', '.join(valid)}.",
        )


def _as_str(value: Any, where: str, source: str, *, required: bool = False) -> str:
    """``None`` (YAML để trống) -> chuỗi rỗng; kiểu khác chuỗi -> lỗi."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _error(source, f"{where} phải là chuỗi (đang là {value!r}).")
    value = value.strip()
    if required and not value:
        raise _error(source, f"{where} không được để trống.")
    return value


def _as_list(value: Any, where: str, source: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _error(source, f"{where} phải là danh sách (đang là {value!r}).")
    return value


def _as_mapping(value: Any, where: str, source: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise _error(source, f"{where} phải là mapping (key: value), đang là {value!r}.")
    return value


def _parse_character(item: Any, index: int, source: str) -> Character:
    where = f"characters[{index}]"
    mapping = _as_mapping(item, where, source)
    _check_keys(mapping, _CHARACTER_KEYS, where, source)
    name = _as_str(mapping.get("name"), f"{where}.name", source, required=True)
    vi = _as_str(mapping.get("vi"), f"{where}.vi", source) or name
    note = _as_str(mapping.get("note"), f"{where}.note", source)

    aliases: list[str] = []
    # Không để alias trùng `name` hoặc trùng nhau (không phân biệt hoa thường):
    # regex vẫn chạy đúng nhưng thừa, và hash đổi oan khi người dùng thêm trùng.
    seen = {name.casefold()}
    for j, raw_alias in enumerate(_as_list(mapping.get("aliases"), f"{where}.aliases", source)):
        alias = _as_str(raw_alias, f"{where}.aliases[{j}]", source)
        if not alias or alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        aliases.append(alias)
    return Character(name=name, vi=vi, aliases=tuple(aliases), note=note)


def _parse_address(item: Any, index: int, source: str) -> Address:
    where = f"address[{index}]"
    mapping = _as_mapping(item, where, source)
    _check_keys(mapping, _ADDRESS_KEYS, where, source)
    missing = [key for key in _ADDRESS_KEYS if key not in mapping]
    if missing:
        raise _error(source, f"{where} thiếu key: {', '.join(missing)}.")
    values = {
        key: _as_str(mapping[key], f"{where}.{key}", source, required=True) for key in _ADDRESS_KEYS
    }
    return Address(
        speaker=values["speaker"],
        listener=values["listener"],
        self_term=values["self"],
        other_term=values["other"],
    )


def parse_glossary(data: Any, *, source: str = "glossary") -> Glossary:
    """Dựng ``Glossary`` từ dữ liệu YAML đã parse. Raise GlossaryError nếu sai.

    Nghiêm như ``parse_config``: key lạ ở mọi cấp bị từ chối (gõ nhầm
    ``alias`` thay vì ``aliases`` mà lặng lẽ bỏ qua thì bản dịch sai mà không
    ai biết vì sao). ``source`` (thường là đường dẫn file) đứng đầu thông báo.
    """
    if data is None:
        return Glossary()
    if not isinstance(data, dict):
        raise _error(source, "glossary phải là một mapping ở cấp cao nhất.")
    _check_keys(data, _TOP_LEVEL_KEYS, "glossary", source)

    context = _as_str(data.get("context"), "context", source)
    characters = tuple(
        _parse_character(item, i, source)
        for i, item in enumerate(_as_list(data.get("characters"), "characters", source))
    )
    address = tuple(
        _parse_address(item, i, source)
        for i, item in enumerate(_as_list(data.get("address"), "address", source))
    )

    terms: list[tuple[str, str]] = []
    raw_terms = data.get("terms")
    if raw_terms is not None:
        for key, value in _as_mapping(raw_terms, "terms", source).items():
            where = f"terms[{key!r}]"
            terms.append(
                (
                    _as_str(key, f"key của {where}", source, required=True),
                    _as_str(value, where, source, required=True),
                )
            )

    skip: list[str] = []
    for i, item in enumerate(_as_list(data.get("skip"), "skip", source)):
        text = _as_str(item, f"skip[{i}]", source)
        if text:
            skip.append(text)

    return Glossary(
        context=context,
        characters=characters,
        address=address,
        terms=tuple(terms),
        skip=tuple(skip),
    )


def load_glossary(path: Path) -> Glossary:
    """Đọc một file glossary YAML. File không tồn tại/hỏng -> GlossaryError."""
    path = Path(path)
    if not path.exists():
        raise GlossaryError(f"Không tìm thấy file glossary: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise GlossaryError("Chưa cài `pyyaml`. Chạy `pip install -e .` rồi thử lại.") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GlossaryError(f"Không đọc được file glossary {path}: {exc}") from exc
    return parse_glossary(data, source=str(path))


# ---------------------------------------------------------------- merge


def merge_glossaries(base: Glossary, override: Glossary) -> Glossary:
    """Gộp hai tầng: ``override`` (theo tập) thắng ``base`` (dùng chung).

    Khoá gộp không phân biệt hoa thường. Cùng khoá thì entry của override
    thay cả entry của base (không trộn từng field: alias/note của base sẽ
    không lén sót lại khi người dùng đã chủ động khai báo lại nhân vật).
    """
    characters = {c.name.casefold(): c for c in base.characters}
    for c in override.characters:
        characters[c.name.casefold()] = c

    address = {(a.speaker.casefold(), a.listener.casefold()): a for a in base.address}
    for a in override.address:
        address[(a.speaker.casefold(), a.listener.casefold())] = a

    terms = {source.casefold(): (source, vi) for source, vi in base.terms}
    for source, vi in override.terms:
        terms[source.casefold()] = (source, vi)

    skip: dict[str, str] = {}
    for item in (*base.skip, *override.skip):
        skip.setdefault(item.casefold(), item)

    return Glossary(
        context=override.context or base.context,
        characters=tuple(characters.values()),
        address=tuple(address.values()),
        terms=tuple(terms.values()),
        skip=tuple(skip.values()),
    )


def load_effective_glossary(
    episode_dir: Path, shared_path: Path | None
) -> tuple[Glossary | None, list[Path]]:
    """Glossary hiệu lực của một tập: file dùng chung rồi ``<ep>/glossary.yaml``.

    ``shared_path`` được chỉ định rõ mà không tồn tại là lỗi (gõ sai đường
    dẫn thì phải báo, không lặng lẽ dịch không glossary); ``glossary.yaml``
    của tập thì tuỳ chọn. Không file nào, hoặc kết quả rỗng, trả
    ``(None, [])`` để hành vi dịch y hệt lúc không có glossary.
    """
    paths: list[Path] = []
    effective: Glossary | None = None

    if shared_path is not None:
        shared_path = Path(shared_path)
        if not shared_path.exists():
            raise GlossaryError(f"Không tìm thấy glossary dùng chung: {shared_path}")
        effective = load_glossary(shared_path)
        paths.append(shared_path)

    episode_path = Path(episode_dir) / GLOSSARY_FILENAME
    if episode_path.exists():
        episode_glossary = load_glossary(episode_path)
        # Chỉ có một file thì giữ nguyên, không đi qua merge (merge gộp trùng khoá).
        effective = episode_glossary if effective is None else merge_glossaries(effective, episode_glossary)
        paths.append(episode_path)

    if effective is None or effective.is_empty():
        return None, []
    return effective, paths


# ---------------------------------------------------------------- write


def write_glossary(glossary: Glossary, path: Path, *, header: str) -> None:
    """Ghi glossary ra YAML sau phần ``header`` (comment), atomic.

    Ghi ra ``.tmp`` rồi ``os.replace``: bị kill giữa chừng thì file của người
    dùng không bị cụt.
    """
    try:
        import yaml
    except ImportError as exc:
        raise GlossaryError("Chưa cài `pyyaml`. Chạy `pip install -e .` rồi thử lại.") from exc

    body = yaml.safe_dump(
        glossary.to_dict(),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )
    # Mỗi dòng header phải là comment YAML, nếu không file sinh ra sẽ hỏng.
    header_lines = [
        line if line.startswith("#") else ("# " + line if line else "#")
        for line in header.splitlines()
    ]
    text = ("\n".join(header_lines) + "\n\n" if header_lines else "") + body

    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

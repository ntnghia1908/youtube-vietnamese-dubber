"""Đọc/validate/lưu ``glossary.yaml`` của một tập cho Web UI (WEB-2).

Không import fastapi (test được khi chưa cài extra ``web``). Validate dùng
đúng parser của pipeline (``parse_glossary``) nên thứ web chấp nhận thì
``translate`` cũng đọc được, và hash ``stale`` tính cùng cách với pipeline
(hash trên nội dung đã chuẩn hoá: đổi comment/khoảng trắng không làm stale).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.translation.glossary import (
    GLOSSARY_FILENAME,
    GlossaryError,
    load_effective_glossary,
    parse_glossary,
)
from app.translation.glossary_draft import BACKUP_SUFFIX
from app.translation.translate import TRANSLATED_FILENAME
from app.transcription.whisper import TRANSCRIPT_FILENAME
from app.web.jobs import JobRequest, JobValidationError
from app.youtube.download import METADATA_FILENAME

MAX_GLOSSARY_BYTES = 256 * 1024
PLAYLIST_FILENAME = "playlist.json"

# Hai tab/hai request lưu cùng lúc: bước kiểm hash + ghi phải nguyên khối,
# nếu không "check rồi ghi" bị chen ngang và 409 không còn đáng tin.
_save_lock = threading.Lock()


class GlossaryConflictError(Exception):
    """File trên đĩa đã đổi so với ``base_sha256`` mà client đang giữ."""


@dataclass(frozen=True)
class GlossaryState:
    exists: bool
    content: str
    file_sha256: str | None
    shared_path: str | None
    effective_sha256: str | None
    translated_sha256: str | None
    has_translation: bool
    stale: bool | None
    has_transcript: bool
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_glossary_state(episode_dir: Path, shared_path: Path | None) -> GlossaryState:
    episode_dir = Path(episode_dir)
    path = episode_dir / GLOSSARY_FILENAME
    exists = path.is_file()
    content = ""
    file_sha: str | None = None
    error: str | None = None
    if exists:
        raw = path.read_bytes()
        file_sha = _sha256_bytes(raw)
        # File sửa tay ngoài web có thể không phải UTF-8: vẫn mở được trang để sửa.
        content = raw.decode("utf-8", errors="replace")

    effective_sha: str | None = None
    try:
        glossary, _paths = load_effective_glossary(episode_dir, shared_path)
        effective_sha = glossary.sha256() if glossary is not None else None
    except GlossaryError as exc:
        error = str(exc)

    has_translation = (episode_dir / TRANSLATED_FILENAME).is_file()
    translated_sha: str | None = None
    if has_translation:
        try:
            data = json.loads((episode_dir / TRANSLATED_FILENAME).read_text(encoding="utf-8"))
            value = data.get("glossary_sha256") if isinstance(data, dict) else None
            translated_sha = value if isinstance(value, str) else None
        except (OSError, ValueError):
            translated_sha = None  # file hỏng = như file cũ thiếu key

    stale: bool | None = None
    if has_translation and error is None:
        stale = effective_sha != translated_sha

    return GlossaryState(
        exists=exists,
        content=content,
        file_sha256=file_sha,
        shared_path=str(shared_path) if shared_path is not None else None,
        effective_sha256=effective_sha,
        translated_sha256=translated_sha,
        has_translation=has_translation,
        stale=stale,
        has_transcript=(episode_dir / TRANSCRIPT_FILENAME).is_file(),
        error=error,
    )


def validate_glossary_text(text: str, *, source: str = GLOSSARY_FILENAME) -> None:
    if len(text.encode("utf-8")) > MAX_GLOSSARY_BYTES:
        raise GlossaryError(
            f"Glossary quá lớn (tối đa {MAX_GLOSSARY_BYTES // 1024} KB)."
        )
    import yaml

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (dòng {mark.line + 1}, cột {mark.column + 1})" if mark is not None else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise GlossaryError(f"YAML sai cú pháp trong {source}{where}: {problem}") from exc
    parse_glossary(data, source=source)  # None (rỗng/chỉ comment) -> Glossary() rỗng


def save_glossary_text(
    episode_dir: Path,
    text: str,
    *,
    base_sha256: str | None,
    shared_path: Path | None,
) -> GlossaryState:
    episode_dir = Path(episode_dir)
    validate_glossary_text(text)
    path = episode_dir / GLOSSARY_FILENAME
    # Chuẩn hoá xuống dòng cuối; giữ nguyên mọi thứ khác (kể cả comment).
    body = text.replace("\r\n", "\n")
    if body and not body.endswith("\n"):
        body += "\n"
    with _save_lock:
        current = path.read_bytes() if path.is_file() else None
        current_sha = _sha256_bytes(current) if current is not None else None
        if current_sha != base_sha256:
            raise GlossaryConflictError(
                "Glossary đã bị đổi ở nơi khác (tab khác hoặc job). Tải lại trang để xem bản mới."
            )
        if current is not None:
            path.with_name(path.name + BACKUP_SUFFIX).write_bytes(current)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(body.encode("utf-8"))
        os.replace(tmp, path)
    return read_glossary_state(episode_dir, shared_path)


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def redub_request(workspace: Path, episode_dir: Path) -> JobRequest:
    """Request "dịch lại & chạy tiếp" bằng job ``dub``/``playlist`` có sẵn.

    Tập thuộc playlist phải chạy qua ``playlist --items N --recheck`` để dùng
    đúng thư mục tập cũ; ``dub <url>`` sẽ tạo thư mục lẻ mới.
    """
    episode_dir = Path(episode_dir)
    playlist = _read_json_dict(episode_dir.parent / PLAYLIST_FILENAME)
    if playlist is not None and episode_dir.parent != Path(workspace):
        url = playlist.get("url")
        entries = playlist.get("entries")
        if not isinstance(url, str) or not url:
            raise JobValidationError("playlist.json thiếu `url`, không dịch lại được.")
        for entry in entries if isinstance(entries, list) else []:
            rel = entry.get("episode_dir") if isinstance(entry, dict) else None
            if isinstance(rel, str) and Path(rel).name == episode_dir.name:
                index = entry.get("index")
                if isinstance(index, int):
                    return JobRequest(kind="playlist", url=url, items=str(index), recheck=True)
        raise JobValidationError("Không tìm thấy tập này trong playlist.json.")

    meta = _read_json_dict(episode_dir / METADATA_FILENAME)
    url = meta.get("original_url") if meta else None
    if not isinstance(url, str) or not url:
        raise JobValidationError("metadata.json thiếu `original_url`, không dịch lại được.")
    return JobRequest(kind="dub", url=url)

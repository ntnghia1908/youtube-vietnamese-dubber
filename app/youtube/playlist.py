"""Lấy danh sách video của một playlist YouTube (yt-dlp, flat) — Checkpoint 8.

Chỉ lấy metadata phẳng (``extract_flat``), không tải file nào — nhanh và
không tốn băng thông dù playlist có hàng chục tập. Video private/deleted
vẫn được **giữ nguyên** trong danh sách (yt-dlp flat vẫn trả ``id``, title
kiểu ``"[Private video]"``): lọc ở đây sẽ khiến người dùng không biết tập
đó tồn tại, thay vào đó để ``run_dub`` tự fail rõ ràng ở stage download khi
thật sự tải tập đó — xem docs/specs/cp-8.md, mục "Hành vi bắt buộc" #59.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Tái sử dụng logger im lặng của CP1 — không copy lại (một nơi duy nhất
# quyết định yt-dlp không tự in log/error ra stdout/stderr).
from app.youtube.download import _SilentYtdlpLogger


class PlaylistError(RuntimeError):
    """Lỗi lấy metadata playlist từ yt-dlp, hoặc ``playlist.json``/``--items`` sai."""


@dataclass(frozen=True)
class PlaylistEntry:
    index: int  # 1-based, theo thứ tự trong playlist
    video_id: str
    title: str  # "untitled" nếu thiếu
    url: str


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str
    url: str  # URL người dùng truyền vào (không phải URL yt-dlp chuẩn hoá)
    entries: list[PlaylistEntry]


def fetch_playlist(url: str) -> PlaylistInfo:
    """Lấy danh sách video của một playlist, không tải file nào.

    Raise ``PlaylistError`` nếu URL không phải playlist, mạng lỗi, hoặc
    playlist rỗng (không còn video hợp lệ nào sau khi lọc).
    """
    import yt_dlp  # import cục bộ: các lệnh không dùng playlist không cần yt-dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "logger": _SilentYtdlpLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise PlaylistError(
            f"Không lấy được playlist từ URL: {url}\nChi tiết: {exc}"
        ) from exc
    if not info:
        raise PlaylistError(f"Không lấy được playlist từ URL: {url}")
    if info.get("_type") != "playlist":
        raise PlaylistError(
            "URL không phải playlist — dùng `python -m app dub URL` cho một video."
        )

    entries = _parse_entries(info.get("entries"))
    if not entries:
        raise PlaylistError(f"Playlist rỗng (không có video hợp lệ nào): {url}")

    return PlaylistInfo(
        playlist_id=info.get("id") or "",
        title=info.get("title") or "untitled",
        url=url,
        entries=entries,
    )


def _parse_entries(raw_entries: Any) -> list[PlaylistEntry]:
    """Chuyển ``entries`` (generator của yt-dlp) thành list ``PlaylistEntry``.

    Bỏ entry ``None`` (video bị xoá hẳn khỏi hệ thống YouTube — khác video
    chỉ private/deleted nhưng vẫn còn id) hoặc thiếu ``id``. Trùng
    ``video_id`` (playlist bị yt-dlp trả lặp) giữ lần xuất hiện đầu.
    """
    seen_ids: set[str] = set()
    entries: list[PlaylistEntry] = []
    # generator -> list(): duyệt một lần, giữ nguyên thứ tự gốc để suy ra vị
    # trí 1-based khi entry không có "playlist_index".
    for position, raw in enumerate(list(raw_entries or []), start=1):
        if raw is None:
            continue
        video_id = raw.get("id")
        if not video_id:
            continue
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)

        entry_url = raw.get("url")
        if not entry_url or not str(entry_url).startswith("http"):
            entry_url = f"https://www.youtube.com/watch?v={video_id}"

        entries.append(
            PlaylistEntry(
                index=raw.get("playlist_index") or position,
                video_id=video_id,
                title=raw.get("title") or "untitled",
                url=entry_url,
            )
        )
    return entries

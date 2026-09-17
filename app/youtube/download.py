"""Logic tải video YouTube (yt-dlp) — Checkpoint 1.

Chỉ hỗ trợ một video đơn lẻ. Playlist sẽ được xử lý ở checkpoint sau
(xem docs/IMPLEMENTATION_PLAN.md, mục Checkpoint 8).

Resume: nếu ``source.mp4`` của episode đã tồn tại thì không tải lại,
trừ khi gọi với ``force=True``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METADATA_FILENAME = "metadata.json"
SOURCE_FILENAME = "source.mp4"

_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_TITLE_LENGTH = 60

# Một số video vẫn public nhưng với player client mặc định của YouTube chỉ
# trả về storyboard (mhtml) — không có stream A/V nào — khiến yt-dlp báo
# "This video is not available". Client "android" thường vẫn trả được format
# muxed 18 (mp4 360p, h264+aac). Khai báo nhiều client để yt-dlp gộp format
# từ tất cả, nên không làm mất các format chất lượng cao của client mặc định.
_EXTRACTOR_ARGS = {"youtube": {"player_client": ["default", "android"]}}


class VideoDownloadError(RuntimeError):
    """Lỗi rõ ràng khi lấy metadata hoặc tải video thất bại."""


class _SilentYtdlpLogger:
    """Chặn yt-dlp tự in log/error ra stdout/stderr.

    ``quiet=True`` của yt-dlp không chặn hết message ERROR — logger rỗng
    này đảm bảo chỉ có thông báo lỗi do chính module này định dạng được
    hiển thị cho người dùng (acceptance criteria: "error message rõ ràng").
    """

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


@dataclass(frozen=True)
class EpisodeInfo:
    """Kết quả sau khi tải xong — dùng lại ở các checkpoint sau (transcribe, ...)."""

    video_id: str
    title: str
    source_url: str
    episode_dir: Path
    metadata_path: Path
    source_path: Path


def sanitize_filename(name: str, max_length: int = _MAX_TITLE_LENGTH) -> str:
    """Loại bỏ ký tự nguy hiểm cho tên file/thư mục (Windows/macOS/Linux).

    Nếu sau khi làm sạch không còn ký tự chữ/số nào (vd input toàn
    ``/\\:*``), trả về "untitled" thay vì một chuỗi chỉ toàn "_".
    """
    name = _UNSAFE_CHARS_RE.sub("_", name.strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name or not re.search(r"[^\W_]", name, flags=re.UNICODE):
        return "untitled"
    return name[:max_length].rstrip(" .") or "untitled"


def build_episode_dir_name(video_id: str, title: str) -> str:
    """Tên thư mục episode duy nhất và an toàn: ``<video_id>__<title>``."""
    return f"{video_id}__{sanitize_filename(title)}"


def _extract_info(url: str) -> dict[str, Any]:
    """Lấy metadata (không tải file). Raise VideoDownloadError nếu lỗi."""
    import yt_dlp  # import cục bộ: các checkpoint trước không cần yt-dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": _EXTRACTOR_ARGS,
        "logger": _SilentYtdlpLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise VideoDownloadError(
            f"Không lấy được thông tin video từ URL: {url}\nChi tiết: {exc}"
        ) from exc
    if not info:
        raise VideoDownloadError(f"Không lấy được thông tin video từ URL: {url}")
    return info


def _write_metadata(info: dict[str, Any], metadata_path: Path) -> None:
    metadata = {
        "id": info.get("id"),
        "title": info.get("title"),
        "original_url": info.get("webpage_url") or info.get("original_url"),
        "duration_seconds": info.get("duration"),
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "extractor": info.get("extractor"),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _download_source(url: str, source_path: Path) -> None:
    """Tải video về đúng ``source_path``. Raise VideoDownloadError nếu lỗi."""
    import yt_dlp

    ydl_opts = {
        "outtmpl": str(source_path.with_suffix("")) + ".%(ext)s",
        # Pipeline BẮT BUỘC phải có audio track (bước transcribe trích audio
        # từ file này). Không dùng selector trần "mp4": trên YouTube hiện đại
        # nó khớp ngay một DASH stream mp4 *chỉ có video* (vd AV1 1080p) và
        # không bao giờ rơi xuống nhánh bestvideo+bestaudio -> source.mp4 câm.
        # Không có nhánh "/best" trần ở cuối: thà báo lỗi rõ ràng ngay lúc tải
        # còn hơn tạo ra file không audio rồi vỡ ở bước transcribe.
        "format": (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "bestvideo+bestaudio/"
            "best[acodec!=none]"
        ),
        "merge_output_format": "mp4",
        # Hàm này chỉ được gọi khi source.mp4 chưa có HOẶC người dùng yêu cầu
        # --force. Mặc định yt-dlp sẽ bỏ qua file đã tồn tại, khiến --force
        # không thật sự tải lại; bật overwrites để --force đúng như mô tả.
        "overwrites": True,
        "extractor_args": _EXTRACTOR_ARGS,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _SilentYtdlpLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise VideoDownloadError(f"Tải video thất bại: {url}\nChi tiết: {exc}") from exc
    if not source_path.exists():
        raise VideoDownloadError(
            f"yt-dlp chạy xong nhưng không thấy file output tại: {source_path} "
            "(có thể merge_output_format không khớp định dạng tải được)."
        )


def download_video(url: str, workspace_dir: Path, *, force: bool = False) -> EpisodeInfo:
    """Tải một video YouTube, tạo thư mục episode trong ``workspace_dir``.

    - Metadata luôn được lấy lại (chi phí thấp, cần để đặt tên thư mục).
    - ``source.mp4`` được bỏ qua nếu đã tồn tại (resume), trừ khi ``force=True``.
    """
    workspace_dir = Path(workspace_dir)
    info = _extract_info(url)

    video_id = info.get("id")
    title = info.get("title") or "untitled"
    if not video_id:
        raise VideoDownloadError(f"Không xác định được video ID từ URL: {url}")

    episode_dir = workspace_dir / build_episode_dir_name(video_id, title)
    episode_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = episode_dir / METADATA_FILENAME
    _write_metadata(info, metadata_path)

    source_path = episode_dir / SOURCE_FILENAME
    if not source_path.exists() or force:
        _download_source(url, source_path)

    return EpisodeInfo(
        video_id=video_id,
        title=title,
        source_url=url,
        episode_dir=episode_dir,
        metadata_path=metadata_path,
        source_path=source_path,
    )

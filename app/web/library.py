"""Quét workspace để dựng thư viện episode/playlist (thuần stdlib).

Không index/cache: mỗi request quét lại. Lý do: pipeline (tiến trình con)
ghi artifact bất cứ lúc nào, cache sẽ lệch; số đo thời gian quét ghi ở
``docs/decisions/WEB-1.md``.

An toàn: route chỉ nhận ``key`` rồi tra ngược qua kết quả quét
(``find_episode``/``find_playlist``) — không bao giờ ghép path từ input client.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.audio.render import OUTPUT_FILENAME
from app.pipeline.dub import STAGES
from app.pipeline.playlist import PLAYLIST_STATE_FILENAME
from app.synchronization.timing import NORMALIZED_FILENAME
from app.transcription.whisper import TRANSCRIPT_FILENAME
from app.translation.glossary import GLOSSARY_FILENAME
from app.translation.translate import TRANSLATED_FILENAME
from app.tts.synthesize import MANIFEST_FILENAME, TTS_DIRNAME
from app.youtube.download import METADATA_FILENAME, SOURCE_FILENAME

logger = logging.getLogger(__name__)

# Stage -> các artifact (tương đối episode_dir) phải có đủ để coi là "done".
_STAGE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "download": (SOURCE_FILENAME, METADATA_FILENAME),
    "transcribe": (TRANSCRIPT_FILENAME,),
    "translate": (TRANSLATED_FILENAME,),
    "tts": (f"{TTS_DIRNAME}/{MANIFEST_FILENAME}",),
    "normalize": (NORMALIZED_FILENAME,),
    "render": (OUTPUT_FILENAME,),
}


@dataclass(frozen=True)
class EpisodeSummary:
    key: str
    rel_dir: str
    title: str | None
    video_id: str | None
    duration_seconds: float | None
    playlist_key: str | None
    stages: dict[str, str]
    too_long_count: int | None
    has_glossary: bool = False


@dataclass(frozen=True)
class PlaylistSummary:
    key: str
    title: str | None
    url: str | None
    entries: list[dict[str, Any]]
    episodes: list[EpisodeSummary]


def make_key(rel_dir: str) -> str:
    """``"pl/ep"`` -> ``"pl~ep"``: một segment URL, không cần encode ``/``."""
    return rel_dir.replace("/", "~")


def _read_json(path: Path) -> Any | None:
    """Đọc JSON; hỏng/thiếu -> None + cảnh báo (thư viện không được crash vì một file hỏng)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("Không đọc được %s: %s", path, exc)
        return None


def _subdirs(path: Path) -> list[Path]:
    try:
        return sorted(
            (p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        )
    except OSError:
        return []


def _stage_states(episode_dir: Path) -> dict[str, str]:
    return {
        stage: "done" if all((episode_dir / rel).is_file() for rel in _STAGE_ARTIFACTS[stage]) else "missing"
        for stage in STAGES
    }


def _too_long_count(episode_dir: Path) -> int | None:
    data = _read_json(episode_dir / NORMALIZED_FILENAME)
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        return None
    return sum(1 for s in data["segments"] if isinstance(s, dict) and s.get("status") == "too_long")


def _summarize_episode(episode_dir: Path, rel_dir: str, playlist_key: str | None) -> EpisodeSummary:
    meta = _read_json(episode_dir / METADATA_FILENAME)
    if not isinstance(meta, dict):
        meta = {}
    duration = meta.get("duration_seconds")
    return EpisodeSummary(
        key=make_key(rel_dir),
        rel_dir=rel_dir,
        title=meta.get("title") if isinstance(meta.get("title"), str) else None,
        video_id=meta.get("id") if isinstance(meta.get("id"), str) else None,
        duration_seconds=float(duration) if isinstance(duration, (int, float)) else None,
        playlist_key=playlist_key,
        stages=_stage_states(episode_dir),
        too_long_count=_too_long_count(episode_dir),
        has_glossary=(episode_dir / GLOSSARY_FILENAME).is_file(),
    )


def scan_workspace(workspace: Path) -> tuple[list[PlaylistSummary], list[EpisodeSummary]]:
    """Trả ``(playlists, episode lẻ)``. Thư mục lạ và ``.web/`` bị bỏ qua."""
    playlists: list[PlaylistSummary] = []
    singles: list[EpisodeSummary] = []
    for top in _subdirs(workspace):
        state_path = top / PLAYLIST_STATE_FILENAME
        if state_path.is_file():
            state = _read_json(state_path)
            if not isinstance(state, dict):
                state = {}
            raw_entries = state.get("entries")
            entries = [e for e in raw_entries if isinstance(e, dict)] if isinstance(raw_entries, list) else []
            # Tên thư mục tập mở đầu bằng video id nên sắp theo tên ra thứ tự lộn xộn;
            # sắp theo index trong playlist.json, tập không có trong entries xếp cuối.
            index_by_dir = {
                Path(e["episode_dir"]).name: e["index"]
                for e in entries
                if isinstance(e.get("episode_dir"), str) and isinstance(e.get("index"), int)
            }
            episode_dirs = sorted(
                (sub for sub in _subdirs(top) if (sub / METADATA_FILENAME).is_file()),
                key=lambda sub: (index_by_dir.get(sub.name, float("inf")), sub.name),
            )
            episodes = [
                _summarize_episode(sub, f"{top.name}/{sub.name}", make_key(top.name))
                for sub in episode_dirs
            ]
            playlists.append(
                PlaylistSummary(
                    key=make_key(top.name),
                    title=state.get("title") if isinstance(state.get("title"), str) else None,
                    url=state.get("url") if isinstance(state.get("url"), str) else None,
                    entries=entries,
                    episodes=episodes,
                )
            )
        elif (top / METADATA_FILENAME).is_file():
            singles.append(_summarize_episode(top, top.name, None))
    return playlists, singles


def find_episode(workspace: Path, key: str) -> Path | None:
    """Path thư mục episode nếu ``key`` có trong kết quả quét, ngược lại None."""
    playlists, singles = scan_workspace(workspace)
    candidates = list(singles)
    for pl in playlists:
        candidates.extend(pl.episodes)
    for ep in candidates:
        if ep.key == key:
            return workspace / ep.rel_dir
    return None


def find_playlist(workspace: Path, key: str) -> Path | None:
    # Duyệt thư mục thật và so key, không giải mã key ngược thành path.
    for top in _subdirs(workspace):
        if make_key(top.name) == key and (top / PLAYLIST_STATE_FILENAME).is_file():
            return top
    return None


def load_segments(episode_dir: Path) -> list[dict[str, Any]]:
    """Segment chuẩn hóa; ưu tiên normalized > translated > transcript."""
    for filename in (NORMALIZED_FILENAME, TRANSLATED_FILENAME, TRANSCRIPT_FILENAME):
        data = _read_json(episode_dir / filename)
        if isinstance(data, dict) and isinstance(data.get("segments"), list):
            raw = data["segments"]
            break
    else:
        return []

    result: list[dict[str, Any]] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        result.append(
            {
                "id": s.get("id"),
                "start": s.get("start"),
                "end": s.get("end"),
                # transcript.json dùng "text", hai file kia dùng "source_text".
                "source_text": s.get("source_text", s.get("text")),
                "translated_text": s.get("translated_text"),
                "status": s.get("status"),
                "tempo": s.get("tempo"),
            }
        )
    return result

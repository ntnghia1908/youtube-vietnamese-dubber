"""Stage: điều phối pipeline end-to-end (download -> ... -> render, playlist).

Checkpoint 7: ``dub.py`` (``run_dub``) — gọi thẳng các hàm stage của các
checkpoint trước theo đúng thứ tự, tự resume và tự sửa lỗi tạm thời
(dịch lỗi, thiếu audio) trong số vòng giới hạn trước khi render.

Checkpoint 8: ``playlist.py`` (``run_playlist``) — gọi ``run_dub`` tuần tự
cho từng tập của một playlist, ghi trạng thái vào ``playlist.json`` để
resume, một tập lỗi không chặn cả playlist.

Re-export ở đây để dùng được ``from app.pipeline import run_dub,
run_playlist, ...`` thay vì phải nhớ đúng submodule. Cả hai module con đều
chỉ import các dependency nặng (yt-dlp, faster-whisper, Ollama, edge-tts)
**bên trong hàm**, không phải ở cấp module — nên import gói này (và qua đó
cả hai submodule) không tự kéo theo các thư viện đó.
"""

from __future__ import annotations

from app.pipeline.dub import DubError, DubOptions, DubResult, run_dub
from app.pipeline.playlist import (
    EpisodeOutcome,
    PlaylistError,
    PlaylistOptions,
    PlaylistResult,
    parse_item_spec,
    run_playlist,
)

__all__ = [
    "DubError",
    "DubOptions",
    "DubResult",
    "run_dub",
    "EpisodeOutcome",
    "PlaylistError",
    "PlaylistOptions",
    "PlaylistResult",
    "parse_item_spec",
    "run_playlist",
]

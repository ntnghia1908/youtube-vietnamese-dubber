"""Stage: chạy ``run_dub`` tuần tự cho mọi tập của một playlist — Checkpoint 8.

Xử lý (transcribe/translate/tts/render) vẫn tuần tự, KHÔNG song song nhiều
tập (plan §19: MVP tuần tự). SỬA ĐỔI 1 (yêu cầu giữa chừng của user): việc
*tải* video được tách ra một luồng riêng (``threading.Thread``, daemon),
chạy song song với luồng xử lý — tập N+1 được tải trong lúc tập N đang
transcribe/translate/tts/render, để không phí thời gian chờ mạng giữa hai
tập. Luồng chính chỉ chờ đúng lúc cần: trước khi gọi ``run_dub`` cho tập
nào, nó chờ (``threading.Event``) tới khi tập đó tải xong.

Trạng thái từng tập được ghi vào ``playlist.json`` **sau mỗi tập** (atomic,
qua một ``threading.Lock`` dùng chung cho cả hai luồng) để resume: một tập
lỗi (tải lỗi hoặc ``DubError``) không chặn cả playlist (cùng tinh thần C3
của CP3), Ctrl+C giữa tập chỉ mất đúng tập đang chạy dở — xem
docs/decisions/checkpoint-8.md mục A.

Khoá resume là ``video_id`` (không phải vị trí trong playlist): playlist bị
sắp xếp lại giữa hai lần chạy không khiến tập bị coi là "mới" — xem
docs/decisions/checkpoint-7.md A1 và cp-8.md mục "Hành vi bắt buộc" #1.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from app.audio.render import OUTPUT_FILENAME
from app.config import AppConfig
from app.pipeline.dub import DubError, DubOptions, DubResult, run_dub
from app.youtube.download import (
    METADATA_FILENAME,
    SOURCE_FILENAME,
    EpisodeInfo,
    VideoDownloadError,
    build_episode_dir_name,
    download_video,
    load_episode_info,
)
from app.youtube.playlist import PlaylistInfo, fetch_playlist

PLAYLIST_STATE_FILENAME = "playlist.json"

# Field lưu trong playlist.json cho mỗi entry (đúng thứ tự trong ví dụ ở
# spec cp-8.md, mục Artifact) — giữ nguyên khi merge với state cũ, trừ
# index/video_id/title/url luôn lấy theo bản fetch mới nhất. "downloaded"
# (SỬA ĐỔI 1) tách riêng khỏi "status": theo dõi RIÊNG việc tải video đã
# xong chưa, độc lập với kết quả xử lý (transcribe/translate/tts/render).
_CARRIED_FIELDS = (
    "status",
    "downloaded",
    "episode_dir",
    "output_path",
    "error_stage",
    "error",
    "warnings",
    "seconds",
    "updated_at",
)

# Timeout chờ luồng tải khi luồng chính dừng sớm/bị Ctrl+C (SỬA ĐỔI 1: "không
# join vô hạn"). Đường chạy bình thường luồng tải luôn xong trước hoặc ngay
# sau vòng lặp chính (tải nhanh hơn nhiều so với transcribe/translate/tts),
# nên timeout này gần như không bao giờ bị chạm tới trừ khi đang dừng sớm.
_DOWNLOAD_JOIN_TIMEOUT_SECONDS = 5.0


class PlaylistError(RuntimeError):
    """Lỗi lấy playlist, đọc/ghi ``playlist.json``, hoặc cú pháp ``--items`` sai."""


@dataclass(frozen=True)
class PlaylistOptions:
    dub: DubOptions  # workspace = workspace GỐC (chưa có thư mục playlist)
    items: frozenset[int] | None = None  # None = mọi tập
    recheck: bool = False
    max_consecutive_failures: int = 3  # 0 = không bao giờ dừng sớm
    download_only: bool = False  # SỬA ĐỔI 1: chỉ tải, không xử lý


@dataclass
class EpisodeOutcome:
    index: int
    video_id: str
    title: str
    # "completed" | "skipped" | "failed" | "not_run" | "downloaded" (chỉ khi
    # download_only=True — SỬA ĐỔI 1, không lưu vào playlist.json).
    outcome: str
    error_stage: str | None = None
    error: str | None = None
    result: DubResult | None = None


@dataclass
class PlaylistResult:
    playlist_dir: Path
    total: int  # số entry của playlist
    selected: int  # số entry khớp --items
    episodes: list[EpisodeOutcome]  # chỉ entry được chọn, theo index
    aborted: bool  # dừng sớm do max_consecutive_failures


def parse_item_spec(spec: str) -> frozenset[int]:
    """``"1-3,5"`` -> ``{1, 2, 3, 5}``. Raise ``PlaylistError`` nếu sai cú pháp."""
    if not spec or not spec.strip():
        raise PlaylistError(f'--items rỗng: {spec!r}. Ví dụ hợp lệ: "1-3,5".')

    result: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            raise PlaylistError(f'--items có phần tử rỗng: {spec!r}. Ví dụ hợp lệ: "1-3,5".')
        if "-" in part:
            bounds = part.split("-")
            start_str, end_str = (bounds[0].strip(), bounds[1].strip()) if len(bounds) == 2 else ("", "")
            if not start_str.isdigit() or not end_str.isdigit():
                raise PlaylistError(f'--items sai định dạng ở "{part}" (kỳ vọng "A-B", số nguyên >= 1).')
            start, end = int(start_str), int(end_str)
            if start < 1 or end < start:
                raise PlaylistError(f'--items sai ở "{part}": cần 1 <= A <= B (đang là {start}-{end}).')
            result.update(range(start, end + 1))
        else:
            if not part.isdigit():
                raise PlaylistError(f'--items sai định dạng ở "{part}" (kỳ vọng số nguyên >= 1).')
            n = int(part)
            if n < 1:
                raise PlaylistError(f'--items phải >= 1, đang là {n} (ở "{part}").')
            result.add(n)
    return frozenset(result)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    # Cùng mẫu app/synchronization/timing.py:_write_json_atomic — bị kill
    # giữa lúc ghi thì playlist.json cụt không được coi là "đã ghi xong".
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _relative_posix(path: Path, base: Path) -> str:
    return Path(os.path.relpath(path, base)).as_posix()


def _output_exists(playlist_dir: Path, entry: dict[str, Any]) -> bool:
    """True nếu file output của một entry ``completed`` còn tồn tại trên đĩa."""
    output_path = entry.get("output_path")
    if output_path:
        return (playlist_dir / output_path).exists()
    # Fallback hiếm gặp: output_path trống nhưng episode_dir có — dùng đúng
    # tên file OUTPUT_FILENAME của stage render (CP6) thay vì đoán lại.
    episode_dir = entry.get("episode_dir")
    if episode_dir:
        return (playlist_dir / episode_dir / OUTPUT_FILENAME).exists()
    return False


def _load_state(path: Path) -> dict[str, dict[str, Any]] | None:
    """Đọc ``playlist.json`` cũ (nếu có), trả về map ``video_id -> entry``.

    Raise ``PlaylistError`` nếu file tồn tại nhưng hỏng — KHÔNG tự ghi đè,
    để người dùng tự sửa hoặc xoá (mất tiến trình một playlist chạy hàng
    giờ nếu tự động ghi đè oan).
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlaylistError(
            f"{path}: không đọc được (JSON hỏng) — sửa hoặc xoá file rồi chạy lại `playlist`. "
            f"Chi tiết: {exc}"
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise PlaylistError(
            f"{path}: thiếu trường 'entries' hoặc sai định dạng — sửa hoặc xoá file rồi chạy "
            "lại `playlist`."
        )
    by_id: dict[str, dict[str, Any]] = {}
    for raw in data["entries"]:
        if isinstance(raw, dict) and raw.get("video_id"):
            by_id[raw["video_id"]] = raw
    return by_id


def _merge_entries(
    playlist_info: PlaylistInfo,
    old_by_id: dict[str, dict[str, Any]] | None,
    log: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Merge danh sách fetch mới với state cũ theo ``video_id``.

    Tập mới thêm vào playlist -> ``pending``/``downloaded=False``. Tập không
    còn trong playlist (bị xoá/gỡ khỏi playlist) -> bỏ khỏi kết quả, KHÔNG
    xoá thư mục đã tải (người dùng có thể đã xem/giữ lại).
    """
    old_by_id = old_by_id or {}
    merged: list[dict[str, Any]] = []
    for entry in playlist_info.entries:
        old = old_by_id.get(entry.video_id) or {}
        record: dict[str, Any] = {
            "index": entry.index,
            "video_id": entry.video_id,
            "title": entry.title,
            "url": entry.url,
        }
        for field_name in _CARRIED_FIELDS:
            record[field_name] = old.get(field_name)
        if record["status"] is None:
            record["status"] = "pending"
        if record["downloaded"] is None:
            record["downloaded"] = False
        merged.append(record)

    removed = set(old_by_id) - {entry.video_id for entry in playlist_info.entries}
    if removed:
        log(f"[playlist] {len(removed)} tập không còn trong playlist (giữ nguyên thư mục)")
    return merged


def run_playlist(
    url: str,
    config: AppConfig,
    options: PlaylistOptions,
    *,
    log: Callable[[str], None] = print,
) -> PlaylistResult:
    """Fetch playlist rồi gọi ``run_dub`` tuần tự cho từng tập được chọn.

    Luôn fetch lại playlist (tập mới thêm được nhận), merge với
    ``playlist.json`` cũ theo ``video_id``, ghi lại ngay (trước khi chạy
    tập nào) rồi ghi lại **sau mỗi tập** để resume đúng khi bị ngắt giữa
    chừng (Ctrl+C, mất điện, ...).

    SỬA ĐỔI 1: một luồng nền tải video (một tập mỗi lần, tuần tự) chạy song
    song với vòng lặp xử lý ở đây — xem docstring module.
    """
    playlist_info = fetch_playlist(url)

    playlist_dir = options.dub.workspace / build_episode_dir_name(
        playlist_info.playlist_id, playlist_info.title
    )
    playlist_dir.mkdir(parents=True, exist_ok=True)
    state_path = playlist_dir / PLAYLIST_STATE_FILENAME

    old_by_id = _load_state(state_path)
    merged_entries = _merge_entries(playlist_info, old_by_id, log)
    by_index = {entry["index"]: entry for entry in merged_entries}

    state: dict[str, Any] = {
        "playlist_id": playlist_info.playlist_id,
        "title": playlist_info.title,
        "url": url,
        "fetched_at": _now_iso(),
        "entries": merged_entries,
    }
    _write_json_atomic(state_path, state)

    total = len(merged_entries)
    if options.items is None:
        selected_indexes = sorted(by_index)
    else:
        selected_indexes = sorted(i for i in options.items if i in by_index)
        for missing in sorted(i for i in options.items if i not in by_index):
            log(f"[playlist] CẢNH BÁO: --items có {missing} nhưng playlist không có tập này — bỏ qua.")

    width = max(2, len(str(total)))

    # Tính trước tập nào sẽ bị `skipped` (hành vi #4) — dùng chung cho cả
    # luồng tải (không tải tập sẽ skip, đỡ tốn mạng) lẫn vòng lặp xử lý,
    # tính một lần trên state TRƯỚC khi hai luồng chạm vào (tránh lệch nhau).
    skip_flags = {
        idx: (
            by_index[idx]["status"] == "completed"
            and not options.recheck
            and not options.dub.force
            and _output_exists(playlist_dir, by_index[idx])
        )
        for idx in selected_indexes
    }
    to_download_indexes = [idx for idx in selected_indexes if not skip_flags[idx]]

    entries_lock = threading.Lock()
    download_events = {idx: threading.Event() for idx in to_download_indexes}
    download_outcomes: dict[int, EpisodeInfo | BaseException] = {}
    download_seconds: dict[int, float] = {}
    stop_download = threading.Event()

    def _download_one(idx: int) -> EpisodeInfo:
        entry = by_index[idx]
        with entries_lock:
            use_cache = bool(entry.get("downloaded")) and not options.dub.force
            episode_dir_hint = entry.get("episode_dir")
            entry_url = entry["url"]
        if use_cache and episode_dir_hint:
            episode_dir_path = playlist_dir / episode_dir_hint
            if (episode_dir_path / SOURCE_FILENAME).exists() and (
                episode_dir_path / METADATA_FILENAME
            ).exists():
                # Đã tải xong từ lần chạy trước — dựng lại EpisodeInfo từ
                # metadata.json, KHÔNG gọi mạng (SỬA ĐỔI 1).
                return load_episode_info(episode_dir_path, entry_url)
        return download_video(entry_url, playlist_dir, force=options.dub.force)

    def _download_worker() -> None:
        for idx in to_download_indexes:
            if stop_download.is_set():
                break
            ep_tag = f"EP{idx:0{width}d}"
            # Log riêng của luồng tải (tiền tố "[playlist-dl]" khác "[EPxx]"
            # của luồng xử lý): khi chạy thật, thấy dòng này xen giữa log
            # "[EPxx] [dub] ..." của tập đang xử lý là bằng chứng hai luồng
            # chạy song song (SỬA ĐỔI 1, mục "Chạy thật thêm").
            log(f"[playlist-dl] {ep_tag} tải ...")
            started = time.monotonic()
            # Mọi exception (không chỉ VideoDownloadError) đều phải được lưu và
            # event luôn được set trong finally: nếu luồng tải chết lặng lẽ vì
            # một lỗi lạ (OSError khi ghi playlist.json, bug...), luồng chính
            # sẽ chờ event của tập đó mãi mãi.
            try:
                try:
                    episode_info = _download_one(idx)
                except VideoDownloadError as exc:
                    elapsed = time.monotonic() - started
                    with entries_lock:
                        download_seconds[idx] = elapsed
                        download_outcomes[idx] = exc
                        entry = by_index[idx]
                        entry["downloaded"] = False
                        entry["updated_at"] = _now_iso()
                        _write_json_atomic(state_path, state)
                    log(f"[playlist-dl] {ep_tag} LỖI ({elapsed:.1f}s): {exc}")
                    continue
                elapsed = time.monotonic() - started
                with entries_lock:
                    download_seconds[idx] = elapsed
                    download_outcomes[idx] = episode_info
                    entry = by_index[idx]
                    entry["downloaded"] = True
                    # Ghi episode_dir NGAY khi tải xong, trước khi xử lý (SỬA ĐỔI 1)
                    # — nếu Ctrl+C ngay sau đó, lần chạy sau biết thư mục đã có.
                    entry["episode_dir"] = _relative_posix(episode_info.episode_dir, playlist_dir)
                    entry["updated_at"] = _now_iso()
                    _write_json_atomic(state_path, state)
                log(f"[playlist-dl] {ep_tag} xong ({elapsed:.1f}s)")
            except BaseException as exc:  # noqa: BLE001 — chuyển sang luồng chính raise lại
                download_outcomes[idx] = exc
                return
            finally:
                download_events[idx].set()

    download_thread: threading.Thread | None = None
    if to_download_indexes:
        download_thread = threading.Thread(target=_download_worker, daemon=True)
        download_thread.start()

    episodes: list[EpisodeOutcome] = []
    aborted = False
    consecutive_failures = 0

    def _register_failure(
        entry: dict[str, Any], ep_tag: str, stage: str, error_message: str, seconds: float
    ) -> None:
        nonlocal aborted, consecutive_failures
        with entries_lock:
            entry["status"] = "failed"
            entry["output_path"] = None
            entry["error_stage"] = stage
            entry["error"] = error_message
            entry["warnings"] = None
            entry["seconds"] = round(seconds, 1)
            entry["updated_at"] = _now_iso()
            _write_json_atomic(state_path, state)
        log(f"[{ep_tag}] LỖI ở stage {stage} — tiếp tục tập sau")
        episodes.append(
            EpisodeOutcome(
                index=entry["index"], video_id=entry["video_id"], title=entry["title"],
                outcome="failed", error_stage=stage, error=error_message,
            )
        )
        # Lỗi tải KHÔNG tính vào (cũng không reset) bộ đếm lỗi liên tiếp: nó
        # chỉ tốn vài giây, còn bộ đếm để chặn lỗi hệ thống (Ollama tắt...)
        # làm phí hàng giờ xử lý. Playlist thật có 9 video Private liền nhau
        # (EP13–21) — tính vào thì chạy cả playlist sẽ dừng ở EP15, không bao
        # giờ tới EP22.
        if stage == "download":
            return
        consecutive_failures += 1
        if options.max_consecutive_failures > 0 and consecutive_failures >= options.max_consecutive_failures:
            log(
                f"[playlist] {consecutive_failures} tập lỗi liên tiếp — dừng "
                "(kiểm tra Ollama/mạng/ffmpeg rồi chạy lại)"
            )
            aborted = True
            stop_download.set()

    try:
        for idx in selected_indexes:
            entry = by_index[idx]
            ep_tag = f"EP{idx:0{width}d}"

            if aborted:
                episodes.append(
                    EpisodeOutcome(
                        index=idx, video_id=entry["video_id"], title=entry["title"], outcome="not_run"
                    )
                )
                continue

            if skip_flags[idx]:
                episodes.append(
                    EpisodeOutcome(
                        index=idx, video_id=entry["video_id"], title=entry["title"], outcome="skipped"
                    )
                )
                continue

            log(f"[{ep_tag}/{total}] {entry['title']} ...")

            # Chờ theo nhịp 0.5s thay vì wait() không timeout: Ctrl+C luôn ngắt
            # được ngay, kể cả trên Windows.
            while not download_events[idx].wait(0.5):
                pass
            download_outcome = download_outcomes[idx]

            if isinstance(download_outcome, VideoDownloadError):
                _register_failure(
                    entry, ep_tag, "download", f"[download] {download_outcome}",
                    download_seconds.get(idx, 0.0),
                )
                continue
            if isinstance(download_outcome, BaseException):
                # Lỗi lạ ở luồng tải = bug, phải nổi lên (hành vi #8) thay vì
                # bị ghi thành "failed" như một video tải hỏng.
                raise download_outcome

            episode_info = download_outcome

            if options.download_only:
                consecutive_failures = 0
                episodes.append(
                    EpisodeOutcome(
                        index=idx, video_id=entry["video_id"], title=entry["title"], outcome="downloaded"
                    )
                )
                continue

            def _ep_log(message: str, tag: str = ep_tag) -> None:
                log(f"[{tag}] {message}")

            dub_options = replace(options.dub, workspace=playlist_dir)
            started = time.monotonic()
            try:
                result = run_dub(entry["url"], config, dub_options, log=_ep_log, episode=episode_info)
            except DubError as exc:
                elapsed = download_seconds.get(idx, 0.0) + (time.monotonic() - started)
                _register_failure(entry, ep_tag, exc.stage, str(exc), elapsed)
                continue

            # Thành công: reset bộ đếm lỗi liên tiếp (#11 — chỉ completed mới reset).
            consecutive_failures = 0
            with entries_lock:
                entry["status"] = "completed"
                entry["episode_dir"] = _relative_posix(result.episode_dir, playlist_dir)
                entry["output_path"] = _relative_posix(result.output_path, playlist_dir)
                entry["error_stage"] = None
                entry["error"] = None
                entry["warnings"] = {
                    "translate_failed_ids": list(result.translate_failed_ids),
                    "missing_ids": list(result.missing_ids),
                    "too_long_ids": list(result.too_long_ids),
                }
                entry["seconds"] = round(
                    download_seconds.get(idx, 0.0) + sum(result.stage_seconds.values()), 1
                )
                entry["updated_at"] = _now_iso()
                _write_json_atomic(state_path, state)
            episodes.append(
                EpisodeOutcome(
                    index=idx, video_id=entry["video_id"], title=entry["title"],
                    outcome="completed", result=result,
                )
            )
    finally:
        # Dừng sớm/Ctrl+C: báo luồng tải dừng sau tập đang tải, KHÔNG join vô
        # hạn (daemon thread — timeout chỉ để tránh log dở dang, không phải
        # để chờ mạng treo).
        stop_download.set()
        if download_thread is not None:
            download_thread.join(timeout=_DOWNLOAD_JOIN_TIMEOUT_SECONDS)

    return PlaylistResult(
        playlist_dir=playlist_dir,
        total=total,
        selected=len(selected_indexes),
        episodes=episodes,
        aborted=aborted,
    )

"""Hàng đợi job cho Web UI: chạy đúng lệnh CLI ``dub``/``playlist`` ở tiến trình con.

Thiết kế (ADR-001 4.3):
- Job chạy ``[python, -m, app, <kind>, <url>, ...]`` chứ không gọi ``run_dub``
  trong tiến trình server: kill an toàn, một job treo/crash không kéo server
  chết, và web dùng đúng đường chạy đã được kiểm chứng của CLI.
- Tối đa ``max_jobs`` worker (trần 2, ADR-001 mục 10), FIFO nhưng job có target
  trùng job đang chạy phải chờ (không bao giờ hai writer trên cùng một thư mục),
  job không xung đột phía sau được vượt lên.
- Trạng thái nằm trên đĩa (``<workspace>/.web/jobs/<id>.json`` + ``.log``),
  ghi atomic, nên server restart không mất lịch sử. Pipeline resume được nên
  job bị ngắt chạy lại (retry) sẽ SKIP phần đã xong.

Thuần stdlib.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.pipeline.playlist import PlaylistError, parse_item_spec

JOB_KINDS = ("dub", "playlist", "glossary")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "interrupted")
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "interrupted")

WEB_DIRNAME = ".web"
JOBS_DIRNAME = "jobs"

# Thời gian chờ SIGTERM có hiệu lực trước khi SIGKILL (giây).
CANCEL_GRACE_SECONDS = 10.0

_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
)
_LANG_RE = re.compile(r"^[a-z]{2,3}$")
# "[EP02] [dub] (3/6) translate xong (12.0s)" — `[dub]` log ở app/pipeline/dub.py
# (_log_start/_log_done), tiền tố `[EPnn]` thêm bởi app/pipeline/playlist.py.
_PROGRESS_RE = re.compile(
    r"^(?:\[(?P<episode>EP\d+)\]\s+)?\[dub\]\s+\((?P<index>\d+)/(?P<total>\d+)\)\s+"
    r"(?P<stage>[a-z]+)\s+(?P<state>\.\.\.|xong|SKIP)(?:\s|$)"
)
_STATE_MAP = {"...": "running", "xong": "done", "SKIP": "skipped"}


class JobValidationError(ValueError):
    """Request job không hợp lệ; thông điệp tiếng Việt, hiển thị thẳng cho người dùng."""


@dataclass
class JobRequest:
    kind: str
    url: str = ""
    source_lang: str | None = None
    items: str | None = None
    force: bool = False
    download_only: bool = False
    recheck: bool = False  # chỉ playlist -> --recheck
    episode_key: str | None = None  # bắt buộc với glossary, cấm với dub/playlist


def _video_id(url: str) -> str:
    """id video từ ``v=``, ``youtu.be/<id>`` hoặc ``/shorts/<id>``; không có -> chuỗi rỗng."""
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
    except ValueError:
        return ""
    path_parts = [p for p in parsed.path.split("/") if p]
    if host == "youtu.be":
        return path_parts[0] if path_parts else ""
    if len(path_parts) >= 2 and path_parts[0] == "shorts":
        return path_parts[1]
    return parse_qs(parsed.query).get("v", [""])[0]


def job_targets(
    kind: str,
    request: dict[str, Any],
    command: list[str],
    *,
    workspace: Path | None = None,
    index_map: Mapping[int, str] | None = None,
) -> frozenset[str]:
    """Các "đích" job sẽ ghi vào; xung đột xét bằng ``targets_conflict``.

    Đích: ``video:<id>`` (một tập/video), ``in-playlist:<L>`` (job chỉ đụng
    vài tập của playlist L, chỉ để chạm với job cả playlist), ``playlist:<L>``
    (cả playlist). Bảo thủ có chủ ý: job ``dub`` video X và tập X trong một
    playlist coi là xung đột dù thư mục khác nhau. Thuần, không đọc đĩa:
    ``index_map`` (index -> video_id, từ ``playlist.json``) do bên gọi đưa vào.
    """
    if kind == "dub":
        vid = _video_id(request.get("url") or "")
        return frozenset({f"video:{vid}"}) if vid else frozenset()
    if kind == "playlist":
        query = parse_qs(urlparse((request.get("url") or "").strip()).query)
        list_id = query.get("list", [""])[0]
        if not list_id:
            return frozenset()
        whole = frozenset({f"playlist:{list_id}"})
        items = request.get("items")
        if not items or not index_map:
            return whole
        try:
            indexes = parse_item_spec(items)
        except PlaylistError:
            return whole
        video_ids = [index_map.get(i) for i in indexes]
        if not indexes or not all(video_ids):
            return whole  # có index không map được -> bảo thủ, khoá cả playlist
        return frozenset({f"video:{v}" for v in video_ids} | {f"in-playlist:{list_id}"})
    if kind == "glossary":
        # build_command đặt thư mục tập ở command[4]. Tên thư mục: <id>__<title>.
        episode_dir = Path(command[4])
        targets = {f"video:{episode_dir.name.split('__', 1)[0]}"}
        parent = episode_dir.parent
        # Tập nằm trong playlist: thư mục cha khác workspace. Không biết workspace
        # (gọi thuần) thì dựa vào tên cha có dạng "<id>__<title>".
        in_playlist = parent != workspace if workspace is not None else "__" in parent.name
        if in_playlist:
            targets.add(f"in-playlist:{parent.name.split('__', 1)[0]}")
        return frozenset(targets)
    return frozenset()


def targets_conflict(a: frozenset[str], b: frozenset[str]) -> bool:
    """Hai job không được chạy cùng lúc: giao nhau, hoặc một bên khoá cả playlist L
    còn bên kia đụng playlist L (cả playlist hoặc vài tập)."""
    # `in-playlist:` chỉ là nhãn để chạm với `playlist:`, hai bên cùng nhãn không phải xung đột.
    if any(not t.startswith("in-playlist:") for t in a & b):
        return True
    for mine, other in ((a, b), (b, a)):
        for t in mine:
            if t.startswith("playlist:"):
                list_id = t.split(":", 1)[1]
                if f"playlist:{list_id}" in other or f"in-playlist:{list_id}" in other:
                    return True
    return False


def read_playlist_index_map(workspace: Path, list_id: str) -> dict[int, str]:
    """index -> video_id từ ``<workspace>/<list_id>__*/playlist.json``; lỗi -> ``{}``
    (bảo thủ: job sẽ khoá cả playlist)."""
    for state_path in sorted(workspace.glob(f"{list_id}__*/playlist.json")):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return {
                int(e["index"]): str(e["video_id"])
                for e in data["entries"]
                if isinstance(e, dict) and e.get("video_id") and e.get("index") is not None
            }
        except (OSError, ValueError, KeyError, TypeError):
            return {}
    return {}


def validate_request(req: JobRequest) -> None:
    """Raise ``JobValidationError`` nếu request sai. Chạy TRƯỚC khi tạo job."""
    if req.kind not in JOB_KINDS:
        raise JobValidationError(f"Loại job không hợp lệ: {req.kind!r}. Hợp lệ: dub, playlist, glossary.")

    if req.kind == "glossary":
        # Nháp glossary chỉ nhận episode_key; server tự tra path (client không gửi path).
        if not req.episode_key:
            raise JobValidationError("Job glossary cần `episode_key`.")
        for name, value in (
            ("url", (req.url or "").strip()),
            ("source_lang", req.source_lang),
            ("items", req.items),
            ("force", req.force),
            ("download_only", req.download_only),
            ("recheck", req.recheck),
        ):
            if value:
                raise JobValidationError(f"Job glossary không nhận `{name}`.")
        return
    if req.episode_key:
        raise JobValidationError("`episode_key` chỉ dùng cho job glossary.")
    if req.recheck and req.kind != "playlist":
        raise JobValidationError("`recheck` chỉ dùng cho job playlist.")

    url = (req.url or "").strip()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        raise JobValidationError("URL không hợp lệ.") from None
    if parsed.scheme not in ("http", "https") or host not in _YOUTUBE_HOSTS:
        raise JobValidationError(
            "URL phải là link YouTube (http/https, youtube.com hoặc youtu.be)."
        )

    query = parse_qs(parsed.query)
    if req.kind == "playlist":
        if not query.get("list", [""])[0]:
            raise JobValidationError("URL playlist phải có tham số `list=`.")
    else:
        if not _video_id(url):
            raise JobValidationError(
                "URL video phải có `v=<id>`, dạng youtu.be/<id> hoặc /shorts/<id>."
            )

    if req.source_lang is not None and not _LANG_RE.match(req.source_lang):
        raise JobValidationError(
            f"Mã ngôn ngữ gốc không hợp lệ: {req.source_lang!r} (vd zh, en, ja)."
        )

    if req.kind != "playlist":
        if req.items:
            raise JobValidationError("`items` chỉ dùng cho job playlist.")
        if req.download_only:
            raise JobValidationError("`download_only` chỉ dùng cho job playlist.")
    elif req.items:
        try:
            parse_item_spec(req.items)
        except PlaylistError as exc:
            raise JobValidationError(f"`items` sai cú pháp: {exc}") from exc


def build_command(
    req: JobRequest,
    *,
    workspace: Path,
    config_path: Path | None,
    python: str = sys.executable,
    episode_dir: Path | None = None,
) -> list[str]:
    """Lệnh CLI tương ứng với request (list args, không qua shell)."""
    if req.kind == "glossary":
        # `glossary` không có --workspace; không bao giờ --force (không ghi đè glossary người dùng).
        if episode_dir is None:
            raise JobValidationError("Job glossary cần thư mục episode.")
        cmd = [python, "-m", "app", "glossary", str(episode_dir)]
        if config_path is not None:
            cmd += ["--config", str(config_path)]
        return cmd
    cmd = [python, "-m", "app", req.kind, req.url.strip(), "--workspace", str(workspace)]
    if config_path is not None:
        cmd += ["--config", str(config_path)]
    if req.items:
        cmd += ["--items", req.items]
    if req.source_lang:
        cmd += ["--source-lang", req.source_lang]
    if req.force:
        cmd.append("--force")
    if req.download_only:
        cmd.append("--download-only")
    if req.recheck:
        cmd.append("--recheck")
    return cmd


def parse_progress(line: str) -> dict[str, Any] | None:
    """Dòng log ``[dub] (i/n) stage ...|xong|SKIP`` -> dict tiến độ; dòng khác -> None."""
    match = _PROGRESS_RE.match(line.strip())
    if not match:
        return None
    return {
        "episode": match.group("episode"),
        "index": int(match.group("index")),
        "total": int(match.group("total")),
        "stage": match.group("stage"),
        "state": _STATE_MAP[match.group("state")],
    }


def _default_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # tồn tại nhưng không phải của mình
    except OSError:
        return False
    return True


def _default_pid_is_pipeline(pid: int) -> bool:
    """pid còn là pipeline do web chạy, không phải tiến trình lạ tái dùng pid.

    Có /proc thì đòi cmdline chứa ``-m app``; không có thì dựa vào việc pipeline
    là session leader (``start_new_session``) nên ``getpgid(pid) == pid``.
    """
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
        return "-m app" in cmdline
    except OSError:
        pass
    try:
        return os.getpgid(pid) == pid
    except (OSError, AttributeError):
        return False


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


_id_lock = threading.Lock()
_id_last_second = ""
_id_counter = 0


def _new_job_id() -> str:
    """``YYYYMMDD-HHMMSS-<6 hex>``; 2 hex đầu là bộ đếm trong cùng giây.

    Có bộ đếm vì id được dùng để sắp xếp (list mới nhất trước, thứ tự FIFO sau
    restart): hai job gửi trong cùng một giây mà chỉ có hậu tố ngẫu nhiên thì
    thứ tự bị đảo ngẫu nhiên.
    """
    global _id_last_second, _id_counter
    second = f"{datetime.now():%Y%m%d-%H%M%S}"
    with _id_lock:
        _id_counter = _id_counter + 1 if second == _id_last_second else 0
        _id_last_second = second
        counter = min(_id_counter, 0xFF)
    return f"{second}-{counter:02x}{secrets.token_hex(2)}"


class JobManager:
    """Hàng đợi job FIFO tránh xung đột target, tối đa ``max_jobs`` worker, trạng thái lưu trên đĩa."""

    def __init__(
        self,
        workspace: Path,
        config_path: Path | None,
        *,
        max_jobs: int = 1,
        episode_workers: int = 1,
        python: str = sys.executable,
        popen: Callable[..., Any] = subprocess.Popen,
        killpg: Callable[[int, int], None] | None = None,
        cancel_grace_seconds: float = CANCEL_GRACE_SECONDS,
        pid_alive: Callable[[int], bool] = _default_pid_alive,
        pid_is_pipeline: Callable[[int], bool] = _default_pid_is_pipeline,
    ) -> None:
        self._workspace = Path(workspace)
        self._config_path = config_path
        self._max_jobs = max(1, int(max_jobs))
        self._episode_workers = max(1, int(episode_workers))
        self._python = python
        self._popen = popen
        # killpg inject để test không bao giờ gửi tín hiệu thật tới pid giả.
        self._killpg = killpg if killpg is not None else getattr(os, "killpg", None)
        self._grace = cancel_grace_seconds
        self._pid_alive = pid_alive
        self._pid_is_pipeline = pid_is_pipeline

        self._jobs_dir = self._workspace / WEB_DIRNAME / JOBS_DIRNAME
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._queue: deque[str] = deque()
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        # job_id -> (proc hoặc None khi chưa spawn, targets, slots). Đăng ký ngay
        # khi lấy khỏi queue để hai worker không cùng lấy hai job xung đột.
        # slots = số run_dub job đó có thể chạy đồng thời (CP9-C): dub/glossary
        # 1, playlist = số tập song song; tổng slots luôn <= max_jobs.
        self._running: dict[str, tuple[Any | None, frozenset[str], int]] = {}
        self._cancel_requested: set[str] = set()

    # ---- đường dẫn / lưu trữ -------------------------------------------

    def _json_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def log_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.log"

    def _write(self, job: dict[str, Any]) -> None:
        """Ghi atomic (tmp + replace): bị kill giữa chừng không để lại JSON cụt."""
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        path = self._json_path(job["id"])
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _read(self, job_id: str) -> dict[str, Any] | None:
        # job_id đến từ URL: chỉ nhận đúng dạng id do mình sinh, chặn traversal.
        if not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", job_id):
            return None
        try:
            return json.loads(self._json_path(job_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ---- vòng đời ------------------------------------------------------

    def start(self) -> None:
        """Recovery rồi bật worker. ``running`` mồ côi -> ``interrupted``; ``queued`` chạy tiếp."""
        with self._lock:
            queued: list[dict[str, Any]] = []
            for job in self.list():
                if job["status"] == "running":
                    # Dọn pipeline mồ côi TRƯỚC khi bật worker: nếu không, job
                    # queued kế tiếp chạy song song với nó (server bị kill -9
                    # không kill được tiến trình con).
                    self._reap_orphan(job)
                    job["pid"] = None
                    job["status"] = "interrupted"
                    job["finished_at"] = _now_iso()
                    self._write(job)
                elif job["status"] == "queued":
                    queued.append(job)
            for job in sorted(queued, key=lambda j: (j.get("created_at") or "", j["id"])):
                self._queue.append(job["id"])
        self._stop_event.clear()
        self._threads = [
            threading.Thread(target=self._worker_loop, name=f"job-worker-{i}", daemon=True)
            for i in range(self._max_jobs)
        ]
        for thread in self._threads:
            thread.start()

    def _reap_orphan(self, job: dict[str, Any]) -> None:
        pid = job.get("pid")
        if not isinstance(pid, int) or not self._pid_alive(pid):
            return
        if not self._pid_is_pipeline(pid):
            return  # pid đã bị tiến trình khác tái dùng: tuyệt đối không kill
        with self.log_path(job["id"]).open("a", encoding="utf-8") as fh:
            if self._killpg is None:
                fh.write(f"[web] CẢNH BÁO: tiến trình mồ côi pid={pid} còn chạy, không tự dừng được trên hệ điều hành này\n")
                return
            fh.write(f"[web] dừng tiến trình mồ côi pid={pid} khi khởi động lại\n")
        self._signal_pid(pid, signal.SIGTERM)
        deadline = time.monotonic() + self._grace
        while time.monotonic() < deadline and self._pid_alive(pid):
            time.sleep(0.05)
        if self._pid_alive(pid):
            self._signal_pid(pid, signal.SIGKILL)

    def _signal_pid(self, pid: int, sig: int) -> None:
        try:
            self._killpg(pid, sig)  # type: ignore[misc]
        except OSError:
            pass

    def stop(self) -> None:
        self._stop_event.set()
        with self._cond:
            procs = [proc for proc, _, _ in self._running.values() if proc is not None]
            self._cond.notify_all()
        for proc in procs:
            self._signal(proc, force=True)
        for thread in self._threads:
            thread.join(timeout=15)
        self._threads = []

    # ---- API ------------------------------------------------------------

    def submit(self, req: JobRequest) -> dict[str, Any]:
        return self._submit(req, retry_of=None)

    def _submit(self, req: JobRequest, retry_of: str | None) -> dict[str, Any]:
        validate_request(req)
        req = JobRequest(**{**asdict(req), "url": (req.url or "").strip()})
        episode_dir = self._resolve_glossary_episode(req) if req.kind == "glossary" else None
        job = {
            "id": _new_job_id(),
            "kind": req.kind,
            "request": {k: v for k, v in asdict(req).items() if k != "kind"},
            "command": build_command(
                req,
                workspace=self._workspace,
                config_path=self._config_path,
                python=self._python,
                episode_dir=episode_dir,
            ),
            "status": "queued",
            "exit_code": None,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
            "progress": None,
            "retry_of": retry_of,
            "pid": None,
        }
        with self._cond:
            self._write(job)
            self._queue.append(job["id"])
            self._cond.notify_all()
        return job

    def _resolve_glossary_episode(self, req: JobRequest) -> Path:
        """Tra path tập từ ``episode_key`` lúc submit (retry cũng đi qua đây nên kiểm lại)."""
        from app.translation.glossary import GLOSSARY_FILENAME
        from app.transcription.whisper import TRANSCRIPT_FILENAME
        from app.web import library

        episode_dir = library.find_episode(self._workspace, req.episode_key or "")
        if episode_dir is None:
            raise JobValidationError("Không có episode này.")
        if not (episode_dir / TRANSCRIPT_FILENAME).is_file():
            raise JobValidationError("Tập chưa có transcript.json, chưa tạo nháp glossary được.")
        if (episode_dir / GLOSSARY_FILENAME).exists():
            raise JobValidationError("Tập đã có glossary — sửa ở editor, không tạo nháp đè.")
        return episode_dir

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = []
            if self._jobs_dir.is_dir():
                for path in self._jobs_dir.glob("*.json"):
                    job = self._read(path.stem)
                    if job is not None:
                        jobs.append(job)
        return sorted(jobs, key=lambda j: j["id"], reverse=True)

    def cancel(self, job_id: str) -> dict[str, Any]:
        """queued -> cancelled ngay; running -> SIGTERM nhóm tiến trình. Job đã kết thúc: không đổi."""
        with self._cond:
            job = self._read(job_id)
            if job is None:
                raise KeyError(job_id)
            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["finished_at"] = _now_iso()
                self._write(job)
                return job
            if job["status"] != "running":
                return job
            self._cancel_requested.add(job_id)
            entry = self._running.get(job_id)
            proc = entry[0] if entry is not None else None
        if proc is not None:
            self._signal(proc, force=False)
            threading.Thread(target=self._escalate, args=(proc,), daemon=True).start()
        return self.get(job_id) or job

    def retry(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        req = JobRequest(kind=job["kind"], **job["request"])
        return self._submit(req, retry_of=job_id)

    # ---- tín hiệu -------------------------------------------------------

    def _signal(self, proc: Any, *, force: bool) -> None:
        """Dừng cả nhóm tiến trình (ffmpeg/yt-dlp con của pipeline cũng chết theo)."""
        try:
            if self._killpg is not None and getattr(proc, "pid", None) is not None:
                self._killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                proc.kill()
            else:
                proc.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            pass  # đã thoát

    def _escalate(self, proc: Any) -> None:
        """Hết hạn chờ SIGTERM mà chưa thoát -> SIGKILL."""
        try:
            proc.wait(timeout=self._grace)
        except subprocess.TimeoutExpired:
            self._signal(proc, force=True)

    # ---- worker ----------------------------------------------------------

    def _targets_of(self, job: dict[str, Any]) -> frozenset[str]:
        index_map = None
        request = job["request"]
        if job["kind"] == "playlist" and request.get("items"):
            list_id = parse_qs(urlparse((request.get("url") or "").strip()).query).get("list", [""])[0]
            if list_id:
                index_map = read_playlist_index_map(self._workspace, list_id)
        return job_targets(
            job["kind"], request, job["command"], workspace=self._workspace, index_map=index_map
        )

    def _slots_for(self, job: dict[str, Any], free_slots: int) -> int:
        """Số slot job chiếm. Không bao giờ chờ đủ slot: còn 1 slot thì playlist chạy 1 tập."""
        if job["kind"] != "playlist":
            return 1
        slots = min(self._episode_workers, free_slots)
        items = (job["request"].get("items") or "").strip()
        if items:
            try:
                slots = min(slots, len(parse_item_spec(items)))
            except PlaylistError:
                pass  # spec lỗi: coi như không biết số tập
        return max(1, slots)

    def _next_queued(self) -> str | None:
        with self._cond:
            while not self._stop_event.is_set():
                busy = [targets for _, targets, _ in self._running.values()]
                free_slots = self._max_jobs - sum(slots for _, _, slots in self._running.values())
                if free_slots < 1:
                    self._cond.wait(timeout=1.0)
                    continue
                for job_id in list(self._queue):
                    job = self._read(job_id)
                    if job is None or job["status"] != "queued":
                        self._queue.remove(job_id)  # đã bị hủy khi còn queued
                        continue
                    targets = self._targets_of(job)
                    if any(targets_conflict(targets, b) for b in busy):
                        continue  # xung đột: giữ nguyên vị trí, job sau được vượt lên
                    self._queue.remove(job_id)
                    slots = self._slots_for(job, free_slots)
                    if job["kind"] == "playlist":
                        # Ghi lệnh TRƯỚC khi spawn để log/UI thấy đúng lệnh đã chạy.
                        job["command"] = [*job["command"], "--episode-workers", str(slots)]
                        self._write(job)
                    self._running[job_id] = (None, targets, slots)
                    return job_id
                self._cond.wait(timeout=1.0)
        return None

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            job_id = self._next_queued()
            if job_id is None:
                return
            try:
                self._run_job(job_id)
            except Exception as exc:  # worker không được chết vì một job lỗi
                with self._lock:
                    job = self._read(job_id)
                    if job is not None and job["status"] == "running":
                        job["status"] = "failed"
                        job["finished_at"] = _now_iso()
                        self._write(job)
                    with self.log_path(job_id).open("a", encoding="utf-8") as fh:
                        fh.write(f"[web] LỖI nội bộ khi chạy job: {exc}\n")
            finally:
                # Gỡ SAU khi trạng thái đã ghi xong, để job xung đột đang chờ
                # không chạy khi job này còn ghi dở.
                self._unregister(job_id)

    def _unregister(self, job_id: str) -> None:
        """Gỡ job khỏi ``_running`` rồi đánh thức worker đang chờ job xung đột."""
        with self._cond:
            self._running.pop(job_id, None)
            self._cond.notify_all()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._read(job_id)
            if job is None or job["status"] != "queued":
                return
            job["status"] = "running"
            job["started_at"] = _now_iso()
            self._write(job)

        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        extra: dict[str, Any] = {}
        if os.name == "nt":
            extra["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            extra["start_new_session"] = True

        log_file = self.log_path(job_id).open("a", encoding="utf-8")
        proc = None
        try:
            try:
                proc = self._popen(
                    job["command"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=env,
                    cwd=str(Path.cwd()),
                    **extra,
                )
            except OSError as exc:
                log_file.write(f"[web] Không khởi chạy được tiến trình: {exc}\n")
                log_file.flush()
                self._finish(job_id, "failed", None)
                return

            with self._lock:
                if job_id in self._running:
                    self._running[job_id] = (proc, *self._running[job_id][1:])
                current = self._read(job_id)
                if current is not None:
                    current["pid"] = getattr(proc, "pid", None)
                    self._write(current)
                cancel_now = job_id in self._cancel_requested
            if cancel_now or self._stop_event.is_set():
                self._signal(proc, force=False)
                threading.Thread(target=self._escalate, args=(proc,), daemon=True).start()

            last_progress = job.get("progress")
            for line in proc.stdout:
                if not line.endswith("\n"):
                    line += "\n"
                log_file.write(line)
                log_file.flush()
                progress = parse_progress(line)
                if progress is not None and progress != last_progress:
                    last_progress = progress
                    with self._lock:
                        current = self._read(job_id)
                        if current is not None:
                            current["progress"] = progress
                            self._write(current)
            exit_code = proc.wait()
        finally:
            log_file.close()

        with self._lock:
            cancelled = job_id in self._cancel_requested
            self._cancel_requested.discard(job_id)
        if cancelled:
            status = "cancelled"
        elif self._stop_event.is_set() and exit_code != 0:
            status = "interrupted"
        else:
            status = "completed" if exit_code == 0 else "failed"
        self._finish(job_id, status, exit_code)

    def _finish(self, job_id: str, status: str, exit_code: int | None) -> None:
        with self._lock:
            job = self._read(job_id)
            if job is None:
                return
            job["status"] = status
            job["exit_code"] = exit_code
            job["pid"] = None
            job["finished_at"] = _now_iso()
            self._write(job)


def read_log_lines(
    path: Path, offset: int, *, final: bool
) -> tuple[list[tuple[int, str]], int]:
    """Đọc các dòng log hoàn chỉnh từ byte ``offset``.

    Trả ``([(offset_sau_dòng, text)], offset_mới)``. Dòng dở (chưa có ``\\n``)
    chỉ được trả khi ``final`` (job đã kết thúc) — tránh cắt đôi một dòng
    giữa hai lần poll.
    """
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except OSError:
        return [], offset
    lines: list[tuple[int, str]] = []
    pos = offset
    while data:
        nl = data.find(b"\n")
        if nl < 0:
            if final:
                pos += len(data)
                lines.append((pos, data.decode("utf-8", errors="replace")))
            break
        chunk, data = data[: nl + 1], data[nl + 1 :]
        pos += len(chunk)
        lines.append((pos, chunk.decode("utf-8", errors="replace").rstrip("\r\n")))
    return lines, pos

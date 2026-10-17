"""FastAPI app của Web UI local (WEB-1).

Chỉ file này import fastapi/uvicorn; ``app.cli`` chỉ import nó bên trong lệnh
``web`` để các lệnh CLI khác chạy được khi chưa cài extra ``web``.

An toàn (ADR-001 mục 5): mọi ``key`` từ URL được tra ngược qua kết quả quét
workspace (``find_episode``/``find_playlist``), không ghép path từ input client;
mọi ``POST`` kiểm ``Origin`` để trang web lạ không điều khiển được server local.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.audio.render import OUTPUT_FILENAME
from app.pipeline.dub import STAGES
from app.translation.glossary import GlossaryError
from app.web import auth, glossary as web_glossary, library
from app.web.jobs import (
    JOB_KINDS,
    TERMINAL_STATUSES,
    JobManager,
    JobRequest,
    JobValidationError,
    read_log_lines,
)
from app.youtube.download import SOURCE_FILENAME

_WEB_DIR = Path(__file__).parent
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SSE_POLL_SECONDS = 0.5
_MEDIA_FILES = {"output": OUTPUT_FILENAME, "source": SOURCE_FILENAME}


def _fmt_duration(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_progress(progress: dict[str, Any] | None) -> str:
    if not progress:
        return ""
    prefix = f"{progress['episode']} " if progress.get("episode") else ""
    return f"{prefix}{progress['index']}/{progress['total']} {progress['stage']} ({progress['state']})"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "on", "yes")


def _sse(event: str, data: str, event_id: int | None = None) -> str:
    out = f"event: {event}\n"
    if event_id is not None:
        out += f"id: {event_id}\n"
    return out + f"data: {data}\n\n"


def create_app(
    workspace: Path,
    job_manager: JobManager,
    *,
    allowed_hosts: tuple[str, ...] = (),
    password: str | None = None,
    shared_glossary: Path | None = None,
) -> FastAPI:
    workspace = Path(workspace)
    password = password or None  # chuỗi rỗng = tắt auth
    origin_hosts = _LOCAL_HOSTS | {h.lower() for h in allowed_hosts}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        job_manager.start()
        try:
            yield
        finally:
            job_manager.stop()

    app = FastAPI(title="YouTube Vietnamese Dubber", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=_WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=_WEB_DIR / "templates")
    templates.env.filters["duration"] = _fmt_duration
    templates.env.filters["progress"] = _fmt_progress
    templates.env.globals["auth_enabled"] = password is not None
    throttle = auth.LoginThrottle()

    # Starlette: middleware đăng ký SAU chạy NGOÀI cùng. Auth đăng ký trước
    # check_host để Host lạ bị chặn (400) trước khi chạm tới logic đăng nhập.
    if password is not None:

        @app.middleware("http")
        async def require_login(request: Request, call_next):
            """Mọi path (trừ /login, /static/) cần cookie phiên hợp lệ.

            Làm theo path chứ không theo decorator từng route để route thêm sau
            (WEB-2) mặc định được bảo vệ.
            """
            path = request.url.path
            if path in auth.PUBLIC_PATHS or path.startswith("/static/"):
                return await call_next(request)
            if auth.verify_session(request.cookies.get(auth.COOKIE_NAME), password):
                return await call_next(request)
            wants_html = "text/html" in request.headers.get("accept", "")
            if request.method in ("GET", "HEAD") and wants_html:
                target = path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
            return JSONResponse({"detail": "Cần đăng nhập."}, status_code=401)

    @app.middleware("http")
    async def check_host(request: Request, call_next):
        """Chặn DNS rebinding: Host lạ (vd evil.example trỏ về 127.0.0.1) -> 400."""
        host = request.headers.get("host", "")
        if host.startswith("["):  # [::1]:8765
            name = host[1:].split("]", 1)[0]
        else:
            name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        if name.lower() not in origin_hosts:
            return JSONResponse({"detail": "Host không được phép."}, status_code=400)
        return await call_next(request)

    def check_origin(request: Request) -> None:
        """POST có Origin lạ (trang web khác gọi vào localhost) -> 403."""
        origin = request.headers.get("origin")
        if origin is None:
            return
        try:
            host = (urlparse(origin).hostname or "").lower()
        except ValueError:
            host = ""
        if host not in origin_hosts:
            raise HTTPException(status_code=403, detail="Origin không được phép.")

    def render(request: Request, name: str, **context: Any):
        return templates.TemplateResponse(request, name, context)

    def episode_or_404(key: str) -> tuple[Path, library.EpisodeSummary]:
        path = library.find_episode(workspace, key)
        if path is None:
            raise HTTPException(status_code=404, detail="Không có episode này.")
        playlists, singles = library.scan_workspace(workspace)
        for ep in [*singles, *(e for pl in playlists for e in pl.episodes)]:
            if ep.key == key:
                return path, ep
        raise HTTPException(status_code=404, detail="Không có episode này.")

    def job_or_404(job_id: str) -> dict[str, Any]:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không có job này.")
        return job

    # ---- đăng nhập (chỉ khi bật mật khẩu) ----------------------------------

    if password is not None:

        def login_page(request: Request, next_url: str, *, error: str | None = None, status: int = 200):
            response = templates.TemplateResponse(
                request, "login.html", {"next_url": next_url, "error": error}, status_code=status
            )
            return response

        @app.get("/login")
        def login_form(request: Request):
            next_url = auth.safe_next(request.query_params.get("next"))
            if auth.verify_session(request.cookies.get(auth.COOKIE_NAME), password):
                return RedirectResponse(next_url, status_code=303)
            return login_page(request, next_url)

        @app.post("/login")
        async def login_submit(request: Request):
            check_origin(request)
            raw = (await request.body()).decode("utf-8", errors="replace")
            form = {k: v[-1] for k, v in parse_qs(raw).items()}
            next_url = auth.safe_next(form.get("next"))
            client = request.client.host if request.client else "?"
            wait = throttle.blocked(client)
            if wait > 0:
                return login_page(
                    request, next_url, status=429,
                    error=f"Sai quá nhiều lần, thử lại sau {int(wait) + 1} giây.",
                )
            if not auth.check_password(form.get("password", ""), password):
                throttle.record_failure(client)
                return login_page(request, next_url, status=401, error="Sai mật khẩu.")
            throttle.reset(client)
            response = RedirectResponse(next_url, status_code=303)
            # Không `Secure`: server chỉ nói HTTP; trình duyệt sẽ bỏ cookie Secure.
            response.set_cookie(
                auth.COOKIE_NAME, auth.make_session(password),
                max_age=auth.SESSION_SECONDS, path="/", httponly=True, samesite="strict",
            )
            return response

        @app.post("/logout")
        def logout(request: Request):
            check_origin(request)
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(auth.COOKIE_NAME, path="/", httponly=True, samesite="strict")
            return response

    # ---- trang HTML ------------------------------------------------------

    @app.get("/")
    def index(request: Request):
        playlists, singles = library.scan_workspace(workspace)
        if not playlists and not singles:
            return RedirectResponse("/jobs")
        return render(request, "library.html", playlists=playlists, singles=singles, stages=STAGES)

    @app.get("/library")
    def library_page(request: Request):
        playlists, singles = library.scan_workspace(workspace)
        return render(request, "library.html", playlists=playlists, singles=singles, stages=STAGES)

    @app.get("/jobs")
    def jobs_page(request: Request):
        return render(request, "jobs.html", jobs=job_manager.list(), kinds=[k for k in JOB_KINDS if k != "glossary"])

    @app.get("/jobs/{job_id}")
    def job_page(request: Request, job_id: str):
        return render(request, "job.html", job=job_or_404(job_id))

    @app.get("/pl/{key}")
    def playlist_page(request: Request, key: str):
        if library.find_playlist(workspace, key) is None:
            raise HTTPException(status_code=404, detail="Không có playlist này.")
        playlists, _ = library.scan_workspace(workspace)
        pl = next(p for p in playlists if p.key == key)
        # episode_dir trong playlist.json tương đối so với thư mục playlist.
        ep_by_key = {e.key: e for e in pl.episodes}
        links: dict[int, str] = {}
        for entry in pl.entries:
            rel = entry.get("episode_dir")
            if isinstance(rel, str):
                ep_key = library.make_key(f"{key.replace('~', '/')}/{rel}")
                if ep_key in ep_by_key:
                    links[entry.get("index")] = ep_key
        gstate = web_glossary.read_playlist_glossary_state(
            library.find_playlist(workspace, key), shared_glossary
        )
        return render(request, "playlist.html", pl=pl, links=links, gstate=gstate)

    @app.get("/ep/{key}")
    def episode_page(request: Request, key: str):
        path, ep = episode_or_404(key)
        has_output = (path / OUTPUT_FILENAME).is_file()
        has_source = (path / SOURCE_FILENAME).is_file()
        return render(
            request,
            "episode.html",
            ep=ep,
            gstate=web_glossary.read_glossary_state(path, shared_glossary),
            segments=library.load_segments(path),
            has_output=has_output,
            has_source=has_source,
            stages=STAGES,
        )

    @app.get("/ep/{key}/glossary")
    def glossary_page(request: Request, key: str):
        path, ep = episode_or_404(key)
        return render(
            request,
            "glossary.html",
            ep=ep,
            gstate=web_glossary.read_glossary_state(path, shared_glossary),
        )

    # ---- Glossary playlist (CP9-A) -----------------------------------------

    def playlist_or_404(key: str) -> Path:
        path = library.find_playlist(workspace, key)
        if path is None:
            raise HTTPException(status_code=404, detail="Không có playlist này.")
        return path

    @app.get("/pl/{key}/glossary")
    def playlist_glossary_page(request: Request, key: str):
        path = playlist_or_404(key)
        playlists, _ = library.scan_workspace(workspace)
        pl = next(p for p in playlists if p.key == key)
        return render(
            request,
            "glossary.html",
            pl=pl,
            ep=None,
            gstate=web_glossary.read_playlist_glossary_state(path, shared_glossary),
        )

    @app.get("/api/playlists/{key}/glossary")
    def api_playlist_glossary(key: str):
        path = playlist_or_404(key)
        return web_glossary.read_playlist_glossary_state(path, shared_glossary).to_dict()

    @app.put("/api/playlists/{key}/glossary")
    async def api_playlist_glossary_save(request: Request, key: str):
        check_origin(request)
        path = playlist_or_404(key)
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            return JSONResponse({"error": "Body không phải JSON hợp lệ."}, status_code=400)
        content = data.get("content") if isinstance(data, dict) else None
        base = data.get("base_sha256") if isinstance(data, dict) else None
        if not isinstance(content, str) or not (base is None or isinstance(base, str)):
            return JSONResponse(
                {"error": "Cần `content` (chuỗi) và `base_sha256` (chuỗi hoặc null)."},
                status_code=400,
            )
        try:
            state = web_glossary.save_playlist_glossary_text(
                path, content, base_sha256=base, shared_path=shared_glossary
            )
        except GlossaryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except web_glossary.GlossaryConflictError as exc:
            current = web_glossary.read_playlist_glossary_state(path, shared_glossary).to_dict()
            return JSONResponse({"error": str(exc), "state": current}, status_code=409)
        return state.to_dict()

    @app.post("/api/playlists/{key}/redub", status_code=201)
    def api_playlist_redub(request: Request, key: str):
        check_origin(request)
        path = playlist_or_404(key)
        try:
            return job_manager.submit(web_glossary.playlist_redub_request(path, shared_glossary))
        except JobValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    # ---- API glossary (WEB-2) -----------------------------------------------

    @app.get("/api/episodes/{key}/glossary")
    def api_glossary(key: str):
        path, _ = episode_or_404(key)
        return web_glossary.read_glossary_state(path, shared_glossary).to_dict()

    @app.put("/api/episodes/{key}/glossary")
    async def api_glossary_save(request: Request, key: str):
        check_origin(request)
        path, _ = episode_or_404(key)
        try:
            data = json.loads(await request.body() or b"{}")
        except ValueError:
            return JSONResponse({"error": "Body không phải JSON hợp lệ."}, status_code=400)
        content = data.get("content") if isinstance(data, dict) else None
        base = data.get("base_sha256") if isinstance(data, dict) else None
        if not isinstance(content, str) or not (base is None or isinstance(base, str)):
            return JSONResponse(
                {"error": "Cần `content` (chuỗi) và `base_sha256` (chuỗi hoặc null)."},
                status_code=400,
            )
        try:
            state = web_glossary.save_glossary_text(
                path, content, base_sha256=base, shared_path=shared_glossary
            )
        except GlossaryError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except web_glossary.GlossaryConflictError as exc:
            current = web_glossary.read_glossary_state(path, shared_glossary).to_dict()
            return JSONResponse({"error": str(exc), "state": current}, status_code=409)
        return state.to_dict()

    @app.post("/api/episodes/{key}/glossary/draft", status_code=201)
    def api_glossary_draft(request: Request, key: str):
        check_origin(request)
        episode_or_404(key)
        try:
            return job_manager.submit(JobRequest(kind="glossary", episode_key=key))
        except JobValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    @app.post("/api/episodes/{key}/redub", status_code=201)
    def api_redub(request: Request, key: str):
        check_origin(request)
        path, _ = episode_or_404(key)
        try:
            return job_manager.submit(web_glossary.redub_request(workspace, path))
        except JobValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    # ---- API job ----------------------------------------------------------

    async def parse_job_request(request: Request) -> JobRequest:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        raw = await request.body()
        data: dict[str, Any]
        if ctype == "application/x-www-form-urlencoded":
            # Tự parse để khỏi phụ thuộc python-multipart (không nằm trong extra `web`).
            data = {k: v[-1] for k, v in parse_qs(raw.decode("utf-8", errors="replace")).items()}
        else:
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                raise JobValidationError("Body không phải JSON hợp lệ.") from None
        if not isinstance(data, dict):
            raise JobValidationError("Body phải là một object JSON.")

        def opt_str(name: str) -> str | None:
            value = data.get(name)
            if value is None:
                return None
            if not isinstance(value, str):
                raise JobValidationError(f"`{name}` phải là chuỗi.")
            return value.strip() or None

        kind = data.get("kind")
        url = data.get("url")
        if kind == "glossary" and url is None:
            url = ""
        if not isinstance(kind, str) or not isinstance(url, str):
            raise JobValidationError("Thiếu `kind` hoặc `url` (chuỗi).")
        return JobRequest(
            kind=kind,
            url=url,
            episode_key=opt_str("episode_key"),
            recheck=_truthy(data.get("recheck", False)),
            source_lang=opt_str("source_lang"),
            items=opt_str("items"),
            force=_truthy(data.get("force", False)),
            download_only=_truthy(data.get("download_only", False)),
        )

    @app.post("/api/jobs", status_code=201)
    async def api_submit(request: Request):
        check_origin(request)
        try:
            job = job_manager.submit(await parse_job_request(request))
        except JobValidationError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return job

    @app.get("/api/jobs")
    def api_jobs():
        return job_manager.list()

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str):
        return job_or_404(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def api_cancel(request: Request, job_id: str):
        check_origin(request)
        job_or_404(job_id)
        return job_manager.cancel(job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def api_retry(request: Request, job_id: str):
        check_origin(request)
        job_or_404(job_id)
        return job_manager.retry(job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def api_events(request: Request, job_id: str):
        job_or_404(job_id)
        try:
            offset = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            offset = 0

        async def stream() -> AsyncIterator[str]:
            nonlocal offset
            last_state: str | None = None
            while True:
                job = job_manager.get(job_id)
                if job is None:
                    return
                done = job["status"] in TERMINAL_STATUSES
                # `final` đọc status TRƯỚC khi đọc log: log chỉ lớn thêm, nên nếu job
                # đã kết thúc thì lần đọc này chắc chắn thấy hết.
                lines, offset = read_log_lines(job_manager.log_path(job_id), offset, final=done)
                for end_offset, text in lines:
                    yield _sse("log", json.dumps(text, ensure_ascii=False), end_offset)
                state = json.dumps(
                    {k: job[k] for k in ("status", "progress", "exit_code")}, ensure_ascii=False
                )
                if state != last_state:
                    last_state = state
                    yield _sse("status", state)
                if done:
                    return
                await asyncio.sleep(_SSE_POLL_SECONDS)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- API thư viện + media ----------------------------------------------

    @app.get("/api/library")
    def api_library():
        playlists, singles = library.scan_workspace(workspace)
        return {"playlists": [asdict(p) for p in playlists], "episodes": [asdict(e) for e in singles]}

    @app.get("/api/episodes/{key}/segments")
    def api_segments(key: str):
        path, _ = episode_or_404(key)
        return library.load_segments(path)

    @app.get("/media/{key}/{kind}")
    def media(key: str, kind: str):
        filename = _MEDIA_FILES.get(kind)
        if filename is None:
            raise HTTPException(status_code=404, detail="Loại media không hợp lệ.")
        path, _ = episode_or_404(key)
        file_path = path / filename
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Chưa có file này.")
        # FileResponse tự xử lý header Range -> 206 (tua video).
        return FileResponse(file_path, media_type="video/mp4")

    return app


def run(
    host: str,
    port: int,
    workspace: Path,
    config_path: Path | None,
    password: str | None = None,
    shared_glossary: Path | None = None,
    max_jobs: int = 1,
) -> None:
    """Chạy uvicorn (chặn tới khi Ctrl+C)."""
    import uvicorn

    manager = JobManager(workspace, config_path, max_jobs=max_jobs)
    app = create_app(workspace, manager, allowed_hosts=(host,), password=password,
                     shared_glossary=shared_glossary)
    print(f"[web] http://{host}:{port}  (workspace: {workspace})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")

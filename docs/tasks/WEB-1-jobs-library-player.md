# Task: WEB-1 — Web UI local: nhập URL + jobs + thư viện + player

## Status / Approval

- Status: DRAFT
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer, task nhiều file + test + chạy thật
- Authorization mode: boundary
- Authorization source: ADR-001 boundary (HUMAN LEAD 2026-10-17)
- Parallel group: —
- Owned paths: app/web/**, app/cli.py, app/config.py, config.example.yaml, pyproject.toml, tests/test_web_*.py, README.md, docs/decisions/WEB-1.md
- Dependencies: ADR-001 ACCEPTED; `.venv` (đã có); Ollama có model dịch cho phần chạy thật trọn pipeline (xem Required verification)
- Base commit / branch: điền SHA khi `/implement` / main
- Human Lead approval: inherited from boundary
- Implementation authorized: YES

## Goal

`$PY -m app web` mở web server local (mặc định `http://127.0.0.1:8765`). Người dùng **dán URL video hoặc playlist YouTube** vào form → web xếp job, chạy pipeline (đúng lệnh CLI `dub`/`playlist`) ở tiến trình con, hiện log + tiến độ stage trực tiếp, hủy/chạy lại được. Kết quả hiện trong thư viện: trạng thái từng stage, player `output_vi.mp4`/`source.mp4`, bảng câu dịch click-để-tua, lọc câu `too_long`.

## Scope

- In scope: subcommand `web`; section config `web`; extra dependency `web`; job queue + subprocess + SSE + hủy + chạy lại + recovery; quét workspace; trang Jobs, Job, Thư viện, Episode, Playlist; media có HTTP Range; JSON API nội bộ; test; README mục "Web UI".
- Out of scope: sửa glossary (WEB-2); sửa câu dịch (WEB-3); auth; bind ngoài localhost; nhiều job chạy đồng thời; **mọi thay đổi trong `app/pipeline/`, `app/youtube/`, `app/translation/`… và schema artifact** (dòng tiến độ máy đọc được, lock file ở ADR-001 mục 7 → chưa làm ở WEB-1: parse log hiện có, ghi rủi ro vào decision log).

## Authority / key decisions

- `docs/adr/ADR-001-web-ui.md` (ACCEPTED): mục 0 boundary, 4.2 stack, 4.3 subprocess + 1 worker, 5 kiến trúc/trang/an toàn, 6 (WEB-1 sau gộp).
- Data model: `docs/IMPLEMENTATION_PLAN.md` §7–8; `playlist.json`: `docs/decisions/checkpoint-8.md` mục A2; log format: `app/pipeline/dub.py` `_log_start`/`_log_done`, `app/pipeline/playlist.py` (`EPnn` tag).
- Quyết định cục bộ:
  - Dependency web là **optional**: `pyproject.toml` thêm `[project.optional-dependencies] web = ["fastapi>=0.115", "uvicorn>=0.30", "jinja2>=3.1", "httpx>=0.27"]` (`httpx` cho `TestClient`). Chỉ `app/web/server.py` import fastapi, và chỉ được import bên trong handler của subcommand `web` → mọi lệnh CLI khác chạy khi chưa cài extra; `web` thiếu thư viện → in hướng dẫn `pip install -e ".[web]"`, exit 2.
  - Test web dùng `unittest.skipUnless(<fastapi import được>)`; `jobs.py`/`library.py` thuần stdlib nên test luôn chạy.
  - Job chạy **đúng lệnh CLI** (`[sys.executable, "-m", "app", kind, url, ...]`), không gọi `run_dub` trong process server.
  - Không index/cache: mỗi request quét lại workspace; ghi số đo thời gian quét vào decision log.

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `pyproject.toml` | extra `web`; đảm bảo `app/web/templates/**`, `app/web/static/**` có trong wheel |
| `app/config.py` | `WebConfig(host: str = "127.0.0.1", port: int = 8765)`, field `web` trong `AppConfig`, parse + validate (port 1–65535) theo pattern `_check_section` |
| `config.example.yaml` | section `web:` + comment: chỉ bind localhost; mở LAN là quyết định riêng (ADR-001 D1-B) |
| `app/cli.py` | subcommand `web` (`--host`, `--port`, `--workspace`, `--config` kế thừa từ `common`); flag > config > mặc định; host không phải loopback → in cảnh báo rõ (vẫn chạy; ghi `[CẦN DUYỆT]`) |
| `app/web/__init__.py` | docstring module |
| `app/web/library.py` | quét workspace (stdlib) |
| `app/web/jobs.py` | `JobManager` (stdlib: `subprocess`, `threading`, `json`) |
| `app/web/server.py` | `create_app(workspace, job_manager) -> FastAPI`, route, Jinja2, static; `run(host, port, workspace, config_path)` gọi uvicorn; lifespan: start/stop `JobManager` |
| `app/web/templates/*.html` | `base`, `jobs`, `job`, `library`, `episode`, `playlist` (Jinja2 autoescape bật) |
| `app/web/static/app.css`, `app/web/static/*.js` | JS thuần: form submit, `EventSource` cho log, player (click câu → tua, highlight câu đang phát, chuyển output/source giữ thời điểm, lọc `too_long`) |
| `tests/test_web_library.py`, `tests/test_web_jobs.py`, `tests/test_web_server.py`, `tests/test_web_cli_config.py` | xem Required verification (không sửa `tests/test_config.py`/`tests/test_cli.py` — ngoài boundary) |
| `README.md` | mục "Web UI (local)": cài extra, chạy, nhập URL, giới hạn |
| `docs/decisions/WEB-1.md` | log quyết định; mục A = contract cho WEB-2 (API job, schema job JSON, hàm library) |

### Interface — `app/web/library.py`

```python
STAGES = app.pipeline.dub.STAGES   # tái dùng, không gõ lại

@dataclass(frozen=True)
class EpisodeSummary:
    key: str                 # rel_dir mã hóa an toàn cho URL ("/" -> "~"), dùng trong route
    rel_dir: str             # POSIX, tương đối workspace: "vid__t" hoặc "pl__t/vid__t"
    title: str | None; video_id: str | None; duration_seconds: float | None
    playlist_key: str | None # None nếu episode lẻ
    stages: dict[str, str]   # stage -> "done" | "missing"
    too_long_count: int | None

@dataclass(frozen=True)
class PlaylistSummary:
    key: str; title: str | None; url: str | None
    entries: list[dict[str, Any]]    # nguyên văn playlist.json["entries"]
    episodes: list[EpisodeSummary]

def scan_workspace(workspace: Path) -> tuple[list[PlaylistSummary], list[EpisodeSummary]]
def find_episode(workspace: Path, key: str) -> Path | None    # chỉ trả path có trong kết quả quét
def find_playlist(workspace: Path, key: str) -> Path | None
def load_segments(episode_dir: Path) -> list[dict[str, Any]]
```

Stage "done" theo artifact (tên lấy từ hằng số có sẵn): download = `SOURCE_FILENAME` + `METADATA_FILENAME` (`app/youtube/download.py`); transcribe = `TRANSCRIPT_FILENAME`; translate = `TRANSLATED_FILENAME`; tts = `TTS_DIRNAME/MANIFEST_FILENAME`; normalize = `NORMALIZED_FILENAME`; render = `OUTPUT_FILENAME` (`app/audio/render.py`).

Nhận diện: thư mục con cấp 1 có `metadata.json` → episode lẻ; có `PLAYLIST_STATE_FILENAME` → playlist, episode của nó là thư mục con cấp 2 có `metadata.json`. Bỏ qua thư mục khác (gồm `.web/`). JSON hỏng → không crash, field `None`, log cảnh báo.

`load_segments`: ưu tiên `normalized.json` (`status`, `tempo`), rồi `translated.json`, rồi `transcript.json`; trả dict chuẩn hóa `id, start, end, source_text, translated_text|None, status|None, tempo|None`.

### Interface — `app/web/jobs.py`

```python
JOB_KINDS = ("dub", "playlist")
JOB_STATUSES = ("queued", "running", "completed", "failed", "cancelled", "interrupted")

@dataclass
class JobRequest:
    kind: str                      # "dub" | "playlist"
    url: str
    source_lang: str | None = None # -> --source-lang
    items: str | None = None       # playlist: -> --items, validate bằng app.pipeline.playlist.parse_item_spec
    force: bool = False            # -> --force
    download_only: bool = False    # playlist: -> --download-only

class JobValidationError(ValueError): ...

def validate_request(req: JobRequest) -> None
def build_command(req: JobRequest, *, workspace: Path, config_path: Path | None,
                  python: str = sys.executable) -> list[str]
def parse_progress(line: str) -> dict[str, Any] | None
    # "[dub] (3/6) translate ..."           -> {"episode": None, "index": 3, "total": 6, "stage": "translate", "state": "running"}
    # "[EP02] [dub] (3/6) translate xong (12.0s)" -> {"episode": "EP02", ..., "state": "done"}  (SKIP -> "skipped")

class JobManager:
    def __init__(self, workspace: Path, config_path: Path | None, *,
                 python: str = sys.executable, popen=subprocess.Popen) -> None  # popen inject để test
    def start(self) -> None          # recovery + thread worker
    def stop(self) -> None           # dừng worker, kill job đang chạy
    def submit(self, req: JobRequest) -> dict[str, Any]        # validate, ghi job JSON "queued"
    def cancel(self, job_id: str) -> dict[str, Any]
    def retry(self, job_id: str) -> dict[str, Any]             # job mới, cùng request
    def get(self, job_id: str) -> dict[str, Any] | None
    def list(self) -> list[dict[str, Any]]                     # mới nhất trước
    def log_path(self, job_id: str) -> Path
```

State: `<workspace>/.web/jobs/<job_id>.json` (ghi atomic: `*.tmp` + `os.replace`, như `playlist.json`) + `<job_id>.log`. `job_id` = `YYYYMMDD-HHMMSS-<6 hex>`. Job JSON:

```json
{"id": "20261017-101500-a1b2c3", "kind": "playlist",
 "request": {"url": "...", "source_lang": "zh", "items": "1-3", "force": false, "download_only": false},
 "command": ["/…/.venv/bin/python", "-m", "app", "playlist", "...", "--workspace", "output", "--items", "1-3", "--source-lang", "zh"],
 "status": "running", "exit_code": null,
 "created_at": "...", "started_at": "...", "finished_at": null,
 "progress": {"episode": "EP02", "index": 3, "total": 6, "stage": "translate", "state": "running"},
 "retry_of": null}
```

Hành vi bắt buộc:

- **Một worker**, FIFO: job thứ hai chờ `queued` tới khi job trước kết thúc (GPU/Ollama dùng chung).
- Subprocess: `stdout=PIPE, stderr=STDOUT`, text UTF-8 (`errors="replace"`), env thêm `PYTHONUNBUFFERED=1` (không thì log tới trễ theo block buffer) và `PYTHONIOENCODING=utf-8`; `cwd` = thư mục project hiện tại; list args, **không** `shell=True`. Linux/macOS: `start_new_session=True`; Windows: `creationflags=CREATE_NEW_PROCESS_GROUP`.
- Mỗi dòng stdout: append vào `.log` (flush ngay), `parse_progress` → cập nhật `progress` trong job JSON (không ghi JSON mỗi dòng nếu progress không đổi).
- Kết thúc: exit 0 → `completed`; khác 0 → `failed` (lỗi chi tiết nằm trong log).
- **Hủy**: `queued` → `cancelled` ngay; `running` → SIGTERM process group (Windows: `terminate()`), chờ 10 s rồi SIGKILL; status `cancelled`. Hủy an toàn nhờ resume của pipeline.
- **Recovery** (`start()`): job `running` từ lần server trước → `interrupted`; job `queued` giữ nguyên và được chạy tiếp.
- **Chạy lại**: tạo job mới cùng request (`retry_of`), không `--force` trừ khi request gốc có → pipeline SKIP phần đã xong.
- `validate_request`: `kind ∈ JOB_KINDS`; URL `http(s)`, host ∈ {`youtube.com`, `www.youtube.com`, `m.youtube.com`, `music.youtube.com`, `youtu.be`}; `playlist` cần query `list=`; `dub` cần `v=` hoặc `youtu.be/<id>` hoặc `/shorts/<id>`; `source_lang` khớp `^[a-z]{2,3}$`; `items` qua `parse_item_spec`; `items`/`download_only` chỉ với `playlist`. Sai → `JobValidationError` với thông điệp tiếng Việt.
- `config_path`: truyền `--config <path>` cho subprocess nếu server được mở với config → job dùng đúng `translation.host`/model của server.

### Route — `app/web/server.py`

| Method + path | Trả về |
|---|---|
| `GET /` | redirect `/jobs` nếu workspace trống, ngược lại trang Thư viện |
| `GET /library` | Thư viện: playlist + episode lẻ, 6 cột stage, số `too_long`, link |
| `GET /jobs` | form nhập URL (kind, source_lang, items, force, download_only) + danh sách job |
| `GET /jobs/{id}` | trang job: request, status, tiến độ, log trực tiếp, nút Hủy / Chạy lại |
| `GET /pl/{key}` | bảng entries `playlist.json` (index, title, status, downloaded, error **đầy đủ**, seconds) + link episode |
| `GET /ep/{key}` | player + bảng câu |
| `POST /api/jobs` | JSON `JobRequest` hoặc form → 201 + job JSON; validation lỗi → 400 + thông điệp |
| `GET /api/jobs`, `GET /api/jobs/{id}` | JSON |
| `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry` | job JSON |
| `GET /api/jobs/{id}/events` | SSE: `event: log` (mỗi dòng log, `id:` = byte offset; hỗ trợ `Last-Event-ID` để nối lại), `event: status` khi status/progress đổi; đóng stream khi job kết thúc và đã gửi hết log |
| `GET /api/library`, `GET /api/episodes/{key}/segments` | JSON |
| `GET /media/{key}/{kind}` | `kind ∈ {output, source}` → `FileResponse` mp4 có `Range` (206) |

An toàn: bind `127.0.0.1` mặc định; mọi `key` tra qua `find_episode`/`find_playlist`, không ghép path từ input client → key lạ/traversal 404; mọi `POST` kiểm `Origin` (nếu có) có host là `127.0.0.1`/`localhost`/host đang bind, sai → 403; Jinja2 autoescape.

## Acceptance Criteria

1. `$PY -m app web --help` hiện `--host`, `--port`, `--workspace`; thiếu extra → hướng dẫn cài, exit 2; lệnh CLI khác không cần extra.
2. Mặc định bind `127.0.0.1:8765`; `--port` / `web.port` ghi đè; port ngoài 1–65535 → lỗi config rõ.
3. Dán URL video hợp lệ vào form → job `queued` → `running` chạy đúng lệnh `app dub <url> --workspace ...` (+ tuỳ chọn), log hiện trực tiếp trên trang job, tiến độ hiện stage hiện tại (`3/6 translate`); kết thúc → `completed`/`failed` đúng exit code.
4. URL playlist → job `playlist` với `--items`/`--download-only` khi chọn; tiến độ hiện tập (`EP02`) + stage.
5. URL sai (không phải YouTube, playlist thiếu `list=`, `items` sai cú pháp, `source_lang` lạ) → 400 với thông điệp tiếng Việt, không tạo job.
6. Hai job gửi liên tiếp: job 2 ở `queued` tới khi job 1 xong (không bao giờ hai subprocess cùng lúc).
7. Hủy job đang chạy → process (cả process con của nó) bị kill trong ≤ 10 s, status `cancelled`; Chạy lại → job mới, pipeline SKIP stage đã xong.
8. Tắt server khi job đang chạy rồi bật lại → job đó `interrupted`, job `queued` được chạy tiếp.
9. `/library` liệt kê mọi episode lẻ + playlist với trạng thái 6 stage đúng theo artifact và số `too_long`; `/pl/{key}` hiện lỗi đầy đủ.
10. `/ep/{key}` phát được output, tua được (Range → 206), chuyển sang source giữ thời điểm; click câu → tua tới `start`; lọc `too_long`. Episode chưa render → trang vẫn mở, hiện source nếu có + thông báo chưa có output.
11. Key lạ/traversal (vd `..%2F..`) → 404; `POST` có `Origin` lạ → 403; title chứa `<script>` hiển thị dạng text.
12. Ngoài `<workspace>/.web/` và artifact do job pipeline tạo, web không tạo/sửa file nào trong workspace.

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS khi đã cài extra `web`. Case mới:
  - `tests/test_web_library.py`: workspace giả có episode đủ 6 stage, episode dở, playlist 2 tập (1 failed error nhiều dòng), thư mục rác, `.web/`, JSON hỏng → `scan_workspace` đúng; `find_episode` từ chối key lạ/traversal; `load_segments` fallback. — AC9, AC11.
  - `tests/test_web_jobs.py` (stdlib, `popen` giả): `validate_request` các case AC5; `build_command` đúng args cho dub/playlist/options/config; `parse_progress` cho dòng dub, dòng `[EPnn]`, SKIP, dòng lạ → None; FIFO 1 worker (AC6); cancel queued/running (AC7); exit code → status (AC3); recovery (AC8); retry; ghi JSON atomic.
  - `tests/test_web_server.py` (`TestClient`, `JobManager` với `popen` giả): các trang 200; `POST /api/jobs` 201/400/403; SSE trả dòng log + status; `/media` với `Range: bytes=0-9` → 206 + `Content-Range`; 404 traversal; escape `<script>`. — AC3–AC5, AC10, AC11.
  - `tests/test_web_cli_config.py`: section `web`, validate port, parser `web`. — AC1, AC2.
- **Chạy thật** (bắt buộc, profile §4 luật 1). Ollama: `config.yaml` (gitignored) đặt `translation.host: http://127.0.0.1:11437` và model mà HUMAN LEAD chọn (xem current-state); nếu model chưa sẵn sàng thì bước 3 chạy tới hết `transcribe` rồi ghi rõ phần chưa kiểm.
  1. `$PY -m app web --workspace output` chạy nền; `ss -ltnp | grep 8765` → chỉ `127.0.0.1`.
  2. `curl -s -X POST -H 'Content-Type: application/json' -d '{"kind":"dub","url":"https://example.com/x"}' http://127.0.0.1:8765/api/jobs` → 400.
  3. `POST /api/jobs` với một **video YouTube ngắn thật (1–3 phút)** → theo dõi `curl -N .../api/jobs/<id>/events` thấy log từng stage tới lúc kết thúc; `ls` thư mục episode thấy artifact; `ffprobe` `output_vi.mp4` có cả audio + video stream (nếu tới được render).
  4. Gửi job thứ hai ngay sau job 1 → `GET /api/jobs` thấy `queued` (AC6). Hủy job 2 khi đang `running` (hoặc chạy job với `--force` để có thời gian hủy) → `ps` không còn process `app dub`; Chạy lại → log có `SKIP` cho stage đã xong (AC7).
  5. `kill` server khi một job đang chạy, bật lại → job đó `interrupted` (AC8).
  6. `curl -s -o /dev/null -w '%{http_code} %{size_download}\n' -r 0-1023 http://127.0.0.1:8765/media/<key>/source` → `206 1024`; `.../media/..%2F..%2Fetc/source` → `404` (AC10, AC11).
  7. `POST` với `-H 'Origin: http://evil.example'` → 403.
  8. Mở `/jobs`, `/jobs/<id>`, `/library`, `/ep/<key>` bằng trình duyệt (hoặc tối thiểu `curl` HTML kiểm `<video>`, bảng câu có `data-start`, script `EventSource`); ghi rõ cách đã kiểm.

## Manual test checklist (Tech Lead)

Không chạm database hay public API. Chạm security model ở mức "server HTTP local, không auth, chạy subprocess theo input form" — đã quyết trong ADR-001 D1/D3; manual test sau automated verification:

- [ ] Mở `http://127.0.0.1:8765/jobs`, dán URL một video ngắn → xem log chạy, hủy, chạy lại.
- [ ] Dán URL playlist với `items` = `1` → tập 1 chạy.
- [ ] Ở trang episode: xem `output_vi.mp4`, tua, chuyển sang bản gốc cùng thời điểm, lọc `too_long`, click câu.

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:

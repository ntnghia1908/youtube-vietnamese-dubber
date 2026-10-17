# Task: WEB-1 — Web UI local: thư viện + player (read-only)

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
- Dependencies: commit adopt framework + ADR-001 ACCEPTED; `.venv` dựng trên máy chạy task
- Base commit / branch: commit chứa ADR-001 ACCEPTED (điền SHA khi `/implement`) / main
- Human Lead approval: inherited from boundary
- Implementation authorized: YES

## Goal

`$PY -m app web` mở một web server local (mặc định `http://127.0.0.1:8765`) cho phép: xem danh sách episode/playlist trong workspace kèm trạng thái từng stage; mở một episode để xem `output_vi.mp4` (chuyển sang `source.mp4` cùng thời điểm) và bảng câu dịch, click câu để tua, lọc câu `too_long`. Chỉ đọc — không chạy pipeline, không ghi file nào trong workspace.

## Scope

- In scope: subcommand `web`; section config `web`; extra dependency `web`; quét workspace; 3 trang HTML (Thư viện, Episode, Playlist); endpoint media có HTTP Range; JSON API read-only; test; README mục "Web UI".
- Out of scope: chạy/hủy job, SSE, log trực tiếp (WEB-2); sửa glossary (WEB-3); sửa câu dịch (WEB-4); auth; bind ngoài localhost; bất kỳ thay đổi nào trong `app/pipeline/`, `app/youtube/`, … (pipeline không đổi).

## Authority / key decisions

- `docs/adr/ADR-001-web-ui.md` (ACCEPTED) mục 0 (boundary), 4.2 (stack), 5 (kiến trúc, trang, an toàn).
- Data model: `docs/IMPLEMENTATION_PLAN.md` §7–8; `playlist.json`: `docs/decisions/checkpoint-8.md` mục A2.
- Quyết định cục bộ:
  - Dependency web là **optional**: `pyproject.toml` thêm `[project.optional-dependencies] web = ["fastapi>=0.115", "uvicorn>=0.30", "jinja2>=3.1", "httpx>=0.27"]` (`httpx` cho `TestClient`). `app/web` chỉ import fastapi bên trong `cmd_web` / module web → `$PY -m app --help` và mọi lệnh CLI khác vẫn chạy khi chưa cài extra; `web` khi thiếu thư viện in hướng dẫn `pip install -e ".[web]"`, exit 2.
  - Test web dùng `unittest.skipUnless(fastapi có sẵn)` để suite vẫn chạy được khi chưa cài extra; Required verification chạy **với** extra đã cài.
  - Không cache/không index riêng: mỗi request quét lại workspace (vài chục thư mục — đủ nhanh). Ghi số đo thời gian quét vào decision log.

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `pyproject.toml` | extra `web` như trên; include `app/web/templates/**`, `app/web/static/**` trong wheel (hatch tự lấy file trong package — kiểm) |
| `app/config.py` | `WebConfig(host: str = "127.0.0.1", port: int = 8765)`, field `web` trong `AppConfig`, parse + validate (port 1–65535) theo pattern `_check_section` hiện có |
| `config.example.yaml` | section `web:` có comment: chỉ bind localhost; mở LAN là quyết định riêng (ADR-001 D1-B) |
| `app/cli.py` | subcommand `web` (`--host`, `--port`, `--workspace`), flag > config > mặc định; cảnh báo rõ nếu host không phải loopback (vẫn chạy — user tự chịu, ghi vào decision log `[CẦN DUYỆT]`) |
| `app/web/__init__.py` | docstring module |
| `app/web/library.py` | quét workspace → model dữ liệu (không import fastapi) |
| `app/web/server.py` | `create_app(workspace: Path) -> FastAPI`, route, Jinja2, mount static; `run(host, port, workspace)` gọi uvicorn |
| `app/web/templates/*.html` | `base.html`, `library.html`, `episode.html`, `playlist.html` (Jinja2 autoescape bật) |
| `app/web/static/app.css`, `app/web/static/episode.js` | CSS gọn, JS thuần: click câu → `video.currentTime`; highlight câu đang phát; nút chuyển output/source giữ thời điểm; checkbox lọc `too_long` |
| `tests/test_web_library.py`, `tests/test_web_server.py`, `tests/test_web_cli_config.py` | xem Required verification |
| `README.md` | mục "Web UI (local)": cài extra, chạy, giới hạn read-only |
| `docs/decisions/WEB-1.md` | log quyết định triển khai; mục A = contract cho WEB-2 |

### Interface

```python
# app/web/library.py — thuần stdlib, không import fastapi
STAGES = ("download", "transcribe", "translate", "tts", "normalize", "render")

@dataclass(frozen=True)
class EpisodeSummary:
    id: str                 # = tên thư mục episode (đã kiểm hợp lệ), dùng trong URL
    rel_dir: str            # đường dẫn tương đối so với workspace, POSIX ("vid__t" hoặc "pl__t/vid__t")
    title: str | None       # metadata.json "title"; None nếu thiếu
    video_id: str | None
    duration_seconds: float | None
    playlist_id: str | None # id thư mục playlist chứa nó, None nếu episode lẻ
    stages: dict[str, str]  # stage -> "done" | "missing" (theo artifact có mặt, bảng dưới)
    too_long_count: int | None  # từ normalized.json; None nếu chưa có

@dataclass(frozen=True)
class PlaylistSummary:
    id: str; title: str | None; url: str | None
    entries: list[dict[str, Any]]   # nguyên văn entries của playlist.json (không đổi schema)
    episodes: list[EpisodeSummary]

def scan_workspace(workspace: Path) -> tuple[list[PlaylistSummary], list[EpisodeSummary]]
def find_episode(workspace: Path, episode_id: str) -> Path | None   # chỉ trả path có trong kết quả quét
def load_segments(episode_dir: Path) -> list[dict[str, Any]]
```

Trạng thái stage suy từ artifact (tên file lấy từ hằng số có sẵn, không gõ lại chuỗi):

| Stage | Artifact "done" | Hằng số |
|---|---|---|
| download | `source.mp4` + `metadata.json` | `app/youtube/download.py` `SOURCE_FILENAME`, `METADATA_FILENAME` |
| transcribe | `transcript.json` | `app/transcription/whisper.py` `TRANSCRIPT_FILENAME` |
| translate | `translated.json` | `app/translation/translate.py` `TRANSLATED_FILENAME` |
| tts | `tts/manifest.json` | `app/tts/synthesize.py` `MANIFEST_FILENAME` (+ tên thư mục tts có sẵn) |
| normalize | `normalized.json` | `app/synchronization/timing.py` `NORMALIZED_FILENAME` |
| render | `output_vi.mp4` | `app/audio/render.py` `OUTPUT_FILENAME` |

Nhận diện: thư mục con cấp 1 của workspace có `metadata.json` → episode lẻ; có `playlist.json` (`app/pipeline/playlist.py` `PLAYLIST_STATE_FILENAME`) → playlist, episode của nó là thư mục con cấp 2 có `metadata.json`. Thư mục khác (vd `.web/`) bỏ qua. JSON hỏng → không crash: episode vẫn liệt kê, field tương ứng `None`, log cảnh báo.

`load_segments`: ưu tiên `normalized.json` (có `status`, `tempo`, `ratio`, `slot`), không có thì `translated.json`, không có thì `transcript.json` (chỉ `text`). Trả list dict chuẩn hóa: `id, start, end, source_text, translated_text|None, status|None, tempo|None`.

Route (`app/web/server.py`):

| Method + path | Trả về |
|---|---|
| `GET /` | trang Thư viện |
| `GET /pl/{playlist_id}` | trang Playlist: bảng entries (index, title, status, downloaded, error **đầy đủ**, seconds) + link tới episode |
| `GET /ep/{episode_key}` | trang Episode |
| `GET /api/library` | JSON `{playlists: [...], episodes: [...]}` |
| `GET /api/episodes/{episode_key}/segments` | JSON list segment |
| `GET /media/{episode_key}/{kind}` | `kind ∈ {output, source}` → `FileResponse` mp4, hỗ trợ `Range` (206) |

`episode_key` = `rel_dir` mã hóa an toàn cho URL (vd thay `/` bằng `~`, ghi vào decision log). Mọi tra cứu đi qua `find_episode` (so khớp với kết quả quét) — **không bao giờ** ghép path từ input của client; key lạ → 404.

## Acceptance Criteria

1. `$PY -m app web --help` hiện `--host`, `--port`, `--workspace`; `$PY -m app web` khi chưa cài extra in hướng dẫn cài và exit 2; mọi lệnh CLI khác không cần extra `web`.
2. Server mặc định bind `127.0.0.1:8765`; `--port`/`config.yaml` `web.port` ghi đè được; port ngoài 1–65535 → lỗi config rõ ràng.
3. `/` liệt kê mọi episode lẻ và playlist trong workspace với trạng thái 6 stage đúng theo artifact có mặt và số câu `too_long` (nếu đã normalize).
4. `/pl/{id}` hiển thị đủ entries của `playlist.json`, gồm thông điệp lỗi đầy đủ (không cắt dòng đầu).
5. `/ep/{key}` phát được `output_vi.mp4`, tua được (Range → 206), chuyển sang `source.mp4` giữ nguyên thời điểm; bảng câu click → tua tới `start`; lọc `too_long` chỉ hiện câu có `status == "too_long"`. Episode chưa render → trang vẫn mở, hiện source (nếu có) và thông báo chưa có output.
6. `episode_key`/`playlist_id` không có trong kết quả quét (gồm chuỗi kiểu `..%2F..`) → 404; không có route nào đọc file ngoài workspace.
7. Title video chứa HTML (vd `<script>`) hiển thị dạng text (autoescape).
8. Web UI không tạo/sửa file nào trong workspace (so sánh `find <workspace> -newer <mốc>` trước/sau khi dùng).

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS khi **đã** cài extra `web` (và chạy thêm một lần không có extra nếu môi trường cho phép, xác nhận test web được skip chứ không lỗi). Case mới:
  - `tests/test_web_library.py`: workspace giả (tempdir) có episode lẻ đủ 6 stage, episode dở (chỉ download+transcribe), playlist 2 tập (1 failed có error nhiều dòng), thư mục rác, JSON hỏng → `scan_workspace` đúng stage/too_long_count/không crash; `find_episode` từ chối key lạ và key traversal; `load_segments` fallback normalized → translated → transcript. — AC3, AC6.
  - `tests/test_web_server.py` (`TestClient`): `/`, `/pl/..`, `/ep/..`, `/api/library`, `/api/episodes/../segments` trả 200 + nội dung chính; `/media/..` với header `Range: bytes=0-9` → 206 + `Content-Range`; key lạ/traversal → 404; title `<script>` bị escape. — AC3–AC7.
  - `tests/test_web_cli_config.py`: section `web` + validate port; parser `web` (thêm test vào file mới, không sửa `tests/test_config.py`/`tests/test_cli.py` — ngoài boundary ADR-001). — AC1, AC2.
- **Chạy thật** (bắt buộc, profile §4 luật 1):
  1. Workspace thật: ưu tiên thư mục EP1 đã `completed` (copy từ máy Windows vào `output/`, gồm `output_vi.mp4`) và thư mục playlist có `playlist.json`. Nếu không có: tạo episode thật bằng `$PY -m app download <video ngắn>` + `$PY -m app transcribe ... --whisper-model tiny` (không cần Ollama) — khi đó AC5 phần output chỉ kiểm được với source; ghi rõ trong báo cáo là CHƯA kiểm output.
  2. `$PY -m app web --workspace output` chạy nền; `curl -s http://127.0.0.1:8765/api/library | head` thấy episode thật với stage đúng (đối chiếu `ls` thư mục).
  3. `curl -s -o /dev/null -w '%{http_code} %{size_download}\n' -r 0-1023 http://127.0.0.1:8765/media/<key>/source` → `206 1024`; tương tự `output` nếu có.
  4. `curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8765/media/..%2F..%2Fetc/source'` → `404`.
  5. `ss -ltnp | grep 8765` → chỉ `127.0.0.1`.
  6. AC8: `touch /tmp/mark` trước, sau các bước trên `find output -newer /tmp/mark` rỗng.
  7. Mở trang `/ep/<key>` bằng trình duyệt (hoặc tối thiểu `curl` HTML và kiểm `<video>`, bảng câu có `data-start`); ghi rõ cách đã kiểm.

## Manual test checklist (Tech Lead)

Không chạm database, public API hay pipeline. Chạm security model ở mức "server HTTP local, không auth" — đã quyết trong ADR-001 D1; manual test sau automated verification:

- [ ] Mở `http://127.0.0.1:8765`, thấy EP1 + playlist.
- [ ] Ở EP1: xem `output_vi.mp4`, tua, chuyển sang bản gốc cùng thời điểm.
- [ ] Bật lọc `too_long`, click vài câu — video tua đúng chỗ; nghe để đánh giá (đầu vào cho CP9).

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:

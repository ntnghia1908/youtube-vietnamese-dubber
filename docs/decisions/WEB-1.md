# WEB-1 — Các quyết định nhỏ khi triển khai

Task: `docs/tasks/WEB-1-jobs-library-player.md`. Mục **[CẦN DUYỆT]** là chỗ Opus nên xem lại.

---

## A. Contract với WEB-2

### A1. Hàm library (`app/web/library.py`, thuần stdlib)

`scan_workspace(ws) -> (list[PlaylistSummary], list[EpisodeSummary])`, `find_episode(ws, key) -> Path | None`,
`find_playlist(ws, key) -> Path | None`, `load_segments(episode_dir) -> list[dict]`, `make_key(rel_dir)`.
`key` = `rel_dir` với `/` -> `~`; không giải mã ngược, luôn tra bằng cách quét. Thông tin glossary
của episode (`glossary.yaml`) chưa được library expose — WEB-2 tự đọc qua `find_episode`.

### A2. Job JSON (`<workspace>/.web/jobs/<id>.json`, log cạnh bên `<id>.log`)

Đúng schema contract WEB-1: `id, kind, request{url,source_lang,items,force,download_only}, command, status,
exit_code, created_at, started_at, finished_at, progress{episode,index,total,stage,state}, retry_of`.
`status` ∈ queued/running/completed/failed/cancelled/interrupted. Thêm field `pid: int|null` (ghi sau Popen, xóa khi job kết thúc/recovery) để recovery dọn pipeline mồ côi.

### A3. API HTTP

`POST /api/jobs` (JSON hoặc `application/x-www-form-urlencoded`; form tự parse bằng `parse_qs` để khỏi cần
`python-multipart`), `GET /api/jobs[/{id}]`, `POST /api/jobs/{id}/cancel|retry`, `GET /api/jobs/{id}/events` (SSE:
`event: log` data = JSON string của một dòng, `id:` = byte offset sau dòng; `event: status` data = JSON
`{status, progress, exit_code}`), `GET /api/library`, `GET /api/episodes/{key}/segments`, `GET /media/{key}/{output|source}`.
Lỗi validate: 400 `{"error": "<tiếng Việt>"}`; Origin lạ: 403 `{"detail": ...}`; id/key lạ: 404.
Để thêm job mới (vd WEB-2 chạy `glossary`/`translate`) cần mở rộng `JOB_KINDS` + `validate_request` + `build_command`
trong `jobs.py`.

### A4. `JobManager` nhận thêm kwargs tùy chọn `killpg`, `cancel_grace_seconds` (ngoài chữ ký contract) để test
không gửi tín hiệu thật tới pid giả.

---

## B. Quyết định

- **B1.** `JobManager.list()/get()` đọc thẳng đĩa (không cache bộ nhớ) dưới `RLock`: đơn giản, đúng sau restart.
  Chỉ thứ tự hàng đợi nằm trong RAM (`deque`), dựng lại từ job `queued` lúc `start()`.
- **B2.** `job_id` được kiểm regex `\d{8}-\d{6}-[0-9a-f]{6}` trước khi chạm file (id đến từ URL).
- **B3.** `stop()` trên server tắt êm: kill nhóm tiến trình con, job thành `interrupted` (không để `running`).
- **B4.** Hủy job `running`: `os.killpg(pid, SIGTERM)`, thread riêng chờ `cancel_grace_seconds` (10 s) rồi SIGKILL.
- **B5.** Số đo quét workspace (không index): ~0.35 ms/lần với 1 episode (20 lần lấy trung bình). Chưa đo với
  playlist 22 tập (ngoài dữ liệu có sẵn trên máy này); mỗi episode cần ~12 lần `stat` + đọc `metadata.json` và
  `normalized.json` nên dự kiến vẫn nhỏ so với ngưỡng cảm nhận được — **[CẦN DUYỆT]** nếu playlist lớn thì xem lại.
- **B6.** Link/ src chứa key đều qua filter `urlencode` (tên thư mục có dấu cách).

## C. Rủi ro / phát hiện [CẦN DUYỆT]

- **C1 (ĐÃ XỬ LÝ vòng review 1).** Server kill -9 để lại pipeline mồ côi. `start()` giờ đọc `pid` của job `running`: nếu còn sống và
  đúng là pipeline (`/proc/<pid>/cmdline` chứa `-m app`; không có /proc thì `getpgid(pid)==pid`) thì SIGTERM nhóm tiến trình,
  chờ `cancel_grace_seconds`, SIGKILL, ghi dòng vào log job, rồi mới `interrupted` và bật worker. Không có killpg (Windows) chỉ ghi cảnh báo.
- **C6.** Middleware kiểm `Host` (chặn DNS rebinding): chỉ nhận 127.0.0.1/localhost/::1 và host đang bind.
- **C2.** Tiến độ lấy bằng regex trên log hiện có (`[EPnn] [dub] (i/n) stage ...`). Nếu đổi format `_log_start`/`_log_done`
  thì `parse_progress` hỏng im lặng (tiến độ trống, job vẫn chạy). Có test cho format hiện tại.
- **C3.** Môi trường dev: `faster-whisper 1.2.1` lỗi `open() got an unexpected keyword argument 'metadata_errors'` với `av 19`
  (pip kéo bản mới nhất). Đã hạ cục bộ `pip install "av>=14,<17"` (còn 16.1.0) trong `.venv` để chạy thật; repo không đổi.
  Cần quyết định có ghim `av<17` trong `pyproject.toml` không (chạm dependency -> ngoài scope WEB-1).
- **C4.** Video `jNQXAC9IJRE` ("Me at the zoo") báo "This video is unavailable" qua yt-dlp trên máy này; job failed đúng exit code 1
  và lỗi hiện trong log. Chạy thật dùng `fcfQkxwz4Oo` (82 s, tiếng Anh).
- **C5.** Chưa chạy thật job `playlist` (chỉ unit test + build_command); chưa kiểm player bằng trình duyệt thật (chỉ curl HTML).

## D. Bổ sung

- **D1.** `job_id` có 2 hex đầu là bộ đếm trong cùng giây (vẫn đúng format `YYYYMMDD-HHMMSS-<6 hex>`): test phát hiện
  hai job cùng giây bị sắp xếp ngẫu nhiên, mà id là khóa sắp xếp cho `list()` và thứ tự FIFO sau recovery.

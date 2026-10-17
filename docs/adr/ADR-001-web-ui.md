# ADR-001 — Web UI local cho YouTube Vietnamese Dubber

| Metadata | Value |
|---|---|
| Status | ACCEPTED (2026-10-17) |
| Change class | S2 (scope, architecture, dependency, security model) |
| Proposed by | ORCHESTRATOR, 2026-10-17 |
| Decision | HUMAN LEAD 2026-10-17: chấp nhận D1–D5 theo khuyến nghị; D6 = boundary (duyệt một lần cho WEB-1..3) |

Plan gốc ghi Web UI là "Future" (`docs/IMPLEMENTATION_PLAN.md` §5, §31). ADR này quyết *làm thế nào* và *theo thứ tự nào*. Mỗi phase thành task contract `docs/tasks/WEB-N-*.md` qua `/spec`.

## 0. Implementation Authorization Boundary

HUMAN LEAD (2026-10-17) authorize ORCHESTRATOR tự lập và thực thi task contract cho các phase WEB-1..2 ở mục 6 (ban đầu đánh số WEB-1..3, xem sửa đổi ở mục 6) đúng như mục 4–6, không cần `APPROVE TASK` từng task. Boundary gồm:

- Path được sửa: `app/web/**` (mới), `app/cli.py` (subcommand `web`), `app/config.py` + `config.example.yaml` (section `web`), `pyproject.toml` (extra `web` với `fastapi`, `uvicorn`, `jinja2`, `httpx`), `tests/test_web_*.py`, `README.md`, `docs/`.
- Thay đổi nhỏ trong `app/pipeline/` chỉ khi mục 7 đã nêu (dòng tiến độ máy đọc được, lock file) và ghi vào decision log của task.

Ngoài boundary → dừng, hỏi HUMAN LEAD: WEB-3; bind ngoài `127.0.0.1` / auth (D1-B); dependency khác danh sách trên; đổi schema artifact pipeline (`translated.json`, `normalized.json`, `playlist.json`...). Commit/push vẫn chờ HUMAN LEAD (integration gate).

## 1. Vấn đề

Dùng CLI hiện tại có mấy điểm đau đã thấy trong thực tế:

- Theo dõi playlist 22 tập (~35 phút/tập, hàng giờ) chỉ qua log terminal và `playlist.json`.
- Đánh giá chất lượng — việc đầu tiên của CP9 — cần **xem/nghe `output_vi.mp4`**, so với `source.mp4`, đối chiếu từng câu `too_long` (EP1: 79/353) với timestamp: hiện phải mở file JSON + player riêng.
- `glossary.yaml` phải sửa tay rồi chạy lại `translate`; không thấy ngay bản dịch nào bị ảnh hưởng.
- Lỗi playlist chỉ in dòng đầu (vd không thấy "Private video").

## 2. Mục tiêu / ngoài phạm vi

Mục tiêu: một **web app chạy local** (`python -m app web` → `http://127.0.0.1:8765`) để: (1) duyệt thư viện episode/playlist và trạng thái từng stage; (2) xem/nghe output cạnh bản gốc; (3) chạy `dub`/`playlist` và theo dõi tiến độ trực tiếp; (4) sửa glossary và chạy lại phần cần thiết; (5) sau đó: duyệt/sửa từng câu dịch.

Ngoài phạm vi: hosting công khai, nhiều người dùng, đăng nhập, database, Docker, tái phát hành video, mobile app.

## 3. Ràng buộc từ project

- Filesystem/JSON là source of truth (plan §31 "Database: Không"); web **không** được tạo bản state thứ hai cho dữ liệu pipeline — luôn đọc artifact trong `workspace`.
- Mọi stage resume được (profile §4 luật 3) → hủy job = kill tiến trình là an toàn, chạy lại sẽ SKIP phần đã xong.
- GPU dùng chung (Whisper + Ollama `gemma3:12b`) → tối đa **một job xử lý** cùng lúc.
  > Sửa đổi 2026-10-17: xem mục 10.
- Không hard-code: host/port/workspace qua `config.yaml` + flag CLI.
- Bản quyền: chỉ phục vụ cho chính người dùng trên máy local.

## 4. Phương án

### 4.1 Mô hình triển khai (D1)

| Phương án | Ưu | Nhược |
|---|---|---|
| **A. Local web UI, bind 127.0.0.1 (khuyến nghị)** | khớp mục tiêu "local, chi phí thấp"; dùng GPU sẵn có; không cần auth; không đụng bản quyền | chỉ dùng trên máy chạy pipeline (hoặc qua SSH tunnel) |
| B. Mở cho LAN (điện thoại/TV xem output) | xem trên thiết bị khác | thành security model mới: cần auth/token, chống path traversal chặt hơn — decision gate riêng |
| C. Dịch vụ public (SaaS) | — | chi phí GPU, YouTube chặn yt-dlp từ IP datacenter, rủi ro bản quyền/ToS khi phân phối video lồng tiếng; trái mục tiêu project → **loại** |

### 4.2 Stack (D2)

| Phương án | Ưu | Nhược |
|---|---|---|
| **FastAPI + uvicorn + Jinja2, JS thuần (`fetch` + `EventSource`), không build step (khuyến nghị)** | toàn Python, ít dependency (3 gói); Jinja2 autoescape chặn XSS từ title video; Starlette `FileResponse` hỗ trợ HTTP Range để tua video; SSE có sẵn | phải tự viết vài trang HTML/CSS |
| stdlib `http.server` | 0 dependency (đúng tinh thần "stdlib làm được thì không thêm") | tự làm routing, Range request, escape HTML, SSE → nhiều code dễ sai hơn lợi ích |
| Gradio / Streamlit | prototype nhanh | khó làm job nền dài giờ + log stream + layout player/bảng câu; mô hình re-run toàn trang |
| FastAPI JSON API + React/Vite SPA | UI phong phú nhất | thêm toolchain Node, hai ngôn ngữ, build step — quá tay cho tool một người |

Dependency đặt ở extra `[project.optional-dependencies] web = [...]` để người chỉ dùng CLI không phải cài. Test cần thêm `httpx` (TestClient) ở extra `dev`/`web`.

### 4.3 Chạy job (D3)

> Sửa đổi 2026-10-17: xem mục 10.

| Phương án | Ưu | Nhược |
|---|---|---|
| **Subprocess gọi chính CLI: `$PY -m app dub|playlist ...` (khuyến nghị)** | tái dùng đúng code path đã chạy thật (CP7/CP8); crash/OOM của Whisper không giết web server; hủy = kill process group, an toàn nhờ resume; log stdout đã có sẵn dạng `[dub] (3/6) translate ...` | tiến độ phải parse từ log (dòng `(i/6)` của `run_dub`, `[EPxx]` của playlist) |
| Gọi `run_dub`/`run_playlist` trong thread của server, truyền `log=` callback | tiến độ có cấu trúc, không parse | model Whisper/ffmpeg nằm chung process với server; hủy giữa chừng khó (không có cancel token); lỗi native làm sập server |

Hàng đợi: một worker xử lý tuần tự (FIFO), state job ở `<workspace>/.web/jobs/<job_id>.json` + `<job_id>.log` (ghi atomic như `playlist.json`). Server khởi động lại: job đang `running` → `interrupted`, có nút "Chạy lại" (resume).

## 5. Kiến trúc đề xuất

```text
browser ──HTTP/SSE──► app/web (FastAPI, 127.0.0.1)
                        │  đọc artifact (read-only)        ┌──────────────────────┐
                        ├────────────────────────────────► │ workspace/ (output/) │
                        │  job queue (1 worker)            │  <ep>/metadata.json  │
                        └─► subprocess: $PY -m app dub ... │  <ep>/translated.json│
                               ghi artifact như CLI ─────► │  <pl>/playlist.json  │
                                                           └──────────────────────┘
```

Module mới (planned):

| Path | Vai trò |
|---|---|
| `app/web/server.py` | tạo app FastAPI, route, mount `static/` |
| `app/web/library.py` | quét workspace → danh sách episode/playlist; trạng thái stage suy từ artifact có mặt (`source.mp4`, `transcript.json`, `translated.json`, `tts/manifest.json`, `normalized.json`, `output_vi.mp4`) |
| `app/web/jobs.py` | hàng đợi, spawn/kill subprocess, ghi job JSON + log, parse tiến độ |
| `app/web/templates/`, `app/web/static/` | Jinja2 + CSS + JS thuần |
| `app/cli.py` | thêm subcommand `web` (`--host`, `--port`); config key `web.host`, `web.port` |

Trang:

1. **Thư viện** `/` — playlist + episode lẻ, cột stage (✓/–/lỗi), thời lượng, link.
2. **Episode** `/ep/<id>` — player `output_vi.mp4` (chuyển nhanh sang `source.mp4` tại cùng thời điểm), bảng câu: thời gian, câu gốc, câu dịch, tempo, cờ `too_long`; click câu → tua video; lọc `too_long`.
3. **Playlist** `/pl/<id>` — bảng từ `playlist.json` (status, downloaded, error đầy đủ, thời gian), nút chạy tiếp/`--items`.
4. **Jobs** `/jobs` — form nhập URL (dub/playlist, `--source-lang`, `--items`, `--force`), hàng đợi, log trực tiếp (SSE), hủy.
5. **Glossary** `/ep/<id>/glossary` — sửa `glossary.yaml` (validate YAML trước khi lưu), nút "Dịch lại + chạy tiếp" (translate tự dịch lại khi glossary đổi — CP6.5).

API (nội bộ, không phải public contract): `GET /api/episodes`, `GET /api/episodes/{id}`, `GET /media/{id}/{output|source}` (Range), `POST /api/jobs`, `GET /api/jobs/{id}/events` (SSE), `POST /api/jobs/{id}/cancel`, `PUT /api/episodes/{id}/glossary`.

An toàn (cho phương án A): bind `127.0.0.1` mặc định; episode được tham chiếu bằng id tra từ danh sách quét, **không** nhận đường dẫn từ client (chặn path traversal); POST kiểm `Origin`/`Host` là localhost (chặn CSRF từ trang web khác gọi vào localhost); subprocess gọi bằng list args, không `shell=True`; URL job phải là youtube.com/youtu.be.

## 6. Lộ trình (mỗi phase = một task contract, một commit, theo profile §7)

| Phase | Nội dung | Phụ thuộc | Giá trị ngay |
|---|---|---|---|
| **WEB-1** Nhập URL + Jobs + Thư viện + player | subcommand `web`; form nhập URL video/playlist → hàng đợi 1 worker, subprocess CLI, log trực tiếp (SSE) + tiến độ stage, hủy, chạy lại, recovery khi restart; quét workspace, trang Thư viện/Episode/Playlist, stream video có Range, bảng câu + tua | ADR ACCEPTED | dùng web làm nguồn vào ngay từ đầu, không cần copy dữ liệu; nghe output + soi câu too_long cho CP9 |
| **WEB-2** Glossary | editor + validate + "dịch lại & chạy tiếp" (job WEB-1) | WEB-1 | vòng sửa tên/xưng hô nhanh |
| WEB-3 *(sau, cần ADR/quyết định riêng)* | sửa câu dịch từng segment → chỉ TTS lại câu đổi (cache TTS đã theo hash text) → normalize/render lại | WEB-2, CP9 | sửa tay câu too_long; **đổi contract `translated.json`** (cờ "đã sửa tay" để `translate --force` không ghi đè) → decision gate |

Required verification mỗi phase (theo profile §4 luật 1 + Test policy): unittest với `TestClient` (mock subprocess) **và** chạy thật: bật `python -m app web`, submit một video ngắn thật qua form, thấy log trực tiếp, hủy giữa chừng rồi chạy lại phải SKIP stage đã xong; `curl -r 0-1023` lên `/media/...` phải trả `206`.

> Sửa đổi 2026-10-17 (HUMAN LEAD): gộp WEB-1 cũ (thư viện/player) và WEB-2 cũ (jobs, nhập URL) thành WEB-1 — web là nơi nhập nguồn YouTube ngay từ phase đầu; glossary thành WEB-2. Boundary mục 0 áp dụng cho WEB-1..2 (nội dung không đổi, chỉ đổi thứ tự).

## 7. Rủi ro

- Parse log để lấy tiến độ dễ gãy khi đổi câu log → đặt tiến độ dạng dòng máy đọc được (vd `@@progress {"stage":..}`) là thay đổi nhỏ trong `run_dub`; quyết khi spec WEB-1.
- Chạy job web song song với lệnh CLI chạy tay trên cùng episode → hai writer. Giảm thiểu: lock file `<episode>/.lock` (cần thay đổi nhỏ ở pipeline — quyết ở WEB-1) hoặc chỉ cảnh báo.
- Tốn thời gian làm UI đẩy lùi CP9 (chất lượng mới là nút thắt thật). Giảm thiểu: dừng sau WEB-1 nếu thấy đủ dùng.
- Máy dev vừa chuyển sang Linux, `.venv` chưa dựng lại → làm trước WEB-1.

## 8. Quyết định cần HUMAN LEAD

| # | Câu hỏi | Khuyến nghị |
|---|---|---|
| D1 | Mô hình triển khai | A — local, `127.0.0.1`; LAN (B) để sau, quyết riêng |
| D2 | Stack + dependency mới `fastapi`, `uvicorn`, `jinja2` (+ `httpx` cho test) dưới extra `web` | đồng ý |
| D3 | Chạy job bằng subprocess CLI, 1 worker | đồng ý |
| D4 | Phạm vi đợt này | WEB-1 → WEB-2 (sau gộp); WEB-3 ADR riêng |
| D5 | Thứ tự so với CP9 | WEB-1 trước (hỗ trợ đánh giá output CP9), rồi CP9 hạng mục 1; WEB-2 xen sau |
| D6 | Governance cho đợt Web | giữ `task` (APPROVE TASK từng phase); hoặc chuyển `boundary` cho WEB-1..3 nếu muốn ít bước duyệt |

Trả lời của HUMAN LEAD (2026-10-17): D1–D5 theo cột khuyến nghị; D6 = `boundary` (mục 0).

## 9. Sửa đổi 2026-10-17 — D1-B (LAN + mật khẩu)

HUMAN LEAD (2026-10-17), sau khi thực tế chạy web trên LAN (`--host 10.8.102.102`): chấp nhận **D1-B ở mức tối thiểu** — được bind ngoài localhost **chỉ khi** bật đăng nhập bằng một mật khẩu duy nhất, lấy từ biến môi trường (không lưu trong file). Làm thành task riêng `WEB-AUTH`, implement **trước** WEB-2 (WEB-2 thêm route ghi file). Không thêm dependency (stdlib `hmac`/`secrets`). Không HTTPS, không nhiều user — chấp nhận rủi ro mật khẩu đi plaintext trên LAN tin cậy.

`WEB-AUTH` **không** nằm trong boundary mục 0 (security model) → cần `APPROVE TASK` cho contract `docs/tasks/WEB-AUTH-password-login.md`.

## 10. Sửa đổi 2026-10-17 — D3: hàng đợi tối đa 2 job song song

HUMAN LEAD (2026-10-17): máy chạy thật là Linux 32 core, Whisper chạy CPU, Ollama ở máy khác — lý do "GPU dùng chung" ở mục 3 không còn đúng cho máy này nhưng vẫn đúng cho máy có GPU. Hàng đợi chạy tối đa `web.max_jobs` job cùng lúc (trần cứng 2), FIFO; job có target trùng với job đang chạy (cùng video, cùng playlist, hoặc tập nằm trong playlist đang chạy) phải chờ, không chạy song song. Mặc định `web.max_jobs` và `whisper.cpu_threads` là `auto`: tính theo CPU/GPU dò được trên **từng máy** lúc chạy (có GPU CUDA → 1 job; CPU ≥ 8 → 2 job; thread Whisper = CPU / 2, trần 12) — máy 32 core ra 2 job × 12 thread. Đặt số cụ thể để ghi đè. Task: `docs/tasks/WEB-PARALLEL-two-workers.md`.

## 11. Sửa đổi 2026-10-17 — mục 10: cùng playlist, khác tập thì chạy song song

HUMAN LEAD (2026-10-17): "hai video cùng playlist cũng có thể chạy song song". Sửa câu "cùng playlist … phải chờ" ở mục 10: target tính **theo tập** (`video:<id>`); job playlist có `items` map được hết sang video_id (qua `<L>__*/playlist.json`) chỉ khoá các tập đó; job không `items`, chưa có `playlist.json` hoặc có index không map được vẫn khoá cả playlist (`playlist:<L>`), chạm mọi job của playlist đó. Job `dub` video X và tập X vẫn chờ nhau. Điều kiện cần: `app/pipeline/playlist.py` ghi `playlist.json` read-modify-write dưới file lock liên tiến trình (`playlist.json.lock`), chỉ thay entry của mình. Task: `docs/tasks/WEB-PARALLEL-PLAYLIST-same-playlist.md`.

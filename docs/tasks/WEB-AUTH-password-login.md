# Task: WEB-AUTH — Web UI: đăng nhập bằng mật khẩu khi mở ra LAN

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 — ngoài boundary ADR-001 mục 0 (security model); quyết định D1-B tối thiểu ở ADR-001 mục 9
- Parallel group: —
- Owned paths: app/web/auth.py (mới), app/web/server.py, app/web/templates/login.html (mới), app/web/templates/base.html, app/cli.py (chỉ `_cmd_web`), app/config.py (chỉ comment `WebConfig`), config.example.yaml (chỉ comment section `web`), tests/test_web_auth.py (mới), tests/test_web_server.py, tests/test_web_cli_config.py, README.md, docs/decisions/WEB-AUTH.md
- Dependencies: WEB-1 (48cc251). WEB-2 phụ thuộc task này.
- Base commit / branch: 2e60f95 / main
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

## Goal

Đặt `DUBBER_WEB_PASSWORD` rồi chạy `$PY -m app web --host <IP LAN>` → mọi trang/API/media/SSE đòi đăng nhập; trang `/login` chỉ có một ô mật khẩu; đăng nhập đúng → cookie phiên ký HMAC 30 ngày; có Đăng xuất. Bind ngoài localhost mà **không** đặt mật khẩu → server từ chối chạy. Bind `127.0.0.1` không đặt mật khẩu → như WEB-1 (không login).

## Scope

- In scope: module `app/web/auth.py` (stdlib); middleware xác thực; `GET/POST /login`, `POST /logout`; trang login; nút Đăng xuất; giới hạn số lần đăng nhập sai; quy tắc khởi động trong `_cmd_web`; test; README; cập nhật comment `WebConfig`/`config.example.yaml` (bỏ câu "không có auth").
- Out of scope: HTTPS/TLS; nhiều user / phân quyền; lưu mật khẩu (hash) trong config; thu hồi phiên phía server (đăng xuất chỉ xoá cookie); CSRF token (đã có kiểm `Origin` + `SameSite=Strict`); dependency mới (`itsdangerous`, `python-multipart`…); mọi thứ ngoài `app/web/`, `app/cli.py`.

## Authority / key decisions

- `docs/adr/ADR-001-web-ui.md` mục 4.1 (D1-B), 5 (an toàn), **9** (quyết định HUMAN LEAD 2026-10-17: task riêng, mật khẩu từ biến môi trường, stdlib, không HTTPS).
- `docs/decisions/WEB-1.md` C6 (middleware kiểm `Host`), A3 (`check_origin`, form parse bằng `parse_qs`).
- Quyết định cục bộ (ORCHESTRATOR):
  - **Bật auth khi và chỉ khi `DUBBER_WEB_PASSWORD` khác rỗng** (bất kể host). Host không phải loopback + không có mật khẩu → `_cmd_web` in lỗi tiếng Việt (hướng dẫn `export DUBBER_WEB_PASSWORD=...`), exit 2, không bind.
  - **Phiên stateless**: khoá ký = `sha256(b"dubber-web-session\0" + password.encode())`; cookie = `"<expiry_unix>.<hex hmac_sha256(key, str(expiry_unix))>"`. Đổi mật khẩu ⇒ mọi phiên cũ mất hiệu lực; restart server không đăng xuất ai. Không lưu state phiên trên đĩa.
  - Tên biến môi trường là hằng số trong `auth.py`, không phải key config (mật khẩu không bao giờ nằm trong file).

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/web/auth.py` (mới, stdlib, không import fastapi) | hằng số, ký/kiểm cookie, so mật khẩu, rate limiter, kiểm `next` |
| `app/web/server.py` | `create_app(..., password: str \| None = None)`; middleware auth (đặt **sau** `check_host`, tức chạy sau khi Host hợp lệ); route login/logout; `run(..., password)` |
| `app/web/templates/login.html` (mới) | form `POST /login`: `password` (type=password, autofocus), hidden `next`; hiện lỗi; không extend nav |
| `app/web/templates/base.html` | nút "Đăng xuất" (form `POST /logout`) chỉ khi auth bật (truyền biến qua `templates.env.globals["auth_enabled"]`) |
| `app/cli.py` `_cmd_web` | đọc `os.environ.get(PASSWORD_ENV)`; quy tắc khởi động; thay câu cảnh báo cũ: auth bật + bind LAN → in `[web] Đăng nhập bằng mật khẩu đang BẬT; kết nối là HTTP (không mã hoá).` |
| `app/config.py`, `config.example.yaml` | chỉ sửa comment: mở LAN cần `DUBBER_WEB_PASSWORD` (ADR-001 mục 9) |
| `tests/test_web_auth.py` (mới), `tests/test_web_server.py`, `tests/test_web_cli_config.py` | xem Required verification |
| `README.md` | mục "Web UI (local)": dùng trên LAN + mật khẩu + giới hạn HTTP |
| `docs/decisions/WEB-AUTH.md` | log quyết định; mục A = contract cho WEB-2 (route mới mặc định được bảo vệ) |

### Interface — `app/web/auth.py`

```python
PASSWORD_ENV = "DUBBER_WEB_PASSWORD"
COOKIE_NAME = "dubber_session"
SESSION_SECONDS = 30 * 24 * 3600
MAX_FAILURES = 5                 # mỗi IP
FAILURE_WINDOW_SECONDS = 300     # quá MAX_FAILURES lần sai trong cửa sổ -> khoá tới khi cửa sổ trôi qua
PUBLIC_PATHS = ("/login",)       # + mọi path bắt đầu "/static/"

def is_loopback(host: str) -> bool                      # "127.0.0.1", "localhost", "::1", 127.x.x.x
def check_password(candidate: str, password: str) -> bool   # hmac.compare_digest trên bytes utf-8
def make_session(password: str, *, now: float | None = None) -> str
def verify_session(cookie: str | None, password: str, *, now: float | None = None) -> bool
    # sai format / chữ ký sai (compare_digest) / hết hạn / expiry > now + SESSION_SECONDS + 60 -> False
def safe_next(value: str | None) -> str
    # chỉ nhận path tương đối bắt đầu "/" và không bắt đầu "//" hoặc "/\\", không có scheme; ngược lại "/"

class LoginThrottle:
    def __init__(self, *, max_failures: int = MAX_FAILURES, window: float = FAILURE_WINDOW_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None
    def blocked(self, client: str) -> float          # số giây còn bị khoá, 0 nếu không
    def record_failure(self, client: str) -> None
    def reset(self, client: str) -> None             # khi đăng nhập đúng
    # threading.Lock; dọn mục quá hạn khi gọi
```

### Hành vi bắt buộc — server

- `password` None/rỗng → không middleware auth, không route `/login`/`/logout` (404), hành vi WEB-1 giữ nguyên **byte-for-byte** (test cũ không sửa vẫn PASS).
- Auth bật, request không có cookie hợp lệ, path không public:
  - `GET`/`HEAD` có `Accept` chứa `text/html` → `303` tới `/login?next=<path+query đã urlencode>`.
  - Còn lại (API, `/media`, SSE, POST) → `401` JSON `{"detail": "Cần đăng nhập."}`.
- `GET /login`: đã đăng nhập → 303 tới `safe_next(next)`; chưa → trang login.
- `POST /login` (form urlencoded, parse bằng `parse_qs` như `parse_job_request`): gọi `check_origin`; IP (`request.client.host`) đang bị khoá → 429 trang login báo "thử lại sau N giây"; sai → `record_failure`, 401 trang login "Sai mật khẩu" (không tiết lộ gì thêm); đúng → `reset`, `303` tới `safe_next(next)` + `Set-Cookie: dubber_session=...; Max-Age=2592000; Path=/; HttpOnly; SameSite=Strict` (không `Secure` — HTTP).
- `POST /logout`: `check_origin`; xoá cookie (`Max-Age=0`), 303 `/login`.
- Thứ tự middleware: `check_host` (400) trước, auth sau. `check_origin` hiện có giữ nguyên trên mọi POST/PUT.
- Không log mật khẩu, không đưa mật khẩu vào job JSON / `command` / env của subprocess (`JobManager` không đổi).
- Route WEB-2 thêm sau này được bảo vệ mặc định (middleware theo path, không phải decorator từng route) — ghi vào decision log mục A.

### Hành vi bắt buộc — `_cmd_web`

| Host | `DUBBER_WEB_PASSWORD` | Kết quả |
|---|---|---|
| loopback | không đặt / rỗng | chạy, không auth (như WEB-1) |
| loopback | đặt | chạy, auth bật |
| khác | không đặt / rỗng | `[web] LỖI: bind <host> cần mật khẩu — đặt biến môi trường DUBBER_WEB_PASSWORD rồi chạy lại.` exit 2 |
| khác | đặt | chạy, auth bật, in dòng cảnh báo HTTP |

### Điểm phải escalate

- Cần dependency mới, hoặc cần sửa ngoài Owned paths → dừng, hỏi.
- Starlette/FastAPI bản đang cài không cho đặt middleware đúng thứ tự (host trước auth) → báo, không tự đổi cơ chế.

## Acceptance Criteria

1. Không đặt mật khẩu + bind `127.0.0.1` → web như WEB-1, `/login` 404; toàn bộ test WEB-1 PASS không sửa.
2. Không đặt mật khẩu + `--host` không phải loopback → exit 2 với hướng dẫn tiếng Việt, không mở cổng.
3. Auth bật: trang HTML chưa đăng nhập → 303 `/login?next=...`; API/`/media`/SSE/POST → 401; `/static/app.css` → 200.
4. Mật khẩu đúng → cookie `HttpOnly`, `SameSite=Strict`, `Max-Age=2592000`, redirect về `next`; sau đó mọi trang/API/media (Range 206)/SSE dùng được.
5. `next=//evil.example` hoặc `next=https://evil.example` → redirect `/`.
6. Sai mật khẩu → 401; sai lần thứ 6 trong 5 phút từ cùng IP → 429 (kể cả khi nhập đúng); đúng → bộ đếm reset.
7. Cookie bị sửa một ký tự, hết hạn, hoặc ký bằng mật khẩu cũ (đổi env rồi restart) → coi như chưa đăng nhập.
8. Đăng xuất → cookie bị xoá, request sau → 303/401. `POST /login`/`/logout` với `Origin` lạ → 403.
9. Mật khẩu không xuất hiện trong log server, job JSON, `command`, HTML.

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS. Case mới:
  - `tests/test_web_auth.py` (stdlib): `check_password`; `make_session`/`verify_session` (đúng, sửa chữ ký, sửa expiry, hết hạn, khác mật khẩu, rác, None); `safe_next` (`/ep/x?y=1` giữ; `//a`, `/\a`, `https://a`, `javascript:`, rỗng → `/`); `LoginThrottle` với clock giả; `is_loopback`. — AC5–AC7.
  - `tests/test_web_server.py`: lớp test mới với `create_app(..., password="pw")` — AC3, AC4 (cookie attrs, Range 206 có cookie), AC5, AC6, AC7, AC8; app không password vẫn qua test cũ — AC1.
  - `tests/test_web_cli_config.py`: 4 dòng bảng `_cmd_web` (mock `app.web.server.run` + `os.environ`) — AC1, AC2.
- **Chạy thật** (bắt buộc):
  1. `env -u DUBBER_WEB_PASSWORD $PY -m app web --workspace output --host 10.8.102.102` → exit 2, `ss -ltnp` không có cổng.
  2. `DUBBER_WEB_PASSWORD=<pw> $PY -m app web --workspace output --host 10.8.102.102` nền (port theo `config.yaml` local). Từ chính máy: `curl -si http://10.8.102.102:<port>/library -H 'Accept: text/html'` → 303 `/login?next=%2Flibrary`; `curl -si .../api/jobs` → 401; `.../static/app.css` → 200.
  3. `curl -si -c jar -d 'password=sai' .../login` → 401; `-d 'password=<pw>&next=/library'` → 303 + `Set-Cookie` đủ thuộc tính; `curl -b jar .../api/jobs` → 200; `curl -b jar -r 0-1023 -o /dev/null -w '%{http_code} %{size_download}' .../media/<key>/source` → `206 1024`; `curl -b jar -N .../api/jobs/<id>/events` có dữ liệu (job cũ bất kỳ).
  4. 6 lần sai liên tiếp → lần 6 là 429.
  5. Sửa 1 ký tự cookie trong `jar` → 401. `POST /logout` với cookie → cookie `Max-Age=0`.
  6. `grep -r "<pw>" output/.web/` và log server → không có.
  7. `env -u DUBBER_WEB_PASSWORD $PY -m app web --workspace output` (127.0.0.1) → `/library` 200 không login, `/login` 404.
  8. Trình duyệt (nếu có) hoặc `curl` HTML trang `/login` (ô password, `next` ẩn) và nút Đăng xuất trong `base.html`; ghi rõ cách đã kiểm.

## Manual test checklist (Tech Lead)

Chạm **security model** (thêm xác thực, cho phép bind LAN) — đã quyết ở ADR-001 mục 9. Không chạm database / public API.

- [ ] Từ điện thoại/máy khác trong LAN mở `http://10.8.102.102:<port>` → trang login; nhập sai rồi đúng; xem video tua được; xem log job trực tiếp.
- [ ] Đăng xuất → quay lại trang login.
- [ ] Restart server cùng mật khẩu → vẫn đăng nhập; đổi mật khẩu → phải đăng nhập lại.

## Result

- Main changes: `app/web/auth.py` (stdlib: HMAC cookie stateless, `safe_next`, `LoginThrottle`, `is_loopback`); `server.py` middleware `require_login` theo path (đăng ký trước `check_host` → Host kiểm trước), `GET/POST /login`, `POST /logout`, `create_app`/`run` nhận `password`; `login.html`, nút Đăng xuất ở `base.html`; `_cmd_web` đọc `DUBBER_WEB_PASSWORD`, bind LAN không mật khẩu → exit 2; README; comment config.
- Tests: 508 OK (484 + 24 mới: `tests/test_web_auth.py` 13 case, `TestServerAuth`, bảng khởi động `_cmd_web`), ORCHESTRATOR chạy lại độc lập.
- Chạy thật: mật khẩu thử qua env, bind 10.8.102.102 port 8099 (8081 đang bị server WEB-1 cũ chiếm). Không env + LAN → exit 2; HTML → 303 `/login?next=%2Flibrary`, API 401, static 200; sai 401, đúng 303 + cookie `HttpOnly; SameSite=strict; Max-Age=2592000`; có cookie: API 200, Range `206 1024`, SSE có dữ liệu; lần sai thứ 6 → 429 (cả khi đúng); restart cùng mật khẩu giữ phiên; sửa cookie → 401; logout `Max-Age=0`; Origin lạ 403; mật khẩu không có trong `.web/` và log; loopback không env → không auth, `/login` 404.
- Review: không blocking. Ghi nhận: test WEB-1 `test_flag_overrides_config_and_warns_on_non_loopback` được viết lại vì luật khởi động đổi theo contract (không che lỗi); SSE với TestClient treo → stream kiểm bằng curl.
- Important findings / decisions: server WEB-1 cũ (pid 1371697, bind 10.8.102.102:8081, KHÔNG auth) vẫn đang chạy — HUMAN LEAD cần tắt và chạy lại bằng code mới.
- Known limitations: HTTP không mã hoá; logout không thu hồi phía server; throttle trong RAM, theo `client.host` (không hỗ trợ reverse proxy); JS WEB-1 (fetch/EventSource) gặp 401 khi phiên hết hạn chỉ báo lỗi, không tự chuyển `/login`; chưa kiểm bằng trình duyệt thật.
- PR: commit thẳng `main` (profile §5).

# WEB-AUTH — Các quyết định nhỏ khi triển khai

Task: `docs/tasks/WEB-AUTH-password-login.md`. Mục **[CẦN DUYỆT]** là chỗ Opus nên xem lại.

---

## A. Contract với WEB-2

- Auth là middleware theo path (`require_login` trong `create_app`), không phải decorator từng route:
  **mọi route thêm sau được bảo vệ mặc định** khi `password` được truyền. Ngoại lệ chỉ `auth.PUBLIC_PATHS` (`/login`) và `/static/*`.
- Chưa đăng nhập: `GET`/`HEAD` có `Accept: text/html` -> 303 `/login?next=...`; còn lại -> 401 `{"detail": "Cần đăng nhập."}`.
  Client JS của WEB-2 (fetch) nên xử lý 401 bằng cách chuyển tới `/login`.
- Mọi `POST/PUT` mới vẫn phải tự gọi `check_origin(request)` (không đổi so với WEB-1).
- `create_app(..., password=None)` và `run(..., password=None)`: không mật khẩu thì hành vi y WEB-1, test cũ không phải sửa.
- Template mới extend `base.html` tự có nút Đăng xuất (global Jinja `auth_enabled`).

## B. Quyết định

- **B1.** Thứ tự middleware: Starlette chạy middleware đăng ký SAU ở vòng NGOÀI, nên `require_login` được đăng ký TRƯỚC `check_host` trong code
  để `check_host` (400) chạy trước. Có test `test_host_checked_before_auth`.
- **B2.** `LoginThrottle.blocked` khoá khi đã có `>= max_failures` lần sai trong cửa sổ (5 lần sai, lần thứ 6 -> 429, kể cả nhập đúng).
  Lần bị khoá không được ghi thêm nên khoá tự hết khi lần sai cũ nhất trôi khỏi cửa sổ. Bộ đếm nằm trong RAM: restart server là reset.
- **B3.** `_cmd_web` đọc mật khẩu trước khi gọi `run`, nhưng sau kiểm import extra `web` (thiếu extra vẫn exit 2 với hướng dẫn cài).
  `app.web.auth` là stdlib nên import ở đầu `_cmd_web` an toàn.
- **B4.** Cảnh báo "Đăng nhập bằng mật khẩu đang BẬT; kết nối là HTTP" chỉ in khi bind ngoài loopback (loopback + mật khẩu thì không in).
- **B5.** `test_flag_overrides_config_and_warns_on_non_loopback` của WEB-1 (bind `0.0.0.0` không mật khẩu) mâu thuẫn quy tắc mới, nên được viết lại
  thành `test_flag_overrides_config` + `test_startup_rule_table` (đúng yêu cầu "4 dòng bảng _cmd_web"; thực tế 6 dòng, thêm mật khẩu rỗng).
- **B6.** [CẦN DUYỆT] Chạy thật: cổng `8081` (config.yaml local) đang bị một server WEB-1 cũ (không auth, bind 10.8.102.102) chiếm, tôi không tắt nó
  mà chạy thử ở `--port 8099`. Server cũ này vẫn chạy code không có auth — HUMAN LEAD cần restart sau khi duyệt.
- **B7.** SSE không test bằng TestClient (stream job không kết thúc sẽ treo); test chỉ kiểm job lạ -> 404 sau đăng nhập, stream thật kiểm bằng curl.

## C. Giới hạn đã biết

- HTTP không mã hoá: mật khẩu và cookie đi dạng rõ trong LAN. Đăng xuất chỉ xoá cookie, không thu hồi phía server.
- Throttle theo `request.client.host`; sau reverse proxy mọi client có cùng IP (chưa hỗ trợ `X-Forwarded-For`).

# WEB-POLISH — quyết định (pha 1)

## A. Contract với pha 2 (glossary.html, playlist.html, glossary.js)

- `app.css` đã style sẵn mọi thẻ chung: `button` (secondary mặc định), `main button[type="submit"]`, `#save`, `#redub` và `.btn-primary` (primary). Pha 2 chỉ cần thêm `class="btn-primary"` cho nút chính và bọc nhóm nút trong `<div class="toolbar">`.
- Class dùng chung mới: `.toolbar` (hàng nút/checkbox), `.badges` (hàng badge), `.meta` (dòng mô tả phụ, màu phụ), `.muted`.
- Pha 2 (xong): glossary.html (form `.card`, `.toolbar`, `btn-primary` cho Lưu và Dịch lại, `.meta`) và playlist.html (`.meta`); glossary.js không đổi. CSS tạm `#save`/`#redub` đã bỏ.

## B. Quyết định

- Token ở `:root`: bg/surface/surface-2/border/text/text-muted, một accent xanh dương trầm (`--accent`, `-hover`, `-soft`), cặp trạng thái ok/warn/error/info/neutral (`--x`, `--x-bg`), log, media, spacing 4/8/12/16/24. Không còn mã màu ngoài `:root` và khối dark.
- Dark mode: `@media (prefers-color-scheme: dark)` ghi đè token + `color-scheme: light dark`. Tương phản chữ chính: #1d2330/#ffffff (~15:1) và #e6e9ef/#1c2028 (~13:1) — ước tính, chưa đo bằng công cụ.
- Badge: mỗi `.st-*` đặt `--b-fg/--b-bg`; `.badge` và `td.stage` dùng chung (desktop ô stage chỉ đổi màu chữ ✓/·, mobile thành pill như WEB-MOBILE).
- Nav: đánh dấu trang hiện tại bằng `aria-current="page"` từ `request.url.path` trong `base.html` (không đổi route/server). `/ep/*` và `/pl/*` tính là "Thư viện". Nút đăng xuất đổi `style` inline thành class `.nav-logout`.
- Markup đổi: job.html (nhóm nút `.toolbar`, dòng `.meta`), episode.html (`.badges`, `.meta`, `.toolbar` cho 2 checkbox), jobs.html (`btn-primary`). Id/class JS cần giữ nguyên; JS không sửa.
- Test: không cần đổi (589 test OK).

## C. Kiểm tra

- Server tạm 127.0.0.1:8099 trên workspace `output`: /jobs, /library, /static/app.css, trang tập, glossary, playlist, job đều 200 (login 404 vì không bật mật khẩu — template login được test auth phủ).
- Không có trình duyệt: kiểm tra trực quan (desktop, 375px, dark mode, layout 2 cột ≥1000px) dành cho HUMAN LEAD.

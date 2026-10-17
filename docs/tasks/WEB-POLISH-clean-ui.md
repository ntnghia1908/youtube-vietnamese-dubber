# Task: WEB-POLISH — Giao diện web gọn gàng, chỉn chu hơn

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 (HUMAN LEAD: "APPROVE TASK CP9-B WEB-POLISH") — ngoài boundary ADR-001 mục 0 (giống WEB-MOBILE)
- Parallel group: P1 (cùng CP9-A) — chia 2 pha
- Owned paths: `app/web/static/app.css`, `app/web/templates/*.html`, `app/web/static/*.js` (chỉ khi cần đổi class/markup), `tests/test_web_*.py` (chỉ khi test assert đúng chuỗi HTML bị đổi), `docs/decisions/WEB-POLISH.md`
- Dependencies: WEB-MOBILE, fix(web) 16b3b3e (layout video trái / danh sách câu phải); chạy SAU CP9-A nếu CP9-A thêm template glossary playlist (để chỉnh luôn trang đó)
- Base commit / branch: 1fafa02 / worktree (song song với CP9-A)
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`.

Chạy song song với CP9-A (HUMAN LEAD 2026-10-17 "chạy luôn WEB-POLISH"), nên chia hai pha:

- **Pha 1 (song song CP9-A, worktree riêng):** `app/web/static/app.css`, `app/web/templates/base.html`, `login.html`, `jobs.html`, `job.html`, `library.html`, `episode.html`, `app/web/static/{episode,job,jobs}.js` (chỉ khi cần), `tests/test_web_*.py` (chỉ assert HTML đổi), `docs/decisions/WEB-POLISH.md`. **KHÔNG** sửa `glossary.html`, `playlist.html`, `glossary.js` (CP9-A đang sửa).
- **Pha 2 (sau khi CP9-A merge, cùng implementer):** chỉnh markup/class cho `glossary.html`, `playlist.html` (gồm trang glossary playlist mới của CP9-A).

## Goal

HUMAN LEAD 2026-10-17: "UI của trang web còn khá thô. Tôi không cần quá màu mè. Trang web nên đơn giản nhưng hãy chỉnh chu thêm." Giữ nguyên chức năng và cấu trúc trang; làm lại phần trình bày cho gọn gàng, nhất quán, dễ đọc trên desktop lẫn điện thoại.

## Scope

- In scope: CSS (typography, khoảng cách, màu trung tính, bảng, nút, form, badge trạng thái, thanh nav); sắp lại markup nhỏ trong template (nhóm nút, tiêu đề phụ, card) khi cần cho bố cục; dark mode theo `prefers-color-scheme`.
- Out of scope: thêm/bớt tính năng, route, API; framework CSS/JS hoặc font ngoài (không CDN, không dependency — chạy LAN, có thể offline); đổi logic JS.

## Authority / key decisions

- `docs/adr/ADR-001-web-ui.md` (FastAPI + Jinja2, không build step, không JS framework).
- `docs/decisions/WEB-MOBILE.md` (breakpoint 640px, bảng → thẻ, video sticky trên mobile, `[hidden]` không bị đè, chạm 44px).
- fix(web) 16b3b3e: ≥1000px trang tập là grid video trái / danh sách câu phải, danh sách cuộn trong `#segments-box`; checkbox `#auto-scroll`. Giữ các id/class mà JS dùng.

## Implementation approach

### Hướng thiết kế (bắt buộc)

- Một bộ design token ở `:root` (màu nền, bề mặt, viền, chữ chính/phụ, accent duy nhất — xanh dương trầm, màu trạng thái ok/warn/error/info dịu) + override cho dark mode (`@media (prefers-color-scheme: dark)`). Toàn bộ CSS dùng token, không mã màu rời.
- Font hệ thống (`system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`), cỡ chữ gốc 15–16px, line-height ~1.5, thang tiêu đề rõ ràng; số (thời lượng, giây, tempo) dùng `font-variant-numeric: tabular-nums`.
- Nav: thanh mảnh, tên app bên trái, link + đăng xuất bên phải, đánh dấu trang hiện tại (thêm biến template nếu cần, không đổi route).
- Bảng: viền ngang mảnh thay lưới ô, header chữ nhỏ màu phụ, hover hàng, hàng `active` nổi bật bằng nền accent nhạt + vạch trái; ô dài xuống dòng gọn.
- Badge trạng thái: pill nền nhạt + chữ đậm cùng tông; cột stage của thư viện thành chấm/✓ gọn.
- Nút: kiểu primary (accent) cho hành động chính (Gửi job, Lưu, Dịch lại & chạy tiếp), secondary (viền) cho còn lại, trạng thái hover/focus-visible/disabled rõ ràng.
- Form/textarea: bo góc nhẹ, focus ring accent; editor glossary dùng font monospace.
- Card cho từng khối (form tạo job, player, glossary) với bóng rất nhẹ hoặc chỉ viền; khoảng cách theo thang 4/8/12/16/24px.
- Log job: nền tối, monospace, giữ hành vi stick-to-bottom.
- Mobile (≤640px): giữ toàn bộ quyết định WEB-MOBILE; chỉ áp style mới.

### File cần sửa

| Path | Việc cần làm |
|---|---|
| `app/web/static/app.css` | Viết lại theo hướng trên (giữ selector JS cần: `#segments`, `#segments-box`, `.player`, `.player-col`, `.episode-layout`, `tr.active`, `[hidden]`, `--player-h`) |
| `app/web/templates/*.html` | Chỉnh markup nhỏ: class nút primary/secondary, nhóm toolbar, mô tả phụ; nav đánh dấu trang hiện tại |
| `docs/decisions/WEB-POLISH.md` | Token, quyết định dark mode, ảnh chụp/ghi chú kiểm tra |

### Điểm phải escalate

- Cần font/icon/thư viện ngoài, hoặc đổi luồng thao tác/chức năng.

## Acceptance Criteria

1. Mọi trang (login, jobs, job, library, playlist, episode, glossary) dùng chung token; không còn mã màu rời ngoài `:root`/dark override.
2. Dark mode theo hệ thống đọc được (tương phản chữ ≥ 4.5:1 cho chữ chính).
3. Không mất chức năng: test web hiện có PASS; JS (tua theo câu, tự cuộn, lọc too_long, đổi output/source, editor glossary, log job) chạy như trước.
4. Mobile 375px không cuộn ngang; desktop ≥1000px trang tập giữ layout hai cột.

## Required verification

- `$PY -m unittest discover -s tests` PASS (sửa assert HTML chỉ khi chuỗi đổi do markup, ghi lý do).
- Chạy thật: khởi động server tạm (`$PY -m app web --workspace output --port 8099`, không đụng server LAN), `curl` từng trang (có cookie nếu bật mật khẩu) → 200, CSS tải được; không có trình duyệt trên máy Linux nên ghi rõ phần kiểm tra trực quan dành cho HUMAN LEAD.

## Manual test checklist (Tech Lead)

- Không chạm database / security model / public API.
- [ ] HUMAN LEAD xem desktop: thư viện, playlist, trang tập (video trái, câu phải, tự cuộn không kéo trang), glossary, jobs.
- [ ] HUMAN LEAD xem điện thoại: như WEB-MOBILE, không vỡ bố cục.
- [ ] Dark mode (nếu máy/điện thoại đang bật).

## Result

- Main changes: `app/web/static/app.css` viết lại theo design token ở `:root` + override dark (`prefers-color-scheme`): nav mảnh có `aria-current`, card, form/focus ring, nút `.btn-primary`/secondary, bảng viền ngang + hover + hàng active, badge pill, `.toolbar`, `.meta`, log tối; giữ breakpoint/selector WEB-MOBILE và layout hai cột ≥1000px. Template: `base.html` (trang hiện tại, `.nav-logout`), `jobs.html`, `job.html`, `episode.html`, `glossary.html` (form `.card`, `.toolbar`, nút chính `btn-primary`), `playlist.html`.
- Tests: toàn suite 602 OK (implementer + ORCHESTRATOR chạy lại sau rebase lên CP9-A), không sửa assert nào.
- Chạy thật: server tạm 127.0.0.1:8099, `curl` /jobs, /jobs/<id>, /library, /pl/<key>, /pl/<key>/glossary, /ep/<key>, /ep/<key>/glossary, /static/app.css → 200; grep không còn mã màu ngoài `:root`/dark. Không có trình duyệt trên máy Linux → kiểm tra trực quan dành cho HUMAN LEAD.
- Review: ORCHESTRATOR đọc diff template + kiểm token màu, không blocking.
- Important findings / decisions: `docs/decisions/WEB-POLISH.md`. Chạy song song CP9-A theo hai pha (pha 2 sau khi CP9-A merge, cùng implementer, cùng worktree).
- Known limitations: tương phản dark mode mới ước tính bằng tính toán; `login.html` không đổi markup (chỉ áp CSS chung).
- PR: — (commit thẳng `main`).

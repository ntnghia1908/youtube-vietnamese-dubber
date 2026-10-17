# Task: WEB-MOBILE — Web UI dùng tốt trên điện thoại (responsive)

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: single-agent
- Implementer: — (single-agent: chỉ CSS + template, không đổi logic Python/API)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 (HUMAN LEAD: "APPROVE TASK WEB-MOBILE") — ngoài boundary ADR-001 mục 0
- Parallel group: —
- Owned paths: `app/web/static/app.css`, `app/web/templates/*.html`, `app/web/static/episode.js` (chỉ nếu cần cho player sticky), `tests/test_web_*.py` (chỉ khi test assert đúng chuỗi HTML bị đổi), `docs/decisions/WEB-MOBILE.md`
- Dependencies: WEB-1, WEB-2, WEB-AUTH, WEB-PARALLEL (đã commit `e3c3be7`)
- Base commit / branch: e3c3be7 / main
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

## Goal

HUMAN LEAD dùng điện thoại nhiều hơn laptop. Mọi trang Web UI (login, Jobs, Job, Thư viện, Playlist, Episode, Glossary) đọc và thao tác được trên màn hình ~360–430px: không cuộn ngang cả trang, chữ không phải zoom, nút/link bấm được bằng ngón tay. Trên laptop giao diện giữ như cũ.

## Scope

- In scope:
  - Media query `@media (max-width: 640px)` trong `app.css`. Giao diện desktop không đổi (mọi rule mới nằm trong media query, trừ các sửa vô hại như `box-sizing`, `max-width:100%` cho input/textarea).
  - Form và input: bỏ ràng buộc độ rộng cứng (`size="70"`, `cols="100"`) bằng CSS `width:100%`. Label xếp dọc trên mobile. Input `font-size ≥ 16px` để iOS không tự zoom.
  - Bảng → dạng thẻ (card) xếp dọc trên mobile. Mỗi `<td>` có `data-label` để hiện tên cột bằng `td::before { content: attr(data-label) }`. Áp dụng cho: Jobs, Playlist, Episode `#segments`.
  - Thư viện: trên mobile mỗi tập là một thẻ gồm tiêu đề, thời lượng và một dòng badge stage gọn (thay cho 6 cột ✓/·). Cho phép thêm markup chỉ hiện trên mobile (vd `<span class="mobile-only">`), không đổi dữ liệu server truyền vào.
  - Episode: video **sticky** ở đầu màn hình trên mobile, để danh sách câu cuộn bên dưới mà vẫn thấy video. Kiểm `scrollIntoView` của câu đang phát không đẩy video khỏi màn hình (`scroll-margin-top` hoặc chỉnh JS nếu cần).
  - Nav: link/nút cao ≥ 44px, không tràn dòng. Log job (`.log`) giảm chiều cao trên mobile. `<code>` lệnh dài được ngắt dòng (`word-break`).
  - Ghi decision ngắn `docs/decisions/WEB-MOBILE.md`.
- Out of scope:
  - Thêm framework/thư viện CSS/JS (không dependency mới), build step, PWA/manifest, dark mode.
  - Đổi route, API, logic Python, dữ liệu server truyền vào template.
  - Thiết kế lại giao diện desktop.
  - Tính năng mới (sửa câu dịch từng segment = WEB-3).

## Authority / key decisions

- HUMAN LEAD 2026-10-17 (chat): "trang web cần hỗ trợ giao diện cho điện thoại tôi sử dụng điện thoại nhiều hơn laptop".
- ADR-001: "mobile app" ngoài phạm vi. Task này **không** phải mobile app: chỉ làm responsive cho Web UI có sẵn, không đổi kiến trúc → S1, không chạm decision gate. Truy cập từ điện thoại qua LAN đã có từ WEB-AUTH (ADR-001 mục 9).
- `base.html` và `login.html` đã có `<meta name="viewport">`.
- CSS thuần trong `app.css` (25 dòng hiện tại), không dependency.

## Implementation approach

- `app.css`: thêm `*, *::before, *::after { box-sizing: border-box; }`, `input, select, textarea { max-width: 100%; }`. Thêm khối `@media (max-width: 640px)` cho: `main` padding 0.75rem; `form.card label { display:block }`; input/select/textarea `width:100%; font-size:16px`; bảng card hóa (`table, thead, tbody, tr, td { display:block }`, `thead { display:none }`, `tr` thành thẻ có border/margin, `td { border:none }`, `td::before` in đậm `attr(data-label)`); `.player { position: sticky; top: 0; z-index: 1; background:#000 }`; `video` max-height ~40vh; `.log` cao ~16rem; nút `min-height: 44px`.
- Template: thêm `data-label="…"` cho từng `<td>` ở `jobs.html`, `playlist.html`, `episode.html`. `library.html`: trên mobile ẩn các cột stage và hiện một ô tóm tắt (markup `mobile-only`/`desktop-only`).
- Glossary: `textarea` `width:100%`, tăng `rows` hợp lý trên mobile bằng CSS `height`. Nút Lưu / Dịch lại xếp được trên một màn hình.
- Không đổi id/class mà JS (`jobs.js`, `job.js`, `episode.js`, `glossary.js`) đang dùng. `episode.js` lọc `r.hidden`, nên CSS mobile không được đè `[hidden]` (giữ `tr[hidden] { display:none }`).

## Acceptance Criteria

1. Ở viewport 375×812, không trang nào (login, `/jobs`, `/jobs/<id>`, `/library`, `/pl/<key>`, `/ep/<key>`, `/ep/<key>/glossary`) có cuộn ngang toàn trang (`document.documentElement.scrollWidth <= window.innerWidth`).
2. Form tạo job dùng được trên mobile: ô URL rộng hết màn hình, label xếp dọc, input font ≥ 16px.
3. Bảng Jobs / Playlist / segments hiện dạng thẻ có nhãn cột trên mobile. Ở ≥ 1024px vẫn là bảng như cũ.
4. Episode trên mobile: video dính ở đầu khi cuộn danh sách câu. Bấm một câu thì tua video. Lọc "Chỉ hiện câu too_long" vẫn ẩn đúng các thẻ.
5. Glossary trên mobile: sửa được text, bấm Lưu và "Dịch lại & chạy tiếp" mà không phải zoom.
6. Desktop (≥ 1024px) nhìn không đổi so với `e3c3be7` (so ảnh chụp/xem tay trên laptop).
7. Không thêm dependency. Id/class mà JS dùng giữ nguyên.

## Required verification

- `.venv/bin/python -m unittest discover -s tests` — toàn bộ test PASS (nếu test assert chuỗi HTML bị đổi thì sửa assert cho đúng markup mới, không xóa test).
- Kiểm tự động AC1 tạm thời: máy này không có headless browser (không chromium/playwright). Thay bằng kiểm tĩnh: template không còn `size=`/`cols=` gây tràn, và mọi `<td>` ở 3 bảng card hóa có `data-label`. Ghi rõ trong Result là AC1–5 chưa kiểm bằng trình duyệt.
- Restart server LAN (theo memory: `kill <pid>`, không `pkill -f`) để HUMAN LEAD mở trên điện thoại.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract → manual test là điểm danh sau automated verification, nhưng là cách duy nhất kiểm AC1–6 thật.

- [ ] Điện thoại: đăng nhập, `/jobs` tạo job (không cần chạy hết, có thể hủy), xem `/jobs/<id>` log.
- [ ] Điện thoại: `/library` → playlist → tập Ocean Girl → xem video, cuộn câu (video dính trên), bấm câu để tua, lọc too_long.
- [ ] Điện thoại: mở glossary một tập, sửa một dòng, Lưu.
- [ ] Laptop: các trang trên nhìn như cũ.

## Result

- Main changes: `app/web/static/app.css` (rule chung + khối `@media (max-width: 640px)`); `data-label`/`title-cell` cho `jobs.html`, `playlist.html`, `episode.html`, `library.html`; `episode.js` thêm biến `--player-h` cho player sticky.
- Tests: `.venv/bin/python -m unittest discover -s tests` → 566 test OK. Không test nào assert markup bị đổi.
- Review: single-agent. Kiểm trên server LAN đang chạy (đã đăng nhập bằng curl): `/static/app.css` có khối WEB-MOBILE; `/jobs`, `/library`, `/pl/…`, `/ep/…`, `/ep/…/glossary`, `/jobs/<id>` trả 200 với markup mới (vd 301 ô `data-label="Dịch"` ở trang tập).
- Important findings / decisions: `docs/decisions/WEB-MOBILE.md`. Không restart server (B3).
- Manual test: HUMAN LEAD 2026-10-17 xác nhận trên điện thoại: "Giao diện điện thoại đã ổn".
- Known limitations: không có kiểm tự động bằng trình duyệt (máy không có headless browser); AC1–6 dựa vào manual test. Selector `:has()` cho label checkbox cần Safari ≥ 15.4 / Chrome ≥ 105; trình duyệt cũ hơn chỉ xếp checkbox mỗi dòng một cái.
- PR: — (commit thẳng `main` khi HUMAN LEAD đồng ý).

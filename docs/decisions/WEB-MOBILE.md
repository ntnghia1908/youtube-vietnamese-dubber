# WEB-MOBILE — quyết định triển khai

Task: `docs/tasks/WEB-MOBILE-responsive.md`.

## A. Contract với task sau

- Breakpoint mobile duy nhất: `@media (max-width: 640px)` trong `app/web/static/app.css`. Desktop chỉ nhận ba rule chung vô hại: `box-sizing: border-box`, `max-width: 100%` cho input/select/textarea, `overflow-wrap` cho `<code>`.
- Bảng nào cần card hóa trên mobile: mỗi `<td>` thêm `data-label="<tên cột>"`. Ô tiêu đề dùng `class="title-cell"` (in đậm, không nhãn). Ô stage của Thư viện dùng `class="stage"` + `title="<stage>"` sẵn có → thành badge "tên ✓". Template mới có bảng phải theo quy ước này.
- `[hidden] { display: none !important; }` là rule toàn cục: card hóa (`display:block`) không được đè thuộc tính `hidden` mà JS dùng để lọc (episode.js "Chỉ hiện câu too_long").
- Player trang Episode dính đầu màn hình trên mobile. `episode.js` ghi chiều cao player vào biến CSS `--player-h` để `scroll-margin-top` của câu đang phát không nằm dưới video.

## B. Quyết định nhỏ

- B1. Card hóa bằng CSS + `data-label` thay vì sinh markup riêng cho mobile: một template phục vụ cả hai, không nhân đôi dữ liệu.
- B2. Không đổi `size="70"`/`cols="100"` trong template. Trên mobile CSS `width:100%` thắng; trên desktop giữ nguyên hiển thị cũ.
- B3. Không cần restart server: FastAPI phục vụ static từ đĩa và Jinja tự nạp lại template khi mtime đổi. Đã kiểm trên server đang chạy (job Episode 02 không bị ngắt). Điện thoại có thể giữ `app.css` cũ trong cache → tải lại trang.

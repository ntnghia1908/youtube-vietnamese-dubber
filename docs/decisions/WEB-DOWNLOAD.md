# WEB-DOWNLOAD — decision log

## A. Contract

- `<thư mục tập>/web_download.json`: `{"downloaded_at": ISO local có offset, "output_size": int, "output_mtime_ns": int}`. Dữ liệu riêng của web; pipeline không đọc/ghi, `--force` không xoá.
- `library.read_download_mark(dir) -> str | None` chỉ trả giá trị khi size + mtime_ns của `output_vi.mp4` còn khớp; `write_download_mark` ghi atomic (tmp + `os.replace`); `clear_download_mark` idempotent. `EpisodeSummary.downloaded_at` (thêm cuối, mặc định None; có trong `/api/library`).
- Route: `GET /download/{key}` (attachment, tên `<title> - lồng tiếng.mp4`), `POST|DELETE /api/episodes/{key}/downloaded` (POST kiểm Origin như các route ghi khác; DELETE cũng kiểm Origin). `/media/...` không đổi.

## B. Quyết định nhỏ

- Dấu ghi lúc server bắt đầu trả file (không biết client tải xong); người dùng bỏ dấu được.
- Request `Range` chỉ ghi dấu khi chưa có dấu hợp lệ (vd lần đầu tải bằng trình quản lý tải); có dấu hợp lệ thì giữ nguyên.
- Playlist page: link tải/✓ chỉ cho tập có stage `render` done; tập chưa render hiện "—".
- Cột "Đã tải" cũ đổi thành "Nguồn", cột mới "Video".
- `episode.js`: click link tải hiện ✓ ngay bằng giờ trình duyệt (chỉ hiển thị; dấu thật do server ghi, tải lại trang sẽ hiện giờ server).
- Hiển thị thời điểm tải: `<time datetime=ISO>` + filter Jinja `dl_time` ("HH:MM dd/mm/yyyy" theo múi giờ trong chuỗi, fallback không JS; chuỗi hỏng trả nguyên). `episode.js` đổi sang giờ trình duyệt cùng định dạng, kể cả lúc click tải. Playlist: tooltip dùng `dl_time`.
- Giờ local của server đang là UTC (`+00:00`) nên fallback server-side hiện giờ UTC; JS sửa theo trình duyệt.

## C. Chạy thật

Server LAN 10.8.102.102:8081 restart bằng kill đúng PID 1607104 (không có job queued/running) -> PID mới 1679961. Episode 03 Ocean Girl:

- `GET /download/<key>` (cookie đăng nhập): 200, `content-disposition: attachment; filename*=utf-8''The%20New%20Adventures%20of%20Ocean%20Girl%20%5BEpisode%2003%20of%2026%20-%20Hearing%20the%20Call%5D%20-%20l%E1%BB%93ng%20ti%E1%BA%BFng.mp4`, 141562844 byte, so sánh byte-by-byte với `output_vi.mp4`: giống.
- `web_download.json` cuối cùng (sau tải lại, để nguyên): `{"downloaded_at": "2026-10-17T15:15:00+00:00", "output_size": 141562844, "output_mtime_ns": 1792244967839593551}`; trang playlist chỉ dòng Episode 03 có "✓ đã tải" (1/26 dòng), trang tập có "✓ Đã tải lúc …".
- `DELETE` -> `{"downloaded_at":null}`, file dấu mất, ✓ biến mất; `Range: 0-9` -> 206, ghi dấu vì chưa có dấu hợp lệ (đúng contract); tải đầy đủ lại -> 200, ✓ có.
- Không cookie -> 401 (curl không Accept html; trình duyệt thì redirect login).
- Dấu Episode 03 để nguyên (ở trạng thái như trên).

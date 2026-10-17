# Decision log — WEB-PARALLEL-PLAYLIST

## A. Contract với stage/job sau

- `playlist.json` format không đổi. Ghi qua `_persist_entry` (file lock `playlist.json.lock`, tmp `playlist.json.<pid>.tmp`). Thứ tự khoá: `entries_lock` rồi file lock.
- `job_targets(..., index_map=)` thêm nhãn `in-playlist:<L>`; `targets_conflict(a, b)` là luật xung đột duy nhất; `read_playlist_index_map(workspace, list_id)` đọc `playlist.json` (lỗi -> `{}` -> khoá cả playlist).
- Job glossary tập trong playlist đổi từ `playlist:<L>` sang `in-playlist:<L>` (vẫn chờ job cả playlist, không chờ job tập khác).

## B. Quyết định nhỏ

- Lần ghi đầu của `run_playlist` (sau fetch) dùng `_write_json_atomic` trong file lock, đọc lại file ngay trong lock rồi merge. `_persist_entry` không reentrant (flock khác fd cùng tiến trình sẽ deadlock) nên lần ghi đầu không gọi nó.
- Thiếu entry của mình trên đĩa (tiến trình khác refetch loại nó) -> append lại.
- Top-level field (`fetched_at`, ...) giữ theo bản trên đĩa khi persist.
- Nhánh Windows `msvcrt` chưa chạy thử trên Windows (chỉ import-guard theo `os.name`) — `# pragma: no cover`.
- Chạy thật dùng workspace tạm (không phải `./output`) để không ghi vào `playlist.json` mà các job web đang chạy (code cũ, ghi đè cả file) đang dùng.

## C. Rủi ro đã biết

- Playlist YouTube bị sắp xếp lại giữa hai lần fetch -> hai job có thể cùng chạy một tập (tốn gấp đôi công, artifact vẫn atomic). Không thêm `.lock` theo tập.
- Job web đang chạy bằng code cũ (trước restart) vẫn ghi đè cả `playlist.json`: lost update vẫn có thể xảy ra cho tới khi các job đó xong và server được restart.

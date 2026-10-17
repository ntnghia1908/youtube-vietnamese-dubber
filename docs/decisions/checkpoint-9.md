# Checkpoint 9 — Các quyết định nhỏ khi triển khai

## CP9-A — Glossary dùng chung theo playlist

### A. Contract với CP9-B.. (và các stage sau)

- **Tầng glossary hiệu lực** (`load_effective_glossary`, sau thắng trước):
  `--glossary`/`translation.glossary` -> `<thư mục playlist>/glossary.yaml` -> `<tập>/glossary.yaml`.
  Gộp bằng `merge_glossaries` (không đổi ngữ nghĩa); chỉ một tầng thì không đi qua merge.
- Tầng playlist được nhận theo vị trí: `episode_dir.parent/playlist.json` tồn tại
  (`playlist_glossary_path`). Tập lẻ không bị ảnh hưởng. File playlist tuỳ chọn;
  hỏng thì `GlossaryError` ở stage translate.
- `translated.json` không đổi schema; `glossary_sha256` là hash glossary hiệu lực
  gồm cả tầng playlist. Playlist chưa có `glossary.yaml` thì hash mọi tập y hệt trước.
- Dữ liệu skip bài hát (hạng mục CP9 kế tiếp) chỉ cần thêm chuỗi `skip` vào
  glossary playlist, không cần code mới ở tầng nạp.
- Web: `GET/PUT /api/playlists/{key}/glossary`, `POST /api/playlists/{key}/redub`,
  trang `/pl/{key}/glossary`. `GlossaryState.playlist_path` mới.

### B. Quyết định nhỏ

- `stale_items` của playlist chỉ xét tập có `translated.json`; tập glossary lỗi
  (stale `None`) không tính stale. Index lấy từ `playlist.json`; thư mục tập chỉ
  lấy tên cuối của `episode_dir` để path trong file không thoát thư mục playlist.
- Lõi ghi có kiểm hash tách thành `_write_checked`, dùng chung tập và playlist.
- Template `glossary.html`/`glossary.js` dùng chung hai chế độ qua `data-api`/`data-mode`.

## CP9-B — Giữ nhạc gốc to ở đoạn không lồng tiếng


(File tạm khi chạy song song với CP9-A; ORCHESTRATOR gộp vào `checkpoint-9.md`.)

### A. Contract với CP(N+1)

- `normalized.json` không đổi schema. `render.json` mục `output.params` thêm `skip_original_volume`,
  `skip_fade_seconds`, `skip_intervals` (`[[a, b], ...]`, đã gộp/cắt; rỗng nếu tắt tính năng).
- `_output_fingerprint` `"v": 2` -> mọi tập đã render mux lại một lần (voice track KHÔNG dựng lại).
- `render_episode(..., skip_original_volume=1.0, skip_fade=0.5)`; `mix_video` nhận thêm
  `skip_intervals`, `skip_original_volume`, `skip_fade`, `skip_fades`.
- Config: `mixing.skip_original_volume` (0–1), `mixing.skip_fade_seconds` (0–3). Không có flag CLI.

### B. Quyết định nhỏ

- Fade nằm ngoài khoảng, thu hẹp theo câu có lồng tiếng kề: mỗi phía `min(fade, khoảng trống tới
  placement gần nhất phía đó)`. `original_volume_expr` có thêm kwarg tuỳ chọn `fades=[(fl, fr)]`
  (ngoài interface contract, mặc định = `fade`) để làm việc này; fade 0 một phía -> `gte`/`lte`.
- `skip_original_volume == original_volume` -> bỏ khoảng (filter y hệt cũ, `skip_intervals: []`).
- Validate mới là hàm riêng `validate_skip_mixing` (không đổi chữ ký `validate_mixing` đang được nơi khác gọi).
- Dấu phẩy escape `\,`, biểu thức không bọc nháy; chạy được trên ffmpeg 6.1.1 (Ubuntu).
- Test fixture có sẵn segment silent id 4 nên assert `output.params` của test cũ được cập nhật.

### C. Số đo (Episode 02, `skip_intervals` = [[0.0, 83.0]], glossary hiện tại có 7 silent)

mean_volume 10s: 20–30s source -25.7 / mới -25.3 / đối chứng -35.7 dB; 120–130s source -29.9 / mới -18.7 / đối chứng -18.7 dB.

# Checkpoint 9-B — Giữ nhạc gốc to ở đoạn không lồng tiếng

(File tạm khi chạy song song với CP9-A; ORCHESTRATOR gộp vào `checkpoint-9.md`.)

## A. Contract với CP(N+1)

- `normalized.json` không đổi schema. `render.json` mục `output.params` thêm `skip_original_volume`,
  `skip_fade_seconds`, `skip_intervals` (`[[a, b], ...]`, đã gộp/cắt; rỗng nếu tắt tính năng).
- `_output_fingerprint` `"v": 2` -> mọi tập đã render mux lại một lần (voice track KHÔNG dựng lại).
- `render_episode(..., skip_original_volume=1.0, skip_fade=0.5)`; `mix_video` nhận thêm
  `skip_intervals`, `skip_original_volume`, `skip_fade`, `skip_fades`.
- Config: `mixing.skip_original_volume` (0–1), `mixing.skip_fade_seconds` (0–3). Không có flag CLI.

## B. Quyết định nhỏ

- Fade nằm ngoài khoảng, thu hẹp theo câu có lồng tiếng kề: mỗi phía `min(fade, khoảng trống tới
  placement gần nhất phía đó)`. `original_volume_expr` có thêm kwarg tuỳ chọn `fades=[(fl, fr)]`
  (ngoài interface contract, mặc định = `fade`) để làm việc này; fade 0 một phía -> `gte`/`lte`.
- `skip_original_volume == original_volume` -> bỏ khoảng (filter y hệt cũ, `skip_intervals: []`).
- Validate mới là hàm riêng `validate_skip_mixing` (không đổi chữ ký `validate_mixing` đang được nơi khác gọi).
- Dấu phẩy escape `\,`, biểu thức không bọc nháy; chạy được trên ffmpeg 6.1.1 (Ubuntu).
- Test fixture có sẵn segment silent id 4 nên assert `output.params` của test cũ được cập nhật.

## C. Số đo (Episode 02, `skip_intervals` = [[0.0, 83.0]], glossary hiện tại có 7 silent)

mean_volume 10s: 20–30s source -25.7 / mới -25.3 / đối chứng -35.7 dB; 120–130s source -29.9 / mới -18.7 / đối chứng -18.7 dB.

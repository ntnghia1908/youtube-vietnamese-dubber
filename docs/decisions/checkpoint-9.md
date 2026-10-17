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

## CP9-C — `playlist` xử lý 2 tập song song

### A. Contract với CP(N+1)

- `playlist.json`, job JSON, thư mục tập: không đổi schema. Job playlist trên web có thêm `--episode-workers N` trong `command` (ghi trước khi spawn).
- Config `pipeline.episode_workers: auto | 1–2` (trần `MAX_WEB_JOBS`); flag `playlist --episode-workers N|auto`. `PlaylistOptions.episode_workers: int = 1`.
- `app.hardware.resolve_episode_workers` (cùng luật `auto` với `resolve_web_max_jobs`); `validate_episode_workers` trong `app/config.py`.
- `server.run(..., *, episode_workers=1)`; `JobManager(..., episode_workers=1)`; `_running: job_id -> (proc, targets, slots)`.
- `run_playlist`: `episodes` luôn sắp theo index; N = 1 chạy trên luồng gọi như cũ.

### B. Quyết định nhỏ

- Thân vòng lặp tách thành `_process_one(idx)` dùng chung hai đường; pool là `_run_pool` (daemon thread, `join(timeout=0.5)` lặp lại để Ctrl+C ngắt được).
- Khoá `result_lock` (khoá lá) bảo vệ `aborted`/`consecutive_failures`/`episodes`; thứ tự khoá `entries_lock` -> file lock giữ nguyên.
- Khi `aborted` luồng tải dừng sớm, nên worker đang chờ tập chưa được tải sẽ không bao giờ được đánh thức: vòng chờ giờ thoát với `not_run` nếu luồng tải đã chết mà event chưa set (chỉ xảy ra khi có >1 worker).
- Dòng log `[playlist] xử lý song song N tập (<lý do>)` do CLI in (vì lý do resolve chỉ CLI biết), không phải `run_playlist`; in cả khi mọi tập bị skip.
- Slot: `playlist` = `min(episode_workers, slot trống lúc dispatch, số tập trong items)`, tối thiểu 1; không chờ đủ slot.
- `--episode-workers` sai exit 2 (khác `--items` sai exit 1, giữ nguyên hành vi cũ của `--items`).
- Test cũ `tests/test_web_cli_config.py` có `fake.run = lambda *a:` nên phải đổi thành `lambda *a, **kw:` để nhận kwarg `episode_workers` (không đổi kỳ vọng).
- `[CẦN DUYỆT]` Whisper `auto` = 12 thread/tiến trình (32 CPU // 2); hai tập transcribe cùng lúc trong MỘT tiến trình dùng 2 × 12 = 24 thread — vẫn vừa 32 CPU, nhưng nếu máy ít core hơn mà `episode_workers` = 2 thì nên xem lại.

### C. Số đo (Linux 32 CPU, không GPU, `qwen3:14b`, Ollama CHƯA đặt `OLLAMA_NUM_PARALLEL=2`)

Lệnh: `playlist ... --items 5,6 --episode-workers 2` (Episode 04 + 05 Ocean Girl, 1486 s + 1467 s video). Wall time cả lệnh: **41m38s**. Lần 2: 1,3 s, `skipped 2`.

| stage (s) | EP05 (Episode 04) | EP06 (Episode 05) |
|---|---|---|
| transcribe | 1729,4 | 1715,7 |
| translate | 294,6 | 293,7 |
| tts | 341,5 (+7,6 sửa) | 354,3 (+7,8 sửa) |
| normalize | 43,5 | 38,8 |
| render | 79,4 | 77,6 |

- Log hai tập xen nhau ở mọi stage (transcribe cùng lúc, translate batch xen kẽ `[EP05]`/`[EP06]`). Cả hai `completed`, `missing_ids` rỗng, `translate_failed_ids` rỗng, không tập nào lỗi TTS vĩnh viễn (không thấy dấu hiệu F1 tăng).
- `output_vi.mp4`: 1 video h264 + 1 aac; 1486,64 s / 1466,72 s so với `source.mp4` 1486,73 s / 1466,78 s.
- `translated.json`: câu rỗng chỉ ở các id đầu (bài hát chủ đề, glossary playlist `skip`), không nằm trong `translate_failed_ids`.
- Web: restart server (kill đúng PID); `server.log` có `[web] Job playlist: tối đa 2 tập song song (32 CPU)`; job `20261017-151057-00c6e9` (`items=7`) chạy với `--episode-workers 1`, sau đó hủy (`cancelled`, exit -15).
- Chưa đo so sánh với chạy tuần tự: Ollama chưa đặt `OLLAMA_NUM_PARALLEL=2` (việc của HUMAN LEAD, xem Manual test checklist).

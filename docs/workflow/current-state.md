# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Đã xong tới **CP8** (`dub` end-to-end, `playlist` với luồng tải song song + resume qua `playlist.json`). Playlist thật đang dùng: `PLJVKAfvqjvcp9lhYU37emhlRZExZrx0Cm` (22 tập, EP13–21 Private, tập dài 18–36 phút, ~35 phút xử lý/tập). EP1 đã `completed`, EP2 đã có transcript.

Đang làm: **WEB-1** (Web UI local, read-only) — contract `docs/tasks/WEB-1-library-player.md`, boundary ADR-001 (không cần APPROVE TASK). Sau đó WEB-2, WEB-3, rồi CP9 (ADR-001 D5).

## Next proposed action

PROPOSED, không authorize implementation:

0. `/implement WEB-1` sau khi gỡ blocker bên dưới.
1. **Checkpoint 9 — Quality improvements** (plan §CP9: chọn **một** hạng mục mỗi lần, chỉ sau khi đánh giá output thật). Việc đầu tiên: **nghe `output_vi.mp4` của EP1** — chưa ai nghe bằng tai output nào từ CP6. Ứng viên theo số liệu đã đo:
   1. *Câu dịch quá dài*: EP1 có 79/353 câu `too_long` (22%) — vượt `timing.max_tempo` 1.25. Hướng: prompt rút gọn / dịch lại riêng câu too_long với giới hạn ký tự (plan mục 5 "translation shortening").
   2. *Nhiều giọng*: một giọng HoaiMy đọc cả vai ba lẫn con (plan mục 6–8).
   3. *Dịch 2 tập song song* (tốc độ): nhanh hơn 1.33× ở bước dịch với `OLLAMA_NUM_PARALLEL=2` — số đo ở `docs/SETUP.md` mục A4.
2. **Web UI local** — WEB-1 → WEB-2 → WEB-3 theo ADR-001 (ACCEPTED); làm trước CP9.

Nợ riêng, làm bằng `fix(...)` (S1), không phải checkpoint:

- `fix(tts)`: edge-tts từng lỗi vĩnh viễn ~20–25% câu trên tập 353 câu (chạy lại thì 0%) — nghi rate-limit; cần backoff/hạ `tts.concurrency`. Xem `docs/decisions/checkpoint-8.md` F1.
- Mục `[CẦN DUYỆT]` còn mở của CP7: C0 (Whisper chia segment khác giữa hai lần chạy), C1 (`tts/manifest.json` bị ghi lại dù không đổi).
- Summary `playlist` chỉ in dòng đầu của lỗi → không thấy lý do thật (vd "Private video").

## Open decisions

Không.

## Blockers

Máy dev hiện tại (Linux) chưa đủ để chạy thật WEB-1:

- `.venv` chưa dựng (dựng theo `docs/SETUP.md`, thêm `pip install -e ".[web]"` khi WEB-1 thêm extra).
- `output/` trống — EP1 `completed` và thư mục playlist đang nằm trên máy Windows; cần copy sang để kiểm player/`too_long` thật.
- Không có Ollama/GPU (`nvidia-smi` không có) → không chạy được translate trên máy này; download + transcribe (CPU) vẫn chạy được.

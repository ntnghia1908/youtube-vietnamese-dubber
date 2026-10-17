# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Đã xong tới **CP8** (`dub` end-to-end, `playlist` với luồng tải song song + resume qua `playlist.json`). Playlist thật đang dùng: `PLJVKAfvqjvcp9lhYU37emhlRZExZrx0Cm` (22 tập, EP13–21 Private, tập dài 18–36 phút, ~35 phút xử lý/tập). EP1 đã `completed`, EP2 đã có transcript.

Đang làm: **WEB-1** (Web UI local: nhập URL video/playlist + jobs + thư viện + player) — contract `docs/tasks/WEB-1-jobs-library-player.md`, boundary ADR-001 (không cần APPROVE TASK). Sau đó WEB-2 (glossary), rồi CP9 (ADR-001 D5).

## Next proposed action

PROPOSED, không authorize implementation:

0. `/implement WEB-1`.
1. **Checkpoint 9 — Quality improvements** (plan §CP9: chọn **một** hạng mục mỗi lần, chỉ sau khi đánh giá output thật). Việc đầu tiên: **nghe `output_vi.mp4` của EP1** — chưa ai nghe bằng tai output nào từ CP6. Ứng viên theo số liệu đã đo:
   1. *Câu dịch quá dài*: EP1 có 79/353 câu `too_long` (22%) — vượt `timing.max_tempo` 1.25. Hướng: prompt rút gọn / dịch lại riêng câu too_long với giới hạn ký tự (plan mục 5 "translation shortening").
   2. *Nhiều giọng*: một giọng HoaiMy đọc cả vai ba lẫn con (plan mục 6–8).
   3. *Dịch 2 tập song song* (tốc độ): nhanh hơn 1.33× ở bước dịch với `OLLAMA_NUM_PARALLEL=2` — số đo ở `docs/SETUP.md` mục A4.
2. **Web UI local** — WEB-1 → WEB-2 theo ADR-001 (ACCEPTED); làm trước CP9.

Nợ riêng, làm bằng `fix(...)` (S1), không phải checkpoint:

- `fix(tts)`: edge-tts từng lỗi vĩnh viễn ~20–25% câu trên tập 353 câu (chạy lại thì 0%) — nghi rate-limit; cần backoff/hạ `tts.concurrency`. Xem `docs/decisions/checkpoint-8.md` F1.
- Mục `[CẦN DUYỆT]` còn mở của CP7: C0 (Whisper chia segment khác giữa hai lần chạy), C1 (`tts/manifest.json` bị ghi lại dù không đổi).
- Summary `playlist` chỉ in dòng đầu của lỗi → không thấy lý do thật (vd "Private video").

## Open decisions

Không.

## Blockers

Không. Ghi chú môi trường máy dev hiện tại (Linux, không GPU NVIDIA):

- `.venv` đã dựng 2026-10-17 bằng Python 3.14 của miniconda (hệ thống thiếu `python3.12-venv`); 437 test OK. WEB-1 thêm extra thì chạy `pip install -e ".[web]"`.
- Ollama ở `http://127.0.0.1:11437` (v0.35.0, có vẻ là tunnel sang máy khác) không có `gemma3:12b`. HUMAN LEAD 2026-10-17: dùng tạm `qwen3:14b` cho WEB-1 (`config.yaml` local) — chất lượng dịch với model này CHƯA được đánh giá; CP9 cần quay lại `gemma3:12b` hoặc đánh giá qwen3:14b.
- Không cần copy dữ liệu từ máy Windows: WEB-1 tự tạo dữ liệu kiểm thử bằng cách nhập URL.

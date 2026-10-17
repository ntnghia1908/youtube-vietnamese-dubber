# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Đã xong tới **CP8** (`dub` end-to-end, `playlist` với luồng tải song song + resume qua `playlist.json`). Playlist thật đang dùng: `PLJVKAfvqjvcp9lhYU37emhlRZExZrx0Cm` (22 tập, EP13–21 Private, tập dài 18–36 phút, ~35 phút xử lý/tập). EP1 đã `completed`, EP2 đã có transcript.

**WEB-1** READY, **WEB-AUTH** READY (đăng nhập bằng mật khẩu khi bind LAN, ADR-001 mục 9; mật khẩu ở `~/.config/dubber/web.env`, nạp qua `~/.bashrc`) — chờ HUMAN LEAD chạy Manual test checklist. HUMAN LEAD 2026-10-17: làm **WEB-2** (`docs/tasks/WEB-2-glossary-editor.md`) trong lúc tạo/nghe output EP1; nghe xong mới chọn hạng mục CP9.

## Next proposed action

PROPOSED, không authorize implementation:

0. Tạo output EP1 của playlist thật trên máy Linux (job playlist `items=1` qua web — đồng thời là manual test WEB-1/WEB-AUTH), HUMAN LEAD nghe, rồi chọn **một** hạng mục CP9 và `/spec CP9`.
1. **Checkpoint 9 — Quality improvements** (plan §CP9: chọn **một** hạng mục mỗi lần, chỉ sau khi đánh giá output thật). Việc đầu tiên: **nghe `output_vi.mp4` của EP1** — chưa ai nghe bằng tai output nào từ CP6. Ứng viên theo số liệu đã đo:
   1. *Câu dịch quá dài*: EP1 có 79/353 câu `too_long` (22%) — vượt `timing.max_tempo` 1.25. Hướng: prompt rút gọn / dịch lại riêng câu too_long với giới hạn ký tự (plan mục 5 "translation shortening").
   2. *Nhiều giọng*: một giọng HoaiMy đọc cả vai ba lẫn con (plan mục 6–8).
   3. *Dịch 2 tập song song* (tốc độ): nhanh hơn 1.33× ở bước dịch với `OLLAMA_NUM_PARALLEL=2` — số đo ở `docs/SETUP.md` mục A4.
2. **WEB-2** (glossary) — đang làm, song song với việc nghe output (bước 0).

Nợ riêng, làm bằng `fix(...)` (S1), không phải checkpoint:

- `fix(tts)`: edge-tts từng lỗi vĩnh viễn ~20–25% câu trên tập 353 câu (chạy lại thì 0%) — nghi rate-limit; cần backoff/hạ `tts.concurrency`. Xem `docs/decisions/checkpoint-8.md` F1.
- Mục `[CẦN DUYỆT]` còn mở của CP7: C0 (Whisper chia segment khác giữa hai lần chạy), C1 (`tts/manifest.json` bị ghi lại dù không đổi).
- Summary `playlist` chỉ in dòng đầu của lỗi → không thấy lý do thật (vd "Private video").

## Open decisions

Không.

## Blockers

Không. Ghi chú môi trường máy dev hiện tại (Linux, không GPU NVIDIA):

- `.venv` đã dựng 2026-10-17 bằng Python 3.14 của miniconda (hệ thống thiếu `python3.12-venv`); 437 test OK. Đã cài extra `web`; `av` ghim `<17` (`fix(deps)`).
- Ollama ở `http://127.0.0.1:11437` (v0.35.0, có vẻ là tunnel sang máy khác) không có `gemma3:12b`. HUMAN LEAD 2026-10-17: dùng tạm `qwen3:14b` cho WEB-1 (`config.yaml` local) — chất lượng dịch với model này CHƯA được đánh giá; CP9 cần quay lại `gemma3:12b` hoặc đánh giá qwen3:14b.
- Không cần copy dữ liệu từ máy Windows: WEB-1 tự tạo dữ liệu kiểm thử bằng cách nhập URL.

# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Đã xong tới **CP8** (`dub` end-to-end, `playlist` với luồng tải song song + resume qua `playlist.json`). Playlist thật đang dùng: `PLJVKAfvqjvcp9lhYU37emhlRZExZrx0Cm` (22 tập, EP13–21 Private, tập dài 18–36 phút, ~35 phút xử lý/tập). EP1 đã `completed`, EP2 đã có transcript.

**WEB-1**, **WEB-AUTH**, **WEB-2**, **WEB-PARALLEL**, **WEB-MOBILE**, **WEB-PARALLEL-PLAYLIST** đã commit (chưa push). Hàng đợi web: tối đa 2 job song song; hai job **khác tập** của cùng playlist chạy song song, trùng tập thì chờ. Web UI dùng tốt trên điện thoại (HUMAN LEAD đã xác nhận). Mật khẩu web ở `~/.config/dubber/web.env`. Manual test checklist WEB-1/WEB-AUTH/WEB-2/WEB-PARALLEL-PLAYLIST chưa tick.

Output để nghe (server 10.8.102.102:8081): EP01 playlist `PLJVKAfv…` `completed`; Ocean Girl Episode 01 (index 2) và Episode 02 (index 3) `completed`. Episode 01 đã dịch lại sau khi bổ sung glossary: lời bài hát chủ đề không còn bị lồng tiếng. Episode 02 còn lọt câu 27s "Love the wisdom, want the will…" (Whisper nghe khác Episode 01) → cần thêm chuỗi `skip` rồi "dịch lại & chạy tiếp". Glossary đang chép tay vào từng tập (bằng chứng cho ứng viên CP9 "glossary theo playlist"). Tập 6, 7 (Episode 05, 06) đã tải (`--download-only`). Nghe xong mới chọn hạng mục CP9.

## Next proposed action

PROPOSED, không authorize implementation:

0. Tạo output EP1 của playlist thật trên máy Linux (job playlist `items=1` qua web — đồng thời là manual test WEB-1/WEB-AUTH), HUMAN LEAD nghe, rồi chọn **một** hạng mục CP9 và `/spec CP9`.
1. **Checkpoint 9 — Quality improvements** (plan §CP9: chọn **một** hạng mục mỗi lần, chỉ sau khi đánh giá output thật). Việc đầu tiên: **nghe `output_vi.mp4` của EP1** — chưa ai nghe bằng tai output nào từ CP6. Ứng viên theo số liệu đã đo:
   1. *Câu dịch quá dài*: EP1 có 79/353 câu `too_long` (22%) — vượt `timing.max_tempo` 1.25. Hướng: prompt rút gọn / dịch lại riêng câu too_long với giới hạn ký tự (plan mục 5 "translation shortening").
   2. *Nhiều giọng*: một giọng HoaiMy đọc cả vai ba lẫn con (plan mục 6–8).
   3. *Dịch 2 tập song song* (tốc độ): nhanh hơn 1.33× ở bước dịch với `OLLAMA_NUM_PARALLEL=2` — số đo ở `docs/SETUP.md` mục A4.
2. Ứng viên CP9 mới từ Ocean Girl: glossary chung cho cả playlist/series (hiện chỉ theo tập); giữ nhạc gốc to ở đoạn `skip`/không lồng tiếng (intro bài hát).

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

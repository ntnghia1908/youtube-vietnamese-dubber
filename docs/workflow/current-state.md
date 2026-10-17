# Current State

| Metadata | Value |
|---|---|
| Status | OPERATIONAL STATE — NOT AUTHORITY |

Chỉ ghi operational state không suy ra được từ Git, task contract hoặc accepted decisions.

## Current focus

Đã xong tới **CP8** + Web UI (WEB-1, WEB-AUTH, WEB-2, WEB-PARALLEL, WEB-MOBILE, WEB-PARALLEL-PLAYLIST, WEB-POLISH) + **CP9-A** (glossary dùng chung theo playlist) + **CP9-B** (giữ nhạc gốc to ở đoạn `silent`). Tất cả đã commit, chưa push. Policy: tối đa 2 implementer song song (`docs/ai/project-profile.md` §7).

Server LAN 10.8.102.102:8081 chạy code mới nhất. Mật khẩu web ở `~/.config/dubber/web.env`. Manual test checklist WEB-1/WEB-AUTH/WEB-2/WEB-PARALLEL-PLAYLIST/WEB-POLISH/CP9-A/CP9-B chưa tick (máy Linux không có trình duyệt → kiểm tra trực quan là việc của HUMAN LEAD).

Ocean Girl (`PLllZo…`): đã có `output/PLllZo…/glossary.yaml` (glossary playlist, 11 chuỗi `skip` bài hát chủ đề). Episode 01/02/03 `completed`; Episode 01/02 đang **stale** (đã có glossary playlist) → bấm "Dịch lại các tập cũ" ở trang glossary playlist. Episode 03 còn lọt điệp khúc "Ocean, our ocean" (segment 6, 8) → thêm `skip`. Glossary Episode 02 có nhân vật/xưng hô (công chúa, vua/phù thủy xưng "ta"); không có speaker diarization nên "cháu" vẫn lan sang lời lính canh/vua — giới hạn đã biết. Tập 6, 7 (Episode 05, 06) đã tải.

## Next proposed action

PROPOSED, không authorize implementation. Thứ tự CP9 HUMAN LEAD chọn 2026-10-17 (đã xong CP9-A, CP9-B):

1. Không lồng tiếng phần bài hát của playlist Guess How Much I Love You (`PLJVKAfv…`) — giờ chủ yếu là dữ liệu: thêm `skip` vào glossary playlist của playlist đó qua web.
2. Dịch 2 tập song song (bước dịch nhanh hơn 1.33× với `OLLAMA_NUM_PARALLEL=2`, số đo ở `docs/SETUP.md` A4) — cần `/spec`.
3. Nhiều giọng đọc thay vì một giọng HoaiMy (ưu tiên cuối; cần speaker diarization, cũng giải quyết xưng hô theo người nói).

Ứng viên khác chưa chọn: câu dịch quá dài (EP1 22% `too_long`).

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

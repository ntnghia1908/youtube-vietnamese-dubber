# Checkpoint 5 — Các quyết định nhỏ khi triển khai

Plan không quy định các điểm dưới đây nên người triển khai tự chọn. Ghi
lại để review trước khi sang CP6. Mục **[CẦN DUYỆT]** là trade-off nên
chốt lại; mục **[CP6]** là thứ CP6 phải biết khi đọc `normalized.json`.

---

## A. Contract với CP6 — đọc kỹ nhất

### A1. Schema `normalized.json` [CP6]

```json
{
  "fingerprint": "sha256…",
  "params": {"normal_max_ratio": 1.05, "max_tempo": 1.25},
  "summary": {"segments": 58, "normal": 48, "stretched": 6, "too_long": 4, "silent": 0, "missing": 0},
  "too_long_ids": [8, 18, 24, 38],
  "missing_ids": [],
  "segments": [
    {"id": 1, "start": 0.0, "end": 6.0, "slot": 6.0,
     "source_text": "…", "translated_text": "…",
     "status": "normal", "tts_file": "tts/000001.mp3", "tts_cache_key": "9f2c…",
     "tts_duration": 5.208, "ratio": 0.868, "tempo": 1.0,
     "audio": "tts/000001.mp3", "audio_duration": 5.208, "overflow": 0.0}
  ]
}
```

- `segments` đúng thứ tự và **đủ id** của `translated.json` tại thời điểm
  chạy `normalize` gần nhất — kể cả `silent`/`missing` đều có một entry
  (khác `tts/manifest.json`, ở đây không có khái niệm "bỏ qua vì rỗng").
- **CP6 chỉ ghép audio cho segment có `audio != null`.** `status == "silent"`
  nghĩa là để khoảng lặng đúng `slot` giây (CP4 dịch ra rỗng/toàn dấu câu —
  không phải lỗi). `status == "missing"` nghĩa là thiếu audio thật (tts
  lỗi/không có entry/file mất) — CP6 nên quyết định: chèn khoảng lặng như
  `silent`, hay dừng và báo lỗi, tuỳ mức độ nghiêm ngặt cần có; CP5 không
  có ý kiến, chỉ đảm bảo không lẫn audio giả và luôn có `error` mô tả để
  debug.
- `audio` là đường dẫn **tương đối với episode dir**, dùng `/`
  (`tts/000001.mp3` hoặc `timing/000007.wav`) — CP6 tự `episode_dir / audio`.
  Không dùng `tts_file` để ghép (nó luôn trỏ file **chưa co giãn**, kể cả
  khi `status` là `stretched`/`too_long`).
- `audio_duration` là ffprobe thật của file cuối cùng (không phải
  `tts_duration / tempo` — atempo không chính xác tuyệt đối). CP6 nên dùng
  giá trị này để tính offset các segment kế tiếp nếu cần, không tự suy ra
  từ `tempo`.
- `overflow > 0` (chỉ xảy ra ở `too_long`) nghĩa là audio vẫn dài hơn slot
  sau khi co giãn tối đa — CP6 sẽ phải quyết định đè lên câu sau hay chấp
  nhận lệch nhẹ nhàng. Rút gọn câu bằng LLM (plan §12 Case 3) là CP9,
  chưa xử lý.
- `fingerprint` chỉ dùng nội bộ để CP5 tự resume, CP6 không cần đọc.

### A2. `normalize_timing()` là hàm dùng lại được, không chỉ qua CLI

```python
def normalize_timing(
    episode_dir: Path, *,
    normal_max_ratio: float = 1.05, max_tempo: float = 1.25,
    force: bool = False, log=print,
) -> TimingResult
```

`TimingResult` có `normalized_path`, `normal_ids`, `stretched_ids`,
`too_long_ids`, `silent_ids`, `missing_ids`, `skipped` — CP7 (pipeline
`dub` end-to-end) gọi thẳng hàm này, giống cách CP3/CP4 gọi
`translate_transcript`/`synthesize_translation`.

### A3. `missing_ids` khác rỗng không chặn `normalize` (exit 0), giống A3 của CP4

CLI in `CẢNH BÁO` nhưng vẫn exit 0. CP6/CP7 chạy sau một lệnh `normalize`
có `missing_ids` khác rỗng thì đang thiếu audio thật cho đúng các id đó —
nên tự kiểm tra (hoặc để CP7 orchestrate chạy lại `tts` rồi `normalize`
tới khi `missing_ids == []`).

---

## B. Thuật toán và cache

### B1. [A2 của CP4 — đã chốt trong spec] CP5 tự `ffprobe`, không sửa CP4

Chi phí đo được: 58 file mất **~3.7s** ở lần chạy đầu (không đáng kể so
với ~34s của TTS hay ~2 phút của dịch). Cache theo `tts_cache_key` trong
`normalized.json` nên các lần sau chỉ probe đúng segment vừa đổi — xem D.

### B2. Cache theo segment: `tts_duration` và `audio` là hai lớp độc lập

- `tts_duration` được giữ lại khi `tts_cache_key` khớp entry cũ, **bất kể**
  `status` cũ là gì (normal/stretched/too_long đều có `tts_duration`) —
  không phụ thuộc `max_tempo` hiện tại.
- File `audio` (chỉ áp dụng cho stretched/too_long) được giữ lại khi CẢ
  `tts_cache_key` khớp, `tempo` (làm tròn 4 chữ số) không đổi, `audio`
  (đường dẫn) không đổi, và file thật còn tồn tại trên đĩa. Đổi
  `--max-tempo` mà tempo tính ra của một segment tình cờ không đổi
  (segment đã `stretched` với tempo < cả hai mức max_tempo) thì không cần
  chạy lại ffmpeg.
- Hệ quả: đổi `--max-tempo` không bao giờ probe lại `tts_duration` (không
  phụ thuộc `max_tempo`), chỉ có thể phải chạy lại ffmpeg cho các segment
  có `tempo` thực sự đổi. Đã kiểm chứng bằng chạy thật (mục D).

### B3. `fingerprint` dùng để resume toàn phần, không thay cho cache từng segment

`fingerprint` = sha256 của `{"params": ..., "segments": [[id, start, end,
tts_status, tts_cache_key], ...]}`. Khớp + mọi `audio` không-null còn tồn
tại trên đĩa → SKIP hoàn toàn (không đọc `tts_duration`/không mở file
audio nào). Không khớp (đổi `max_tempo`, sửa một câu dịch, xoá tay một
file timing) → vẫn tính lại toàn bộ danh sách, nhưng cache theo-segment ở
B2 quyết định segment nào thực sự cần I/O.

### B4. `slot <= 0` coi là `too_long` ngay, không probe

Theo đúng chữ ký `classify()` của spec. Trường hợp này chưa gặp trong dữ
liệu thật (Whisper luôn cho `end > start`), chỉ là biện pháp phòng thủ.

### B5. Lỗi ffprobe trên file `tts/*.mp3` → `missing` (không dừng); lỗi ffprobe
trên file `timing/*.wav` vừa tự tạo hoặc lỗi ffmpeg khi co giãn → raise
`TimingError` (dừng cả lệnh)

Theo đúng phân loại của spec: "ffprobe lỗi trên file đó -> missing" áp
dụng cho nội dung do stage trước (CP4) tạo ra — có thể hỏng vì lý do
ngoài tầm kiểm soát (mạng, edge-tts trả file lạ). Ngược lại, lỗi khi
chính `normalize` vừa dùng ffmpeg tạo ra `timing/*.wav` rồi lại không
ffprobe được, hoặc ffmpeg tự báo lỗi, là dấu hiệu môi trường hỏng (ffmpeg
cài sai, đĩa đầy) — spec ghi rõ "Lỗi ffmpeg khi co giãn (môi trường) ->
TimingError, exit 1", nên xử lý cùng nhóm với lỗi ffprobe hậu-stretch thay
vì lặng lẽ đánh dấu `missing` cho một lỗi hệ thống có thể ảnh hưởng mọi
segment còn lại.

---

## C. Config và CLI

### C1. `TimingConfig` + validate dùng chung giữa config và `--max-tempo`

`validate_timing_ratios(normal_max_ratio, max_tempo)` (tương tự
`validate_rate_or_volume` của CP4) raise `ConfigError`, gọi cả trong
`parse_config` và `_cmd_normalize`. Không thêm flag CLI cho
`normal_max_ratio` theo đúng spec — chỉnh nó thì sửa `config.yaml`.

### C2. Không thêm field `duration`/`tempo` vào `tts/manifest.json`

Đúng chốt của spec ("Không sửa `app/tts/*`"). Mọi thông tin timing nằm
trọn trong `normalized.json` của CP5.

---

## D. Số liệu đo được (episode thật 58 segment, video ~4 phút)

- Lần chạy đầu tiên (đủ 58 ffprobe + 10 ffmpeg atempo cho 6 stretched + 4
  too_long): **~4.0s**.
- Chạy lại không đổi gì: **SKIP, ~0.2s** (chỉ đọc + so fingerprint + kiểm
  tra file tồn tại, không ffprobe/ffmpeg).
- `--max-tempo 1.4` (từ 1.25): **~0.6s** — không ffprobe lại file nào,
  chỉ chạy `ffmpeg atempo` cho đúng 1 segment (id 38, chuyển từ `too_long`
  sang `stretched`); 6 segment `stretched` cũ giữ nguyên `tempo` nên không
  đụng tới ffmpeg. `too_long` còn lại: 8, 18, 24 (3 thay vì 4).
- Quay lại `--max-tempo 1.25` (mặc định): **~0.6s**, không còn file mồ côi
  trong `timing/` (đếm lại đúng 10 file = 6 stretched + 4 too_long).
- `--force`: **~3.85s** — probe + co giãn lại toàn bộ 58 segment, kết quả
  giống hệt lần chạy đầu (48/6/4/0).
- Report thực tế: **normal 48 / stretched 6 / too_long 4** (id 8, 18, 24,
  38) — đúng dự đoán của Opus trước khi giao spec.
- Đối chiếu ffprobe chạy tay: id 1 `tts_duration=5.208s` (khớp số liệu CP4
  "84 ký tự → 5.208s"); id 8 `tts_duration=1.872s` (khớp "11 ký tự →
  1.872s"). File `timing/000008.wav` (`too_long`, tempo 1.25):
  `audio_duration=1.510417s` khớp `tts_duration/1.25 = 1.4976` **gần
  đúng** (chênh do atempo không chia hết tuyệt đối) — `overflow=0.51`
  đúng `1.510417 - 1.0 (slot)`. Mọi segment `stretched` kiểm tra được đều
  có `audio_duration` lệch `slot` trong khoảng `[-0.02, +0.0]`s, tốt hơn
  ngưỡng ±0.05s yêu cầu.
- `ffprobe -show_streams` trên `timing/000008.wav`: 1 stream
  `codec_name=pcm_s16le`, `channels=1`, `duration=1.510417` — không phải
  file câm/rỗng.

## E. Việc chưa làm

- Rút gọn câu `too_long` bằng LLM rồi TTS lại (plan §12 Case 3): CP9.
- Cắt khoảng lặng đầu/cuối mp3 edge-tts, mượn khoảng lặng segment sau: xem
  mục "Ngoài phạm vi" của spec CP5 — có thể xem lại nếu CP6 thấy quá nhiều
  `too_long` khi chạy video dài hơn.
- Nghe thử chất lượng giọng ở tempo 1.25 (đánh giá "méo") — chưa nghe
  bằng tai người, chỉ kiểm tra được số liệu (duration đúng, stream hợp
  lệ). Nếu Opus/user thấy cần, có thể nghe thử `timing/000008.wav` (tempo
  1.25, tăng tốc nhiều nhất trong 58 segment) trước khi chốt ngưỡng
  `max_tempo` mặc định.
- Ghép `voice_track.wav`, mix với audio gốc, render video cuối: CP6.

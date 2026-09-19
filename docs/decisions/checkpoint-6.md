# Checkpoint 6 — Các quyết định nhỏ khi triển khai

Spec (`docs/specs/cp-6.md`) đã chốt các điểm lớn (dời có trần thay vì đè,
`missing` mặc định báo lỗi, mux một lần ffmpeg, voice track dựng bằng
stdlib). File này ghi các chỗ spec để ngỏ và số liệu đo được. Mục
**[CẦN DUYỆT]** là chỗ Opus nên xem lại; mục **[CP7]** là thứ CP7 phải biết.

---

## A. Contract với CP7 — đọc kỹ nhất

### A1. Hàm dùng lại được [CP7]

```python
def render_episode(
    episode_dir: Path, *,
    original_volume: float = 0.30, speech_volume: float = 1.0,
    max_shift: float = 1.0, allow_missing: bool = False,
    force: bool = False, log=print,
) -> RenderResult
```

`RenderResult` có `voice_track_path`, `output_path`, `render_path`,
`placed_ids`, `silent_ids`, `missing_ids`, `shifted_ids`, `overlap_ids`,
`max_shift_seen`, `duration`, `voice_track_skipped`, `output_skipped`.
`RenderError` (không phải `TimingError`) cho mọi lỗi input/ffmpeg — CP7
bắt riêng. Tham số mix lấy từ `config.mixing` (`original_volume`,
`speech_volume`, `max_shift_seconds`); validate bằng
`app.config.validate_mixing` trước khi gọi (giống `_cmd_render`).

### A2. `render` KHÔNG tự chạy stage trước [CP7]

Thiếu `normalized.json`/`source.mp4`, hoặc có segment `missing` mà không
`allow_missing` → `RenderError`, không tự gọi `tts`/`normalize`. CP7 (`dub`)
phải điều phối: sau `normalize`, nếu `TimingResult.missing_ids` khác rỗng thì
chạy lại `tts` rồi `normalize` tới khi rỗng, rồi mới `render_episode`.
Segment có `audio` mà file mất trên đĩa (dù `allow_missing=True`) cũng là
`RenderError` — cách xử lý là chạy lại `normalize`.

### A3. Schema `render.json` [CP7]

```json
{
  "voice_track": {
    "fingerprint": "sha256…", "sample_rate": 24000, "duration": 243.554,
    "params": {"max_shift_seconds": 1.0},
    "summary": {"placed": 58, "silent": 0, "missing": 0, "shifted": 7,
                "overlap": 0, "max_shift_seen": 0.51},
    "placements": [
      {"id": 9, "start": 34.0, "placed_at": 34.51, "audio_duration": 2.983,
       "shift": 0.51, "overlap": 0.0}
    ]
  },
  "output": {
    "fingerprint": "sha256…",
    "params": {"original_volume": 0.3, "speech_volume": 1.0},
    "duration": 243.554
  }
}
```

- `placements` có một entry cho **mỗi** segment có `audio` (không có
  `silent`/`missing`), đúng thứ tự `(start, id)`. Số thực làm tròn 3 chữ số.
- Section `output` có thể vắng (mux lỗi giữa chừng, hoặc vừa dựng lại voice
  track): đọc `render.json` phải chịu được thiếu section.
- `voice_track.duration` = độ dài track (= `max(source, audio cuối)`);
  `output.duration` = độ dài `source.mp4` (mux theo `duration=first`).

### A4. Output cuối [CP7]

`<ep>/output_vi.mp4`: video stream copy nguyên (h264), audio aac stereo
44100 Hz 192k. Không có `mixed_audio.wav` trung gian.

---

## B. Quyết định triển khai

### B1. Segment không có audio và `status != "silent"` coi là `missing` [CẦN DUYỆT]

Spec định nghĩa `missing` là status `"missing"`. Với segment `audio == null`
mà status lạ (không phải `silent` cũng không phải `missing`) — không xảy ra
với `normalized.json` do CP5 sinh — tôi phân loại vào `missing` (báo lỗi
trừ khi `--allow-missing`) thay vì lặng lẽ coi như `silent`. Lý do: cùng
tinh thần quyết định 4 của spec, thà báo lỗi còn hơn để một câu mất tăm.

### B2. Thứ tự kiểm tra đầu vào

`normalized.json` (tồn tại, JSON hợp lệ, có `segments`, mỗi segment có
`id`/`start` số) → `source.mp4` → file `audio` không tồn tại/thiếu
`audio_duration` (liệt kê hết id) → `missing`. Mọi lỗi ở đây xảy ra trước khi
động vào bất kỳ file nào (kể cả dọn `.tmp`).

### B3. `probe_duration(source.mp4)` chạy ở mọi lần gọi, kể cả SKIP

`source_duration` nằm trong fingerprint voice track và quyết định độ dài
track, nên phải biết trước khi quyết SKIP. Chi phí: một lần `ffprobe`
(<0,3s, gộp trong tổng thời gian SKIP đo được ở D).

### B4. Ép `float` cho `original_volume`/`speech_volume`/`max_shift` trước khi tính fingerprint

`max_shift_seconds: 1` trong YAML là `int`, CLI `--max-shift 1` là `float`;
`json.dumps(1)` ≠ `json.dumps(1.0)` sẽ làm fingerprint đổi và dựng lại track
oan. Có test (`test_int_and_float_max_shift_share_fingerprint`).

### B5. Xử lý `render.json` khi resume

- SKIP voice: giữ nguyên section `voice_track` cũ và `output` cũ.
- Dựng lại voice: ghi `render.json` chỉ có `voice_track` mới (bỏ `output`
  cũ) ngay sau `os.replace` của `voice_track.wav`, đúng spec.
- Xoá tay `voice_track.wav` (nội dung dựng lại y hệt → cùng fingerprint) mà
  `output_vi.mp4` còn và khớp: mux SKIP, và section `output` cũ được **ghi
  lại** vào `render.json` (nếu không, lần sau sẽ mux lại oan).
- So sánh `output.fingerprint` luôn với `render.json` đọc **lúc đầu hàm**,
  không phải bản vừa bị bỏ section `output`.

### B6. Phòng thủ nhỏ trong `build_voice_track`

- `off = max(0, round(placed_at * sr))`, và placement nằm hoàn toàn ngoài
  track (`n <= 0`) bị bỏ qua thay vì raise (spec: "vượt track thì cắt, không
  raise").
- Xử lý big-endian (`byteswap`) khi cộng vùng đè, vì `array('h')` dùng thứ tự
  native trong khi PCM là s16le. Máy x86/ARM little-endian không chạm tới.
- Log tiến độ mỗi 10 segment (`[render] đã ghép N/M segment`) — video dài
  vài chục phút sẽ im lặng lâu nếu không có.

### B7. Giới hạn bộ nhớ (theo spec, không tối ưu sớm)

`bytearray` cả track: ~2,9 MB/phút (đo: 11,7 MB cho 243,55s). Video 2 giờ
≈ 350 MB RAM khi dựng. Chấp nhận; nếu gặp video dài hơn thì stream-hoá
theo khoảng (ghi WAV tuần tự, giữ đệm vùng đè) — chưa làm.

### B8. Báo cáo CLI khi không có segment dời

`shifted : 0` (không kèm hậu tố `(tối đa …s)`, vì "tối đa 0.00s" vô nghĩa).
Spec chỉ mô tả trường hợp có dời.

---

## C. Config và CLI

- `MixingConfig(original_volume=0.30, speech_volume=1.0, max_shift_seconds=1.0)`
  + `validate_mixing()` dùng chung giữa `parse_config` và `_cmd_render`
  (mẫu `validate_timing_ratios`).
- `speech_volume` không có flag CLI (theo spec) — chỉnh trong config. Đây là
  hệ số lúc mix, khác `tts.volume` (dạng `+N%`, áp lúc edge-tts tổng hợp).
- Không đổi mặc định nào của spec (`original_volume` 0.30, `max_shift_seconds`
  1.0).

---

## D. Số liệu đo được (episode thật 58 segment, source 243,554s)

Máy: Windows 11, ffmpeg 7.1.1 (có `amix normalize`).

**Thời gian**
- Lần 1 (dựng voice + mux): không đo trực tiếp bằng `time`; theo mtime
  `voice_track.wav` 07:13:53 → `output_vi.mp4` 07:13:58 và lần `--force` bên
  dưới, khoảng **~8–9s**.
- SKIP cả hai (lần 2): **0,26s**.
- Chỉ mux lại (`--original-volume 0.5`, lần 3): **5,6s** (voice SKIP, không
  gọi `decode_pcm`).
- `--max-shift 0` (lần 4, dựng lại voice + mux): **8,65s**.
- `--force` (lần 5, về mặc định): **8,60s**. Ước lượng: dựng voice ~3s
  (58 lần `ffmpeg pipe:1`), mux ~5,6s.

**Kích thước:** `voice_track.wav` 11.690.642 B (5.845.299 frame mono s16
24 kHz, đúng `ceil(243,554104 × 24000)`); `output_vi.mp4` 16.148.075 B
(original 0,5) / ~16,14 MB (mặc định); `source.mp4` 13.997.576 B.

**Placement ở mặc định (`max_shift` 1.0):** `shifted` = **7**
(id 9, 10, 15, 18, 19, 25, 39; shift 0.51, 0.493, 0.016, 0.016, 0.248, 0.232,
0.059), `max_shift_seen` = **0.51** (id 8 → id 9, đúng dự đoán), `overlap` = **0**.
Ít hơn dự đoán ~10–15 của spec, và xa ngưỡng escalate 30. Các `too_long`
(8, 18, 24, 38) chỉ kéo theo 1–2 câu sau, drift hồi phục nhanh.

**Với `--max-shift 0` (đè hoàn toàn):** `overlap` = 6 (id 9 0.51s, 15 0.016,
18 0.016, 19 0.232, 25 0.232, 39 0.059) — cho thấy nếu không dời thì id 9
sẽ đè 0,51s lên đuôi id 8. (Lần chạy này đã bị ghi đè bởi `--force` ở mặc định.)

**Kiểm tra độc lập với `render.json` (đọc thẳng `voice_track.wav`)**
- `wave`: 1 kênh, sampwidth 2, 24000 Hz, 243,554s.
- RMS `[5.4, 5.9]s` = **0,0** (id 1 dài 5,208s, hết trước 5,4s); RMS
  `[6.2, 6.7]s` = **5401,5** (id 2 bắt đầu ở 6,0s, không bị dời).
- 40 khoảng trống ≥ 0,3s giữa các placement liên tiếp: cả 40 có RMS **bằng
  đúng 0**. Ba khoảng "1,0s của video": id 6→7 = 2,712s, 29→30 = 1,128s,
  43→44 = 1,672s (audio ngắn hơn slot nên khoảng trống thực lớn hơn 1,0s),
  đều RMS 0.
- RMS nhỏ nhất trên toàn đoạn một placement: **2393,5 (id 8)** — câu
  `too_long` tempo 1.25, vẫn > 200 rất xa; kế tiếp id 29 (3045), id 23 (3074).

**`output_vi.mp4`** (`ffprobe`): 1 stream `h264` 640x360 (7299 frame) + 1
stream `aac` 44100 Hz **stereo**; duration 243,553991s so với source
243,554104s (lệch 0,0001s). md5 video stream (`-map 0:v:0 -c copy -f md5`):
**khớp** giữa `source.mp4` và `output_vi.mp4` (`e3d68bb2…62314ce`) → không
encode lại video.

**Mức âm (`volumedetect`)**

| file | mean_volume | max_volume |
|---|---|---|
| `source.mp4` | −20,7 dB | 0,0 dB |
| `output_vi.mp4` (original 0.30, mặc định) | −19,8 dB | −1,3 dB |
| `output_vi.mp4` (original 0.50) | −19,2 dB | −0,5 dB |

`max_volume` ≥ −0,1 dB (ngưỡng nghi clip của spec) không xảy ra ở cả hai;
`alimiter=0.95` giữ đỉnh dưới ~−0,45 dB. Source gốc đã chạm 0,0 dB nên đỉnh
0,5 phản ánh audio gốc chứ không phải giọng thuyết minh.

**Resume:** lần 2 SKIP cả hai (mtime hai file không đổi); lần 3 SKIP voice
(mtime giữ nguyên 07:13:53), `output_vi.mp4` mới hơn và `render.json` có
`output.params.original_volume = 0.5`; lần 4 voice + mux dựng lại
(`voice_track.params.max_shift_seconds = 0.0`, `overlap` > 0 ở id 9 = 0.51);
lần 5 cả hai mới hơn, `output.params.original_volume` về 0.3 và
`max_shift_seconds` về 1.0.

---

## E. Việc chưa làm

- **Nghe thử bằng tai người** (đã nêu "Ngoài phạm vi" của spec): chất lượng
  giọng ở tempo 1.25 quanh 0:33–0:36 (id 8); độ to/nhỏ audio gốc ở
  `original_volume` 0.30 so với 0.50; có nên hạ `timing.max_tempo` hay đổi
  `original_volume`. Số liệu (RMS/mức âm) đều ổn nhưng không thay thế tai.
- Ducking động (sidechaincompress), source separation (plan §16).
- Rút gọn câu `too_long` bằng LLM (CP9).
- Stream-hoá dựng track cho video rất dài (xem B7).
- `dub` end-to-end + `app/pipeline/*` (CP7), playlist (CP8).

# Checkpoint 7 — Các quyết định nhỏ khi triển khai

Spec: `docs/specs/cp-7.md`. Mục **[CẦN DUYỆT]** là chỗ Opus nên xem lại; mục
**[CP8]** là thứ CP8 (playlist) phải biết.

---

## A. Contract với CP8 — đọc kỹ nhất

### A1. `run_dub()` là hàm CP8 sẽ gọi cho từng video [CP8]

```python
def run_dub(
    url: str, config: AppConfig, options: DubOptions, *,
    log: Callable[[str], None] = print,
) -> DubResult
```

`DubOptions`/`DubResult` đúng như spec (không đổi field nào). CP8 (playlist)
nên gọi `run_dub` một lần cho mỗi URL, bắt `DubError` riêng từng video (một
video lỗi không được chặn cả playlist — cùng tinh thần C3 của CP3), tái sử
dụng cùng `AppConfig` cho cả playlist. Không có state file `dub.json`: CP8
nếu cần theo dõi tiến trình cả playlist (đã xong tập nào) phải tự làm việc
đó ở tầng của mình, không dựa vào side-effect nào từ `run_dub`.

### A2. `run_dub` không tạo artifact mới, không đổi schema CP1–CP6.5 [CP8]

Đúng như spec: chỉ gọi lại các hàm stage sẵn có. `render.json`/`translated.json`/...
giữ nguyên schema các checkpoint trước.

### A3. `DubError.stage` dùng để biết dừng ở đâu, không dùng để tự động sửa [CP8]

`stage` là một trong `STAGES = ("download", "transcribe", "translate", "tts",
"normalize", "render")`. CP8 có thể dùng để log "video X lỗi ở stage Y" cho
từng video trong playlist, nhưng **không** nên tự ý retry theo stage (retry
đã nằm trong `run_dub` cho translate/tts/normalize; các lỗi khác — mạng,
ffmpeg thiếu, sai model — retry ở tầng playlist nhiều khả năng chỉ lặp lại
lỗi giống hệt).

---

## B. Quyết định triển khai

### B1. Phát hiện "download SKIP" bằng mtime, không phải `exists()` "trước khi gọi" [CẦN DUYỆT]

Spec viết "skipped_stages: download khi source.mp4 đã có và không force (so
exists() trước khi gọi)". Về mặt kỹ thuật **không thể** literal hoá được:
`episode_dir`/`source_path` chỉ biết được *sau* khi `download_video()` trả
về (nó tự gọi `_extract_info` — một lần gọi mạng — để suy ra tên thư mục từ
`video_id`/`title`), nên không có cách nào `exists()` một đường dẫn ta chưa
biết. Gọi `_extract_info` riêng để "dò trước" sẽ tốn thêm một lần gọi mạng
mỗi lần chạy `dub`, và vẫn có nguy cơ suy ra khác `download_video()` tự làm
(hai lần gọi mạng cho cùng video hiếm khi trả về khác nhau, nhưng không có
gì đảm bảo).

Cách đã làm: ghi `download_started_at = time.time()` **ngay trước** khi gọi
`download_video()`, rồi so `episode.source_path.stat().st_mtime` với mốc đó
sau khi hàm trả về — file cũ hơn mốc = không bị tải lại (SKIP), file mới hơn
mốc = vừa được `_download_source` ghi (không SKIP). Đã kiểm bằng chạy thật:
episode có sẵn (mtime `source.mp4` từ nhiều ngày trước) → SKIP đúng, tổng
`download` stage 2,6s (chỉ mất mạng ở `_extract_info`); workspace mới →
không SKIP (mất 6,5s tải thật).

Rủi ro lý thuyết: lệch giờ hệ thống giữa lúc ghi file và lúc đọc lại (NTFS
mtime độ phân giải cao, không phải vấn đề trên Windows), hoặc `force=True`
(đã loại trừ tường minh bằng điều kiện `not options.force`).

### B2. Log tts/normalize: mỗi vòng tự in cặp `(4/6) tts .../xong` và `(5/6) normalize .../xong` riêng

Bản đầu in `(4/6) tts ...` rồi `(5/6) normalize ...` trước, gộp thời gian
mọi vòng sửa lại mới in `xong` — khi chạy thật log đọc rất khó hiểu (dòng
`(5/6) normalize ...` chen giữa lúc `(4/6) tts` còn chưa có dòng "xong").
Đã đổi: `_run_tts`/`_run_normalize` tự bọc `(i/6) ... / xong` quanh **mỗi**
lần gọi (kể cả các vòng sửa ở bước 7), nên log đọc tuần tự tự nhiên. Thời
gian cộng dồn qua biến `nonlocal` (`tts_seconds`/`normalize_seconds`), skip
chỉ true khi **không vòng nào** thật sự làm việc (mọi lần gọi đều `.skipped`).

### B3. Stage "config sai" quy về stage nào

`validate_mixing` (dùng `original_volume`/`speech_volume`/`max_shift_seconds`)
→ gắn stage `"render"` (tham số chỉ dùng ở đó); `validate_timing_ratios` →
`"normalize"`; `validate_rate_or_volume` cho `tts.rate`/`tts.volume` →
`"tts"`. Thiếu `translation.model` → `"translate"` (đúng spec). Các validate
này với config hợp lệ (đi qua `parse_config`) không bao giờ raise — chỉ có
tác dụng khi ai đó dựng `AppConfig`/`DubOptions` trực tiếp bằng Python với
giá trị sai (vd test, hoặc CP8 tự build config).

### B4. `create_translator`/`create_tts_engine` cũng được bọc `try/except`

Interface spec không nêu rõ, nhưng cả hai có thể raise `TranslationError`/
`TTSError` (provider không hỗ trợ) — bọc để không có đường nào lỗi thoát ra
ngoài dạng "trần" thay vì `DubError`.

### B5. `translate`/`tts`/`normalize` dùng closure nội bộ (`_translate`/`_run_tts`/`_run_normalize`)

Tránh lặp lại đủ bộ kwargs (lấy từ `config`) ở cả lần gọi đầu và vòng sửa;
mỗi closure tự bọc `try/except <LỗiStage>` một chỗ duy nhất.

### B6. `repair_rounds_used` cộng dồn translate + tts/normalize

Đúng field doc spec ("tổng vòng lặp lại"). Thông điệp lỗi ở bước 8
(`DubError("render", ...)`) dùng riêng biến vòng của **chính** bước thiếu
audio (`missing_rounds`), không dùng tổng, để số trong câu báo lỗi phản ánh
đúng số lần đã thử sửa audio (không lẫn số vòng translate nếu có).

### B7. `DubResult.too_long_ids`/`missing_ids` lấy từ đâu

`too_long_ids`: từ lần gọi `normalize_timing` **cuối cùng** (sau mọi vòng
sửa). `missing_ids`: từ `RenderResult.missing_ids` (chỉ khác rỗng khi
`allow_missing=True` và `render_episode` thật sự chèn im lặng — đúng field
doc spec "lấy từ RenderResult").

### B8. `_cmd_dub` validate `original_volume` trước khi gọi `run_dub`

Giống `_cmd_render`: `validate_mixing` chạy ở CLI layer trước khi dựng
`DubOptions`, dù `run_dub` cũng tự validate lại (bước 0) — hai lớp phòng
thủ không thừa vì test CLI cần "`--original-volume 1.5` → exit 1, không gọi
`run_dub`" (kiểm tra ở lớp CLI, không phụ thuộc implementation detail bên
trong `run_dub`).

---

## C. Phát hiện khi chạy thật — cần Opus quyết định

### C0. [CẦN DUYỆT] Whisper phân đoạn lại khác hẳn lần trước cho cùng một video (36 vs 58 segment)

Chạy thật bước 2 (workspace mới, cùng URL/model/`whisper.model: medium` với
episode gốc CP1-6.5) ra **36 segment** thay vì 58 của episode cũ trong
`output/`. So hai transcript: bản cũ chia câu rất mịn (gần một câu/dòng,
vd `id 2 "Guess how much I love you." (6-9s)`, `id 3 "By Sam McBratney, an
illustrated by Anita Jerm." (9-14s)`), bản mới gộp nhiều câu một segment (vd
`id 2 "Guess How Much I Love You by Sam McBrattney and illustrated by..."
(6-15s)`). Cùng `model_size=medium`, `device=auto`, `compute_type=auto`,
cùng file `source.mp4`/`audio.wav` xét về nội dung (tải lại từ đúng URL).
Không đổi tham số nào ở CP7 — `transcribe_audio()` được gọi y hệt cách
`_cmd_transcribe` gọi trước đây. Nghi ngờ nhiều nhất: model faster-whisper
tải lại (cache HF Hub) có thể khác phiên bản/quantization so với lần chạy
CP1-6.5 cũ (vài tuần trước), hoặc `device=auto` lần này chọn GPU còn lần
trước là CPU (ảnh hưởng VAD/beam search) — **chưa xác minh được nguyên
nhân**, không tự đổi tham số. Hệ quả xuôi dòng: `too_long` bước 2 ra **0**
(không phải áp lực timing như spec kỳ vọng) vì segment dài hơn có `slot`
cũng dài hơn tương ứng; văn bản dịch (do gộp câu) khác thoại gốc điểm ngắt
so với bản cũ nhưng không kiểm tra được xưng hô ba–con vì transcript này
(đọc truyện) không có hội thoại nhiều nhân vật.

### C1. [CẦN DUYỆT] `synthesize_translation` luôn ghi lại `tts/manifest.json` dù không có việc gì làm

Quan sát khi chạy thật (mục D bên dưới, resume trên episode có sẵn):
`tts/manifest.json` đổi mtime dù log in `tổng hợp 0, cache 57` và
`TTSResult.skipped == True`. Đọc `app/tts/synthesize.py`: `write_manifest()`
được gọi **vô điều kiện** ở cuối hàm (dòng ~340, sau nhánh
`if pending and not synthesized_ids...`), không có nhánh bỏ qua khi
`pending` rỗng — nội dung file giống hệt lần trước (đã kiểm bằng `diff`,
xem D2), chỉ mtime đổi.

Đây là hành vi có từ CP4, **không phải lỗi do CP7 gây ra** — `dub` chỉ gọi
lại đúng như `_cmd_tts` vẫn làm. Nhưng nó khiến acceptance criteria của
spec CP7 ("`tts/manifest.json` không đổi" ở bước Chạy thật #1) không đạt
theo nghĩa đen (mtime đổi, nội dung không đổi). Tôi **không tự sửa**
`synthesize.py` (đây là sửa hành vi một hàm stage — theo luật phải escalate,
không tự quyết). Hai hướng xử lý: (a) chấp nhận vì nội dung không đổi và
`.skipped=True` vẫn đúng ngữ nghĩa, chỉ sửa lại câu chữ acceptance criteria
của spec; (b) sửa `synthesize_translation` chỉ `write_manifest()` khi có
thay đổi thật (thêm điều kiện `if pending or ...`). Đề xuất (a) vì rủi ro
thấp hơn và không phải lo ảnh hưởng ngược tới CP4-6.5 đã chạy thật ổn định.

### C2. Bước 4 (xoá 1 mp3 rồi chạy lại): `normalize`/`render` SKIP chứ không "dựng lại" như spec dự đoán

Spec ghi acceptance "normalize/render dựng lại". Thực tế đo được: xoá
`tts/000001.mp3` rồi chạy lại `dub` → `tts` tổng hợp đúng 1 (`tổng hợp 1,
cache 35`), nhưng `normalize` và `render` đều **SKIP**. Lý do: fingerprint
của `normalize_timing` dựa trên `(id, start, end, tts_status, tts_cache_key)`
— không dựa trên nội dung/mtime file mp3. `cache_key` chỉ phụ thuộc
text+voice+rate+volume (không đổi vì text không đổi), nên dù file mp3 bị
tổng hợp lại, `cache_key` giống hệt lần trước → `normalize` coi như không
có gì đổi → SKIP; `render` cũng SKIP theo vì `normalized.json` không đổi.
Đây là hành vi **đúng** theo thiết kế cache của CP4/CP5 (âm thanh tổng hợp
lại từ cùng text/voice/rate được coi là tương đương, không cần dựng lại
track/mux tốn thời gian) — không phải lỗi CP7, chỉ là dự đoán của spec
không khớp với cách CP4/CP5 đã cắm cache. Không cần sửa gì; nêu ở đây để
Opus biết acceptance criteria bước 4 của spec cần đọc lại (kỳ vọng "dựng
lại" nên đổi thành "SKIP vì cache_key không đổi — chỉ tts tổng hợp lại").

---

## D. Số liệu đo được (episode thật, URL
`https://www.youtube.com/watch?v=zGuIUytF_6U`, ~4 phút, RTX 3050 6GB,
`gemma3:12b`, `whisper.model: medium`)

### D1. Bước 1 — resume trên episode CP1-6.5 có sẵn (`output/`, 58 segment)

Tất cả 6 stage SKIP, tổng **2,7s** (chủ yếu `_extract_info` mạng: download
2,6s). `translate`/`tts` không gọi model/mạng TTS (log chỉ có
`[tts] ... segment dùng lại từ cache`, không có dòng `ok (Xs)`). Không có
dòng nhắc glossary (tập đã có `glossary.yaml` từ CP6.5). `output_vi.mp4`/
`translated.json` mtime **không đổi**; `tts/manifest.json` mtime **có đổi**
(xem C1 — hành vi có từ CP4, không phải do CP7).

### D2. Bước 2 — workspace mới (`output/cp7-e2e/`, 36 segment — xem C0)

| Stage | Thời gian |
|---|---|
| download | 6,5s |
| transcribe | 69,7s (whisper `medium`, CPU/GPU tự chọn) |
| translate | 231,1s (2 batch: 170,1s + 61,0s — `gemma3:12b`, GPU thấy ở `ollama ps` ~37-63% GPU/CPU) |
| tts | 133,7s (gồm 1 vòng sửa: 12 segment lỗi tạm thời "No audio was received" từ edge-tts, tự phục hồi hết ở vòng 1/2) |
| normalize | 1,9s |
| render | 7,4s |
| **Tổng** | **450,4s (~7,5 phút)** |

`render.json`: `summary = {placed: 36, silent: 0, missing: 0, shifted: 1,
overlap: 0, max_shift_seen: 0.24}`; `output.duration = 243.554` (khớp
episode gốc — cùng video). `ffprobe`: video `h264`, audio `aac 44100 2ch`.
`translated.json`: `glossary_sha256: null`, `failed_ids: []`. `too_long: 0`
(xem C0 — segment dài hơn nên slot cũng dài hơn tương ứng, không phải dấu
hiệu chất lượng). `sửa lại: 1 vòng` (đúng cơ chế tự sửa thiếu audio, không
cần người can thiệp).

### D3. Bước 3 — chạy lại lệnh 2

Tất cả 6 stage SKIP, tổng 2,6s. `output_vi.mp4`/`translated.json` mtime
không đổi; `tts/manifest.json` đổi (C1).

### D4. Bước 4 — xoá `tts/000001.mp3` rồi chạy lại

`tts`: `tổng hợp 1, cache 35`. `normalize`/`render`: **SKIP** (xem C2, khác
spec dự đoán "dựng lại"). `translate`: SKIP. Tổng 3,2s.

### D5. Bước 5 — tạo glossary rồi chạy lại

`python -m app glossary` tạo `glossary.yaml` (2 characters, 2 address, 0
terms). Chạy lại `dub` (không `--force`): log `[translate] glossary đã thay
đổi kể từ lần dịch — dịch lại từ đầu.`; dịch lại **34/36** câu (`2 segment
dùng lại từ cache` ở tts vòng đầu, tức 34 câu đổi bản dịch); `tts` vòng đầu
lại gặp 7 lỗi tạm thời edge-tts, tự sửa qua **2 vòng** (5 câu ở vòng 1, 2 câu
còn lại ở vòng 2) — đúng giới hạn `repair_rounds: 2`, không có `DubError`.
Tổng 349,7s. `translated.json.glossary_sha256` khác `null` sau khi chạy.

### D6. Bước 6 — bẫy ngôn ngữ (`--source-lang zh` trên workspace đã có transcript `en`)

Exit 1 ngay sau stage transcribe (download SKIP 2,2s, không gọi translate).
stderr: `[transcribe] transcript.json đang là ngôn ngữ 'en', khác
--source-lang 'zh' vừa truyền. Chạy: python -m app transcribe "<ep>"
--source-lang zh --force rồi chạy lại dub.` `transcript.json` mtime không đổi.

### D7. Bước 7 — mở bằng tai/mắt

**Chưa nghe bằng tai** (agent không có khả năng phát âm thanh). Đã kiểm
gián tiếp: `ffprobe` xác nhận có đúng 1 stream video (h264) + 1 stream audio
(aac 44100 stereo); `ffmpeg -af volumedetect` trên `output_vi.mp4`:
`mean_volume -20.3 dB`, `max_volume -2.0 dB` (không im lặng, không clip,
cùng thang với số liệu CP6 mục D: `-19.8`/`-1.3 dB`). Cần người nghe thật
để xác nhận chất lượng giọng + mix — nợ giống CP6.

### D8. `ollama ps` trong lúc dịch

`gemma3:12b … 63%/37% CPU/GPU … 8192 context` — có dùng GPU (không rơi vào
bug "100% CPU" của CP6.5 D0).

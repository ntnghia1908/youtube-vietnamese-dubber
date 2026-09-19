# Checkpoint 8 — Các quyết định nhỏ khi triển khai

Spec: `docs/specs/cp-8.md` (đã có SỬA ĐỔI 1 — luồng tải song song với luồng
xử lý, thêm giữa chừng). Mục **[CẦN DUYỆT]** là chỗ Opus nên xem lại; mục
**[CP9]** là thứ CP9 phải biết.

---

## A. Contract với CP9 — đọc kỹ nhất

### A1. `run_playlist()` là hàm CP9 (nếu có) sẽ gọi/mở rộng [CP9]

```python
def run_playlist(
    url: str, config: AppConfig, options: PlaylistOptions, *,
    log: Callable[[str], None] = print,
) -> PlaylistResult
```

`PlaylistOptions`/`PlaylistResult`/`EpisodeOutcome` đúng như spec, cộng
thêm `PlaylistOptions.download_only: bool = False` (SỬA ĐỔI 1). Không có
state file nào khác ngoài `<playlist_dir>/playlist.json` — mọi tiến trình
nằm trong đó.

### A2. Schema `playlist.json` thêm field `"downloaded": true|false` mỗi entry [CP9]

```json
{"index": 1, "video_id": "...", "title": "...", "url": "...",
 "status": "pending|completed|failed",
 "downloaded": true,
 "episode_dir": "vid__title", "output_path": "vid__title/output_vi.mp4",
 "error_stage": null, "error": null, "warnings": null,
 "seconds": 12.3, "updated_at": "..."}
```

- `downloaded` tách RIÊNG khỏi `status`: theo dõi việc **tải video** xong
  chưa, độc lập với kết quả xử lý (transcribe/translate/tts/render).
  `episode_dir` được ghi ngay khi tải xong — **trước** khi `run_dub` chạy,
  nên có thể khác `None` ngay cả khi `status` vẫn `"pending"`.
- Trên **lỗi ở stage `download`** (do luồng tải, không phải `DubError`):
  `episode_dir`/`output_path` = `null`, `downloaded = false`,
  `error_stage = "download"`, `error` có dạng `"[download] <thông điệp
  VideoDownloadError>"` — cùng format `"[stage] message"` với `DubError`
  để CLI hiển thị dòng LỖI thống nhất bất kể nguồn lỗi.
- Trên **lỗi ở stage khác** (`DubError` từ `run_dub`, ví dụ `translate`):
  **khác CP7/bản đầu của CP8** — `episode_dir` **KHÔNG** bị xoá về `null`
  nữa (video đã tải xong thật, giữ lại để lần sau khỏi tải lại); chỉ
  `output_path` về `null`. Xem quyết định B4.
- `seconds` cho tập thành công = thời gian luồng tải đo được (tải thật hoặc
  gần 0 nếu dùng cache `load_episode_info`) **cộng** tổng
  `result.stage_seconds.values()` (trong đó `stage_seconds["download"]`
  luôn là `0.0` vì `run_dub` không tự tải nữa) — xem B5.

### A3. `run_dub()` thêm keyword-only `episode: EpisodeInfo | None = None` [CP9]

```python
def run_dub(
    url: str, config: AppConfig, options: DubOptions, *,
    log: Callable[[str], None] = print,
    episode: EpisodeInfo | None = None,
) -> DubResult
```

- `episode` khác `None` → bỏ qua hoàn toàn `download_video` (không gọi
  mạng YouTube lần 2), dùng thẳng `episode`; `"download"` được ghi vào
  `skipped_stages`, `stage_seconds["download"] = 0.0`, log
  `(1/6) download SKIP (0.0s)`.
- `episode=None` (mặc định) → giữ nguyên hành vi CP7 y hệt. `dub` đơn lẻ
  (CLI) **không đổi**, luôn gọi với `episode=None`.
- `app/youtube/download.py` có thêm `load_episode_info(episode_dir, url)
  -> EpisodeInfo`: dựng lại `EpisodeInfo` từ `metadata.json` có sẵn, không
  gọi mạng — dùng bởi luồng tải của `playlist` khi entry đã `downloaded`.

### A4. `outcome` của `EpisodeOutcome` có thêm giá trị `"downloaded"` khi `download_only=True` [CP9]

Bốn giá trị gốc (`completed|skipped|failed|not_run`) áp dụng khi
`download_only=False`. Khi `download_only=True`, outcome của một tập tải
thành công là `"downloaded"` (không phải `"completed"` — pipeline chưa
chạy), `result` luôn `None`. `status` trong `playlist.json` **không đổi**
sau một lần `download_only` thành công (không tự chuyển `pending`, xem C5)
— chỉ `downloaded`/`episode_dir` được cập nhật.

---

## B. Quyết định triển khai (SỬA ĐỔI 1 — luồng tải song song)

### B1. Kiến trúc: một `threading.Thread` daemon tải tuần tự, `threading.Event` mỗi tập, một `threading.Lock` dùng chung

- Trước khi tạo luồng: tính trước `skip_flags` (tập nào sẽ `skipped`) trên
  snapshot state **một lần duy nhất** — dùng chung cho cả việc quyết định
  luồng tải có tải tập đó không (`to_download_indexes`) lẫn vòng lặp xử lý
  (tránh hai nơi tính khác nhau do state bị luồng kia sửa giữa chừng).
- `download_events: dict[index, threading.Event]` — luồng chính
  `.wait()` đúng event của tập sắp xử lý trước khi gọi `run_dub`.
- `download_outcomes/download_seconds: dict[index, ...]` — kết quả
  (`EpisodeInfo` hoặc `VideoDownloadError`) và thời gian tải mỗi tập.
- Mọi chỗ sửa entry + `_write_json_atomic` (cả hai luồng) đều nằm trong
  `with entries_lock:` — hai luồng có thể cùng ghi `playlist.json` gần như
  đồng thời (luồng tải ghi khi vừa tải xong tập N+1, luồng chính ghi khi
  vừa xử lý xong tập N).
- Dừng sớm/Ctrl+C: `stop_download.set()` trong `finally` của vòng lặp
  chính (chạy dù thành công, lỗi, `DubError`, hay exception khác nổi lên);
  luồng tải tự kiểm tra cờ này ở đầu mỗi vòng lặp tập. `join(timeout=5.0)`
  — không chờ vô hạn (SỬA ĐỔI 1 yêu cầu), nhưng đủ cho đường chạy bình
  thường (tải luôn nhanh hơn nhiều so với transcribe/translate/tts).

### B2. Tránh gọi mạng khi tập đã `downloaded`: kiểm tra `source.mp4` + `metadata.json` còn trên đĩa

`use_cache = entry["downloaded"] and not options.dub.force`. Nếu true VÀ
cả hai file còn tồn tại → `load_episode_info` (không mạng); nếu file mất
(người dùng xoá tay, hoặc đĩa hỏng) → rơi về `download_video` bình thường
(coi như chưa tải). `--force` luôn bỏ qua cache, gọi `download_video` lại
từ đầu — nhất quán với ý nghĩa "làm lại toàn bộ" của `--force`.

### B3. Lỗi tải (`VideoDownloadError`) ghi `failed` như `DubError`, nhưng KHÔNG tính vào bộ đếm dừng sớm (sửa khi review)

Không có `DubError` riêng cho tải (tải xảy ra ở tầng `playlist`, không qua
`run_dub`) — `_register_failure()` dùng chung cho cả hai loại lỗi, chỉ
khác `stage` (`"download"` so với `exc.stage` của `DubError`) và cách format
`error` (`f"[download] {exc}"` so với `str(DubError)`, cả hai cùng dạng
`"[stage] message"`).

Bản đầu tính cả lỗi tải vào `max_consecutive_failures`. Playlist thật có
EP13–21 là **Private video** (flat trả `title=None`, `duration=None`;
`extract_info` báo `DownloadError: Private video`) → chạy cả playlist sẽ
dừng ở EP15, không bao giờ tới EP22. Đã đổi: lỗi stage `download` không
tăng và không reset bộ đếm. Lỗi tải chỉ tốn vài giây; bộ đếm tồn tại để chặn
lỗi hệ thống làm phí hàng giờ xử lý (Ollama tắt, ffmpeg hỏng).

Cũng sửa khi review: luồng tải bắt mọi exception và luôn `set()` event trong
`finally` (trước đây lỗi lạ khiến luồng chính chờ event mãi); luồng chính
raise lại exception không phải `VideoDownloadError`. Chờ event theo nhịp
`wait(0.5)` để Ctrl+C luôn ngắt được.

### B4. [CẦN DUYỆT] Trên `DubError` (lỗi ở stage sau download), `episode_dir` được GIỮ LẠI thay vì xoá về `null`

Spec gốc (trước SỬA ĐỔI 1) mô tả `episode_dir = null` khi một tập `failed`.
Sau khi tách luồng tải, `episode_dir` được ghi ngay khi tải xong — nếu
`run_dub` fail ở `translate` (ví dụ Ollama tắt), video **đã tải thật** và
vẫn còn trên đĩa; xoá `episode_dir` về `null` sẽ khiến lần chạy sau tưởng
chưa tải, tải lại tốn mạng vô ích dù `downloaded: true` đã ghi đúng. Đã đổi
sang: `DubError` chỉ xoá `output_path` (render chưa xong), giữ nguyên
`episode_dir`. Chỉ lỗi thật sự ở stage `download` mới có `episode_dir =
null` (vì chưa từng tải được). Đề xuất giữ vì nhất quán với mục tiêu của
SỬA ĐỔI 1 (tránh tải lại) — Opus xem lại có đồng ý không.

### B5. `seconds` của một tập = thời gian tải (đo bởi luồng tải) + tổng `stage_seconds` của `run_dub`

`run_dub` không còn đo được thời gian tải thật (luôn `0.0` khi có
`episode=`), nên `playlist` tự cộng thêm để `seconds` trong
`playlist.json` vẫn phản ánh đúng tổng thời gian thực tế của tập (dùng để
ước lượng tốc độ playlist — mục D). Với tập lấy từ cache
(`load_episode_info`), phần tải gần như `0`.

### B6. `--download-only`: `status` KHÔNG tự chuyển, chỉ `downloaded`/`episode_dir` đổi

Đã cân nhắc tự chuyển `status: "failed" (error_stage=download)` →
`"pending"` khi tải lại thành công ở chế độ `--download-only`, nhưng chọn
**không làm** để giữ code đơn giản (nhánh `download_only` trong vòng lặp
chính không cần lock/ghi state — luồng tải đã ghi đủ). Hệ quả: nếu một tập
từng fail ở `download` rồi được `--download-only` tải lại thành công,
`status` vẫn hiển thị `"failed"`/`error_stage: "download"` cho tới khi một
lần `dub` (không `download_only`) thật sự chạy qua tập đó — chấp nhận vì
`--download-only` là bước chuẩn bị, không phải kết quả cuối. Ghi ở đây để
không bị hiểu nhầm là bug khi đọc `playlist.json` giữa hai bước.

### B7. Không thêm `DubError`/exception riêng cho lỗi tải — bắt `VideoDownloadError` trực tiếp ở tầng playlist

Giữ đúng tinh thần CP7 A3 (`DubError.stage` không dùng để tự động sửa) —
lỗi tải được xử lý tại chỗ trong `run_playlist`, không đi qua `run_dub`
nên không cần bọc thành `DubError`.

---

## C. Quyết định triển khai (phần còn lại của spec gốc, trước SỬA ĐỔI 1)

### C1. `app/pipeline/__init__.py` re-export cả `run_dub` lẫn `run_playlist`

Spec ghi "export thêm ... (theo cách đang export `run_dub`)" nhưng thực tế
CP7 **không** re-export `run_dub` ở `__init__.py` (docstring cũ nói rõ "Không
re-export gì"). Đã kiểm: `dub.py`/`playlist.py` chỉ import các thư viện
nặng (yt-dlp, faster-whisper, Ollama, edge-tts) **bên trong hàm**, không ở
cấp module — nên eager-import cả hai vào `__init__.py` không kéo theo
dependency nặng nào lúc `import app.pipeline`. Đã xác minh bằng
`python -c "import app.pipeline as p"` chạy tức thời, không lỗi thiếu
thư viện. Quyết định: export đầy đủ `run_dub, DubOptions, DubResult,
DubError, run_playlist, PlaylistOptions, PlaylistResult, PlaylistError,
EpisodeOutcome, parse_item_spec` — vừa khớp yêu cầu spec vừa không có rủi
ro loại CP7 lo ngại.

### C2. `_add_dub_arguments`/`_resolve_dub_options` dùng chung giữa `dub` và `playlist`

`_resolve_dub_options(args, config, *, prefix)` nhận thêm `prefix` (khác
chữ ký gợi ý trong spec `_resolve_dub_options(args, config) -> DubOptions |
None`) để thông báo lỗi đúng tiền tố `[dub]`/`[playlist]` — không đổi hành
vi `dub` (test cũ vẫn `assertIn("[dub] LỖI", ...)`).

### C3. `parse_item_spec` lỗi rõ từng trường hợp

Không dùng một message chung "sai cú pháp" — mỗi nhánh lỗi (`rỗng`, thiếu
số ở `A-B`, `A > B`, không phải số nguyên `>= 1`) có message riêng để
người dùng sửa ngay không cần đoán.

### C4. `_output_exists` có fallback qua `episode_dir + OUTPUT_FILENAME`

Trường hợp hiếm `output_path` trống nhưng `episode_dir` có (state cũ méo,
hoặc entry vừa được luồng tải ghi `episode_dir` nhưng chưa qua `run_dub`)
— dùng đúng hằng số `OUTPUT_FILENAME` của CP6 thay vì đoán tên file.

### C5. Merge giữ `downloaded` như các field khác trong `_CARRIED_FIELDS`

Tập bị bỏ khỏi playlist không xoá thư mục (giữ nguyên hành vi #2 của
spec); tập mới → `downloaded: false` mặc định giống `status: "pending"`.

---

## D. Số liệu đo được (playlist thật)

Playlist: `https://www.youtube.com/playlist?list=PLJVKAfvqjvcp9lhYU37emhlRZExZrx0Cm`
("Guess How Much I Love You: Compilations!", 22 tập, tiếng Anh — cùng
series đã dùng ở CP7), `whisper.model: medium`, `translation.model:
gemma3:12b`, RTX 3050 6GB. **Khác CP7**: mọi tập trong playlist này dài
18–36 phút (không phải video 4 phút của CP7), episode 1 ra **353 segment**.

- `fetch_playlist`: 22 entry, khớp đúng số tập trên trang YouTube (kiểm tay).
  Entry 13–21 có `title: "untitled"` (yt-dlp flat không trả title — có thể
  video private/không công khai; **chưa xác nhận được** vì không thử tải,
  xem mục F).
- `--download-only --items 1-3`: 3/3 `downloaded`, `ffprobe` xác nhận cả 3
  `source.mp4` có đủ stream `h264`+`aac`. Tổng vài giây (chỉ mạng tải, không
  Whisper/Ollama).
- `--items 1` (sau download-only): log `(1/6) download SKIP (0.0s)` — xác
  nhận `episode=`/cache tải hoạt động đúng qua wire (không phải chỉ mock).
  `transcribe` 51.4s (18 phút audio, `medium`). `translate` 353 segment,
  15 batch, **1811.1s (~30 phút)**: có 1 batch lỗi output (`thiếu id 350`)
  tự chia đôi và dịch xong đúng theo cơ chế CP3. `tts` (concurrency=4): tỷ
  lệ lỗi tạm thời "No audio was received" cao bất thường (~20–25% permanent
  fail sau 3 lần thử ở mỗi id, đo trên ~100 id đầu) — xem mục F1.
  **Dừng tay (kill process) giữa chừng tts để dành thời gian cho bước quan
  trọng hơn (SỬA ĐỔI 1 concurrency)**; artifact còn lại (`translated.json`
  đủ 353 segment, ~104 file `tts/*.mp3` đã cache) chứng minh resume an toàn
  sau khi bị kill cứng (không qua KeyboardInterrupt).
- `--items 4-5` (EP04/EP05 chưa từng tải): **bằng chứng trực tiếp luồng tải
  chạy song song** — log thật (không mock):
  ```
  [playlist-dl] EP04 tải ...
  [EP04/22] Guess How Much I Love You: Compilation - Little White Owl's Stories ...
  [playlist-dl] EP04 xong (12.1s)
  [playlist-dl] EP05 tải ...
  [EP04] [dub] (1/6) download ...
  [EP04] [dub] (1/6) download SKIP (0.0s)
  [EP04] [dub] (2/6) transcribe ...
  [playlist-dl] EP05 xong (10.4s)          <- EP05 tải xong TRONG LÚC EP04 đang transcribe
  [EP04] [dub] (2/6) transcribe xong (55.3s)
  ```
  `playlist.json` tại thời điểm này: EP04/EP05 `"downloaded": true`,
  `episode_dir` đã ghi, `status` vẫn `"pending"` (đúng B6/A2 — tách biệt
  tải và xử lý). Dừng tay sau khi translate EP04 bắt đầu (batch 1/9 DONE
  136.9s) để kịp viết báo cáo.

---

### D-review. Chạy thật sau khi sửa review (Opus)

- `playlist --download-only` cả playlist: 22 tập, `downloaded 13 | failed 9`,
  không abort. EP13–21 lỗi `Please sign in` (Private video), EP22 tải xong
  (16.3s). 13 `source.mp4` đều có `video audio` (ffprobe). Exit 1 (đúng: có failed).
- Chạy lại `--download-only --items 1-12,22`: cả 13 tập `xong (0.0s)` —
  `load_episode_info`, không gọi mạng.
- `playlist --items 1 --source-lang en --allow-missing` (EP1, 17:50 phút,
  353 segment; translate đã xong từ lần chạy trước bị kill): download/transcribe/translate
  SKIP, tts 104.1s, normalize 32.7s, render 39.5s → `completed`, exit 0.
  `output_vi.mp4` h264+aac, 1069.88s (= source). `missing_ids` rỗng — edge-tts
  lần này không lỗi câu nào (F1 không tái hiện; khả năng cao là rate-limit tạm thời).
  **`too_long` 79/353 (22%)** — cao, xem lại `timing.max_tempo`/độ dài câu dịch ở CP9.
- Chạy lại `--items 1`: `skipped 1`, không có dòng `[EP01] [dub]`, tổng 2.1s, exit 0.
- Chưa chạy thật: bước 3–4 (OLLAMA_HOST hỏng rồi sửa), bước 6 (Ctrl+C) — chỉ
  có unit test.

## F. Phát hiện quan trọng khi chạy thật — CẦN OPUS QUYẾT ĐỊNH

### F1. [CẦN DUYỆT] edge-tts tỷ lệ lỗi vĩnh viễn ~20–25% trên episode dài (300+ segment)

Khác hẳn số liệu CP7 (36 segment, 12 lỗi tạm thời, tự phục hồi hết ở vòng
1/2 — 0% lỗi vĩnh viễn). Ở episode 353 segment, đo trên ~100 id đầu:
khoảng 23 id `failed` hẳn (hết 3 lần thử) dù lỗi luôn là "No audio was
received" (transient theo thiết kế CP4). Nghi ngờ nhiều nhất: edge-tts
(dịch vụ không chính thức của Microsoft Edge) rate-limit theo IP khi tần
suất request cao kéo dài (concurrency=4 chạy liên tục nhiều phút) — chưa
xác minh được nguyên nhân chính xác (không phải do playlist/CP8, hành vi
nằm ở CP4). Hệ quả cho playlist có video dài: `repair_rounds: 2` (mặc
định) nhiều khả năng **không đủ** xoá hết `missing_ids` cho episode
300+ segment → `render` báo lỗi cần `--allow-missing` thay vì tự hoàn
thành. Không tự sửa (ngoài phạm vi CP8 — thay đổi retry/concurrency của
CP4). Đề xuất Opus cân nhắc: (a) tăng `pipeline.repair_rounds` mặc định
cho playlist dài, (b) giảm `tts.concurrency` mặc định, hoặc (c) coi đây là
giới hạn đã biết, khuyến nghị `--allow-missing` cho playlist tập dài.

### F2. [CẦN DUYỆT] Playlist mục tiêu có tập rất dài (18–36 phút/tập) — "Chạy thật" đầy đủ tốn nhiều giờ thực tế

Một tập 353 segment: transcribe 51s + translate 1811s (~30 phút) + tts dự
kiến 40–70 phút (kể cả vòng sửa) + render vài giây ≈ **~1.5–2 giờ/tập**.
22 tập ≈ **có thể hơn một ngày** nếu chạy hết. Do đó **không hoàn thành
được đủ 7 bước "Chạy thật" của spec** (đặc biệt bước 3–4: hỏng Ollama rồi
sửa và chờ dịch lại xong hẳn) trong phiên làm việc này — xem mục "Chưa
làm" trong báo cáo cuối. Đã ưu tiên chứng minh **đúng hành vi mới** (SỬA
ĐỔI 1 — tải song song, cache tải, download-only) bằng chạy thật ngắn thay
vì một lần chạy đầy đủ. Đề xuất Opus: chấp nhận bằng chứng từng phần này,
hoặc chỉ định video ngắn hơn để hoàn thành đủ 7 bước.

---

## G. Việc chưa làm / ngoài phạm vi

- Xử lý (transcribe/translate/tts/render) song song nhiều tập — chỉ *tải*
  chạy song song (đúng SỬA ĐỔI 1).
- Tự nạp glossary cấp playlist.
- Retry theo stage ở tầng playlist; retry yt-dlp khi fetch playlist lỗi.
- `--force` từng stage.
- `status` tự đồng bộ lại sau `--download-only` khi lỗi trước đó là
  `error_stage="download"` (xem B6).

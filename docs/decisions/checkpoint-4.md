# Checkpoint 4 — Các quyết định nhỏ khi triển khai

Plan không quy định các điểm dưới đây nên người triển khai tự chọn. Ghi
lại để review trước khi sang CP5. Mục **[CẦN DUYỆT]** là trade-off nên
chốt lại; mục **[CP5]**/**[CP6]** là thứ checkpoint sau phải biết khi đọc
`tts/manifest.json`.

---

## A. Contract với CP5/CP6 — đọc kỹ nhất

### A1. Schema `tts/manifest.json` [CP5][CP6]

```json
{
  "provider": "edge", "voice": "vi-VN-HoaiMyNeural", "rate": "+0%", "volume": "+0%",
  "segments": [
    {"id": 1, "status": "ok", "file": "000001.mp3", "cache_key": "9f2c…", "text": "Chào mừng…"},
    {"id": 17, "status": "empty", "file": null, "cache_key": null, "text": ""},
    {"id": 23, "status": "failed", "file": null, "cache_key": null, "text": "…", "error": "…"}
  ]
}
```

- `segments` đúng thứ tự và đủ id như `translated.json` tại thời điểm chạy
  lệnh `tts` gần nhất — **không phải** lúc nào cũng đủ id nếu
  `translated.json` bị sửa tay giữa hai lần chạy mà chưa chạy lại `tts`.
- **CP5/CP6 chỉ được đọc entry có `status == "ok"`** để lấy audio, tuyệt
  đối không tự `glob("*.mp3")` trong `tts/` — file mồ côi (segment cũ đã
  bị xoá khỏi `translated.json` hoặc text đổi thành rỗng) bị dọn ở cuối
  stage, nhưng vẫn có khoảng thời gian ngắn trong lúc chạy mà thư mục có
  thể lẫn cả file không còn hợp lệ.
- `file` là tên **tương đối** trong `tts/` (vd `"000001.mp3"`), không phải
  đường dẫn đầy đủ — CP5/CP6 tự `tts_dir / entry["file"]`.
- Một `id` trong `translated.json` **không chắc có file**: `status: "empty"`
  (dịch ra chuỗi rỗng hoặc toàn dấu câu) hoặc `status: "failed"` (lỗi hết
  lượt, xem A3) đều có `file: null`. CP5/CP6 phải tự quyết định làm gì với
  khoảng lặng đó (giữ im lặng đúng độ dài gốc, hay báo lỗi tuỳ ngữ cảnh) —
  CP4 không có ý kiến, chỉ đảm bảo không lẫn audio giả.
- `cache_key` chỉ có giá trị khi `status == "ok"`; CP5/CP6 không cần dùng
  tới field này (dành cho CP4 tự resume), nhưng đừng xoá khi ghi lại file
  nếu có sửa manifest — sẽ làm mất cache của CP4 ở lần `tts` kế tiếp.
- `text` là bản text **đã strip()** thực sự gửi cho TTS (không phải
  `translated_text` gốc chưa strip) — dùng để debug nghe không khớp phụ đề.

### A2. Duration/timing của từng segment **không** có trong manifest [CP5]

CP4 không đo/ghi `duration` thật của file mp3 (ngoài phạm vi spec — xem
mục "Điểm phải escalate" của spec CP4). CP5 cần `ffprobe` từng file
`tts/*.mp3` (qua danh sách lấy từ manifest, không tự glob) để biết độ dài
thật và so với `end - start` của segment nhằm tính `tts_rate`/co giãn.
**[CẦN DUYỆT]**: nếu CP5 thấy chi phí ffprobe hàng trăm file lặp lại giữa
các lần chạy đáng kể, có thể đề xuất CP4 ghi thêm `duration` vào entry khi
tổng hợp xong (rẻ vì đã có file ngay lúc đó) — chưa làm ở CP4 vì spec yêu
cầu không tự thêm.

### A3. `status: "failed"` không làm dừng lệnh `tts` (exit 0) [CP5][CP6]

Giống C3 của CP3: một segment lỗi hết `max_attempts` lần được ghi
`status: "failed"` kèm `error`, CLI in `CẢNH BÁO` nhưng vẫn exit 0. CP5/CP6
chạy sau một lệnh `tts` có `failed_ids` khác rỗng thì đang thiếu audio cho
đúng các id đó — nên tự kiểm tra (hoặc để CP7 orchestrate chạy lại `tts`
tới khi `failed_ids == []` trước khi sang bước ghép).

### A4. `synthesize_translation()` là hàm dùng lại được, không chỉ qua CLI

```python
def synthesize_translation(
    translated_path: Path, tts_dir: Path, engine: TTSEngine, *,
    max_attempts=3, concurrency=4, force=False, log=print, sleep=time.sleep,
) -> TTSResult
```

`TTSResult` có `manifest_path`, `synthesized_ids`, `cached_ids`,
`empty_ids`, `failed_ids`, `skipped` — CP7 (pipeline `dub` end-to-end) gọi
thẳng hàm này thay vì shell ra `python -m app tts`, giống cách CP3 gọi
`translate_transcript`.

---

## B. Engine, retry và resume

### B1. `EdgeTTSEngine` khớp đúng chữ ký spec, không cần chỉnh

Đã kiểm tra `inspect.signature` trên `edge-tts==7.2.8` cài thật vào
`.venv` (Python 3.14.7): `Communicate.__init__` nhận đúng
`rate`, `volume`, `receive_timeout` như spec mô tả. Không có gì để
escalate ở mục này.

### B2. `.venv` dùng Python 3.14 — edge-tts cài và chạy được bình thường

Không có vấn đề tương thích được ghi nhận với `edge-tts`, `aiohttp`,
`multidict`, v.v. trên Python 3.14 tại thời điểm CP4 (2026-09-18).

### B3. Cache theo từng segment, không theo cả file

`TTSEngine.cache_key()` = sha256 của
`"\n".join([provider, voice, rate, volume, text])`. Một segment được coi
là "đã xong, không cần gọi lại" khi cả ba điều kiện đúng: manifest cũ có
entry cùng `id`, `status == "ok"`, `cache_key` khớp, **và** file thật tồn
tại với size > 0. Thiếu một trong ba thì tổng hợp lại — cụ thể hoá plan
§13.

### B4. Fail-fast chỉ áp dụng khi CHƯA có bằng chứng cấu hình chạy được

**[FIX sau review]** Bản đầu: hễ segment cần tổng hợp *đầu tiên* trong
danh sách `pending` lỗi hết `max_attempts` lần là `raise TTSError` ngay,
bất kể ngữ cảnh. Bug phát hiện khi test resume thật: nếu lần chạy trước đã
có một số segment `ok` (cache hợp lệ) và segment `failed` từ trước (vd một
câu bị edge-tts từ chối dai dẳng), thì lần chạy sau — segment lỗi đó vẫn
đứng đầu `pending` (vì các segment khác đã cache) — cứ raise mãi mãi,
chặn hẳn playlist dù 57/58 segment đã ổn.

Sửa: fail-fast (raise) chỉ khi `not cached_ids` — tức đây là lần chạy
*hoàn toàn mới* của episode, chưa có gì chứng minh voice/mạng/cấu hình
hoạt động được. Có ít nhất một `cached_ids` (từ manifest cũ, file hợp lệ)
thì coi cấu hình đã được chứng minh chạy tốt trước đó; segment đầu tiên
lỗi hết lượt lúc này chỉ là vấn đề của riêng segment đó (câu khó, hoặc
mạng chập chờn đúng lúc) — ghi `failed_ids`, log CẢNH BÁO, tiếp tục các
segment còn lại, exit 0. Áp dụng cùng điều kiện cho lượt kiểm tra cuối
("toàn bộ `pending` đều lỗi" — trước đây luôn raise, giờ cũng chỉ raise
khi `not cached_ids`).

Test hồi quy:
`test_first_pending_fails_but_has_cache_does_not_raise` — chạy xong một
lần (3 segment ok), sửa text id 1 (đứng đầu `pending`) để luôn lỗi, chạy
lại: không raise, `failed_ids == [1]`, `cached_ids == [2, 3]`. Test cũ
`test_first_segment_fails_completely_raises_and_stops` (lần chạy đầu tiên,
không cache) vẫn giữ nguyên hành vi raise.

### B5. Manifest ghi lại từ thread chính sau mỗi segment, kể cả cached/empty

`write_manifest()` gọi lần đầu ngay sau khi tính xong danh sách
cached/empty (trước khi tổng hợp bất kỳ segment nào), rồi gọi lại sau mỗi
kết quả (fail-fast hoặc từ `ThreadPoolExecutor`). Nhờ vậy kill giữa chừng
chỉ mất đúng phần `pending` chưa xong; các entry cached/empty không bao
giờ bị mất dù tiến trình chết ngay dòng log đầu tiên.

### B6. `--force` không giữ lại entry cũ ngay cả khi cache_key không đổi

Đúng như spec (mục 8): `force=True` bỏ qua toàn bộ manifest cũ (không
load `old_manifest`), nên **lần ghi `write_manifest()` đầu tiên của một
lượt `--force` chỉ chứa các segment "empty"** (không cần mạng, tính được
ngay) — các entry "ok" từ trước bị "biến mất" khỏi manifest cho tới khi
từng segment được tổng hợp lại và ghi vào. Hệ quả đã thấy khi test thật:
`--force` bị kill sớm (ngay lúc đang xử lý segment đầu tiên) thì hầu như
toàn bộ 57 segment còn lại phải tổng hợp lại ở lần chạy sau, dù file mp3
cũ (từ trước `--force`) vẫn còn nguyên trên đĩa — đúng như spec mô tả
("kill giữa chừng khi force thì lần sau không force vẫn resume được nhờ
manifest mới ghi dần", không cam kết giữ được nhiều hơn phần đã ghi
*trong* lượt force đó). Không sửa gì — đây là hệ quả được spec chấp nhận,
không phải bug.

### B7. Đọc `failed_ids` của `translate` trực tiếp từ JSON, không qua `read_translated`

`read_translated()` (CP3) không trả `failed_ids`. CP4 đọc lại file JSON
một lần nữa (`_read_failed_ids`) chỉ để phục vụ dòng log "N segment rỗng,
trong đó M do dịch lỗi" — lỗi đọc ở đây bị nuốt lặng lẽ (trả rỗng) vì chỉ
ảnh hưởng một dòng log, không phải luồng chính.

---

## C. Sự cố khi chạy thật (không phải bug code)

### C1. Mạng chập chờn giữa lúc test — retry/backoff hoạt động đúng như thiết kế

Trong lúc chạy thật (test kill-giữa-chừng), gặp lỗi kết nối thật tới
`speech.platform.bing.com` (`Cannot connect to host ... [The specified
network name is no longer available]`, `Connection timeout to host wss://...`)
— không phải throttle 403. Một số segment mất 30–90s do phải chờ đủ
`max_attempts` lần + backoff 2s/5s trước khi thành công hoặc bị đánh dấu
`failed`. Hệ thống tự phục hồi đúng thiết kế: các segment lỗi được ghi
`failed_ids`, lần chạy `tts` kế tiếp (không `--force`) tự động thử lại
đúng các id đó và thành công khi mạng ổn định trở lại. Không có segment
nào bị bỏ sót hay lặp gọi thừa.

### C2. Fix `tests/test_cli.py`: `TestCliHelp._run` thiếu `encoding="utf-8"`

Bug có sẵn từ trước CP4, không liên quan logic tổng hợp giọng nói: hàm
`_run()` gọi `subprocess.run(..., text=True)` không chỉ định `encoding`,
nên Python decode stdout của tiến trình con theo `locale.getpreferredencoding()`
của máy (`cp1252` trên Windows) trong khi tiến trình con thực sự in UTF-8.
Với 3 subcommand cũ, chuỗi byte không hiểu ngẫu nhiên chưa rơi vào byte
không hợp lệ của cp1252; thêm subcommand `tts` vào `--help` (dài hơn, ký
tự khác) làm lộ `UnicodeDecodeError`. Sửa bằng cách truyền
`encoding="utf-8"` tường minh — tiến trình con luôn in UTF-8 (xem
`app/__main__.py` đã `reconfigure(encoding="utf-8")` khi chạy qua
`python -m app`), test không nên phụ thuộc code page của máy chạy CI.

---

## D. Số liệu đo được

- Episode thật 58 segment (video ~4 phút): lần chạy đầu tiên (mạng ổn
  định) mất **~34s** cho toàn bộ 58 segment (concurrency mặc định 4, mỗi
  segment ~1–2.5s khi mạng bình thường). Ước lượng tập 25 phút (~400
  segment): **~4 phút** cho TTS (rẻ hơn nhiều so với dịch ~14–15 phút ở
  CP3, vì edge-tts không cần nạp model local).
- Chạy lại không đổi gì: SKIP, ~0.18s (chỉ đọc + ghi lại manifest).
- Duration audio hợp lý với độ dài câu: 84 ký tự → 5.208s; 11 ký tự →
  1.872s; 71 ký tự → 5.376s (giọng `vi-VN-HoaiMyNeural`, rate mặc định).
  Đổi `rate: +20%` → cùng câu 84 ký tự còn 4.344s.

## E. Việc chưa làm

- Đo duration thật/ghi vào manifest, `tts_rate`, `normalized.json`: CP5.
- Ghép `voice_track.wav`, mix, render: CP6.
- Provider TTS khác ngoài edge (Piper, Azure...), chọn voice theo
  `target_language`, pitch: ngoài phạm vi hiện tại.
- Chưa thử `concurrency` cao hơn 4 để xem Microsoft có throttle 403 hay
  không — lần chạy thật chỉ gặp lỗi kết nối tạm thời, không phải 403.

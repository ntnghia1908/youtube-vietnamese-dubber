# CP4 — Edge TTS

## Mục tiêu
Sinh giọng tiếng Việt cho từng segment của `translated.json` bằng edge-tts,
mỗi segment một file `tts/000001.mp3`… Resume/cache theo
`hash(provider + voice + rate + volume + text)` (plan §13): sửa một câu dịch
thì chỉ tổng hợp lại đúng câu đó; chạy lại khi đã đủ thì không gọi mạng.

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|
| `app/tts/base.py` | `TTSError`, `TTSEngine` (ABC), `cache_key()` |
| `app/tts/edge.py` | `EdgeTTSEngine` — gọi `edge_tts.Communicate(...).save()` |
| `app/tts/__init__.py` | `create_tts_engine(config: TTSConfig) -> TTSEngine` (giống `app/translation/__init__.py`) |
| `app/tts/synthesize.py` | Stage: `synthesize_translation(...)` — đọc `translated.json`, resume, retry, song song, ghi manifest |
| `app/config.py` | Thêm `TTSConfig` + section `tts` (contract CP3 A4: không thêm thì mọi lệnh lỗi `Section không hợp lệ: tts`) |
| `app/cli.py` | Subcommand `tts` + cập nhật docstring đầu file |
| `config.example.yaml` | Section `tts:` có comment |
| `pyproject.toml` | Thêm `"edge-tts>=7.0"`; cài vào `.venv` (`.venv/Scripts/python.exe -m pip install -e .`) |
| `tests/test_tts.py`, `tests/test_config.py`, `tests/test_cli.py` | Xem mục Test |
| `docs/decisions/checkpoint-4.md` | Quyết định + mục A contract cho CP5/CP6 |

Không đặt ở `models/`, không tạo `app/pipeline/*` ở CP4.

## Interface

```python
# app/tts/base.py
class TTSError(RuntimeError): ...

class TTSEngine(ABC):
    provider: str                      # "edge"
    def __init__(self, voice: str, rate: str, volume: str) -> None
    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> None:
        """Ghi audio ra output_path. Raise TTSError nếu lỗi (kể cả không nhận được audio)."""
    def cache_key(self, text: str) -> str:
        # sha256 hex của "\n".join([provider, voice, rate, volume, text])
```

```python
# app/tts/edge.py
class EdgeTTSEngine(TTSEngine):
    provider = "edge"
    def __init__(self, voice: str, rate: str, volume: str, *, timeout_seconds: float) -> None
    def synthesize(self, text: str, output_path: Path) -> None:
        # import edge_tts CỤC BỘ (lệnh khác không cần cài edge-tts)
        # asyncio.run(edge_tts.Communicate(text, voice, rate=rate, volume=volume,
        #                                  receive_timeout=int(timeout_seconds)).save(str(output_path)))
        # Mọi exception của edge_tts/aiohttp/asyncio.TimeoutError -> bọc thành TTSError(str(exc))
```
Kiểm tra chữ ký `Communicate` thật trong bản edge-tts đã cài trước khi dùng
`receive_timeout`; khác thì tự điều chỉnh và ghi vào decisions.

```python
# app/tts/synthesize.py
TTS_DIRNAME = "tts"
MANIFEST_FILENAME = "manifest.json"          # -> tts/manifest.json
def segment_filename(segment_id: int) -> str  # 1 -> "000001.mp3"

@dataclass(frozen=True)
class TTSResult:
    manifest_path: Path
    synthesized_ids: list[int]   # gọi TTS lần này
    cached_ids: list[int]        # dùng lại file cũ
    empty_ids: list[int]         # bỏ qua vì text rỗng
    failed_ids: list[int]
    skipped: bool                # True khi không phải gọi TTS segment nào và không còn lỗi

def synthesize_translation(
    translated_path: Path,
    tts_dir: Path,
    engine: TTSEngine,
    *,
    max_attempts: int = 3,
    concurrency: int = 4,
    force: bool = False,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,   # test truyền no-op
) -> TTSResult
```

Tái sử dụng:
- `read_translated(path) -> (source_lang, target_lang, list[TranslatedSegment])`
  ở `app/translation/translate.py` — raise `TranslationError` nếu file hỏng →
  bắt lại và raise `TTSError` kèm gợi ý chạy `translate`.
- `TranslatedSegment(id, start, end, source_text, translated_text)` cùng file.
- Helper ghi JSON atomic: copy mẫu `_write_json_atomic` ở `app/translation/translate.py:78`
  (hàm private — copy, không import).
- CLI: theo mẫu `_cmd_translate` ở `app/cli.py:200` (override config bằng `dataclasses.replace`, `log` kèm `flush=True`).

## Artifact
- Vào: `<episode>/translated.json` (contract CP3 A1/A2):
```json
{"source_language": "en", "target_language": "vi",
 "translator": {"provider": "ollama", "model": "qwen3:8b"},
 "transcript_sha256": "cd5d…", "failed_ids": [17],
 "segments": [
   {"id": 1, "start": 0.0, "end": 6.0, "source_text": "Welcome…", "translated_text": "Chào mừng…"},
   {"id": 17, "start": 80.0, "end": 83.5, "source_text": "…", "translated_text": ""}]}
```
- Ra: `<episode>/tts/000001.mp3`… (tên theo `id`, không theo thứ tự trong list)
  và `<episode>/tts/manifest.json`:
```json
{
  "provider": "edge", "voice": "vi-VN-HoaiMyNeural", "rate": "+0%", "volume": "+0%",
  "segments": [
    {"id": 1, "status": "ok", "file": "000001.mp3", "cache_key": "9f2c…", "text": "Chào mừng…"},
    {"id": 17, "status": "empty", "file": null, "cache_key": null, "text": ""},
    {"id": 23, "status": "failed", "file": null, "cache_key": null, "text": "…", "error": "NoAudioReceived: …"}
  ]
}
```
  - `segments` đúng thứ tự và đủ id như `translated.json`.
  - `file` là tên tương đối trong `tts/`. Stage sau (CP5/CP6) **đọc manifest,
    chỉ dùng entry `status == "ok"`** — không glob `*.mp3`.

## Config
`app/config.py`: `TTSConfig` (frozen dataclass) + `_TTS_TYPES`, thêm `"tts"` vào `top_level`:

```yaml
tts:
  provider: edge               # hiện chỉ có edge
  voice: vi-VN-HoaiMyNeural    # xem `edge-tts --list-voices`
  rate: "+0%"                  # tốc độ đọc, dạng +N% / -N%
  volume: "+0%"
  concurrency: 4               # số segment tổng hợp song song
  max_attempts: 3              # số lần thử mỗi segment
  timeout_seconds: 60
```
- Mặc định trong code đúng như trên (voice mặc định theo plan §10).
- Validate: `provider in ("edge",)`; `rate`/`volume` khớp `^[+-]\d{1,3}%$`
  (lỗi thường gặp: YAML `rate: +0%` không quote vẫn là str, nhưng `rate: 0%`
  thiếu dấu → báo lỗi gợi ý `"+0%"`); `concurrency`, `max_attempts`,
  `timeout_seconds` > 0 (dùng `_positive`).
- CLI `python -m app tts EPISODE_DIR [--voice V] [--rate R] [--volume V] [--force] [--config PATH]`.
  Flag mặc định `None`; flag rate/volume sai định dạng → exit 1 với thông báo
  rõ (validate bằng cùng regex, đặt hàm dùng chung trong `config.py`).
  `--rate` nhận giá trị bắt đầu bằng `-` → hướng dẫn dùng `--rate=-10%` trong help.

## Hành vi bắt buộc
1. **Thiếu `translated.json`** → `TTSError("… chạy `translate` trước")`, exit 1.
2. **Text cần đọc** = `translated_text.strip()`. Rỗng, hoặc không có ký tự
   chữ/số nào (`not any(c.isalnum() for c in text)`, vd `"..."` — edge-tts
   trả NoAudioReceived) → `status: "empty"`, không gọi TTS. Gồm cả segment
   nằm trong `failed_ids` của translate (CP3 A1: text rỗng). Log một dòng
   tổng: số segment rỗng và số trong đó là do dịch lỗi
   (`id in failed_ids` của translated.json) để user biết chạy lại `translate`.
3. **Cache/resume từng segment**: dùng lại (cached) khi manifest cũ có entry
   cùng id, `status == "ok"`, `cache_key == engine.cache_key(text)`, và file
   tồn tại với size > 0. Ngược lại tổng hợp lại. Hệ quả mong muốn: sửa text
   một câu / translate chạy lại do transcript đổi → chỉ câu đổi bị gọi lại;
   đổi voice/rate/volume → gọi lại tất cả.
4. **Ghi file atomic**: engine ghi vào `000001.mp3.tmp`, stage kiểm tra size
   > 0 rồi `os.replace` sang `000001.mp3`. Size 0 → coi như lỗi, retry. (File
   cụt sau khi bị kill không được phép bị coi là cache hợp lệ.) Đầu stage xoá
   mọi `*.tmp` sót lại trong `tts/`.
5. **Manifest ghi atomic sau mỗi segment xong** (ok hoặc failed), ghi từ
   thread chính (dùng `ThreadPoolExecutor(concurrency)` + `as_completed`;
   worker chỉ gọi engine và trả kết quả). Kill giữa chừng → chạy lại chỉ làm
   phần còn thiếu. Trong lúc chạy, manifest chỉ chứa segment đã có kết quả
   (kể cả entry cached/empty); lần ghi cuối chứa đủ id, đúng thứ tự.
6. **Retry**: tối đa `max_attempts` lần mỗi segment, chờ `2s`, `5s` (rồi 5s
   cho các lần sau) giữa các lần (plan §24), qua tham số `sleep`. Hết lượt →
   `status: "failed"` kèm `error`, **không dừng stage** (giống C3 của CP3).
7. **Fail fast**: tổng hợp segment không rỗng *đầu tiên cần gọi TTS* một
   mình trước (tuần tự); nếu nó lỗi hết lượt → raise `TTSError` ngay kèm
   gợi ý kiểm tra mạng / tên voice. Tránh 400 segment × 3 lần thử khi voice
   gõ sai hoặc mất mạng. Sau đó mới chạy song song phần còn lại. Nếu kết
   thúc mà **mọi** segment cần đọc đều failed → raise.
8. **`--force`**: bỏ qua manifest cũ, tổng hợp lại tất cả (vẫn ghi đè từng
   file atomic, không xoá cả thư mục trước — kill giữa chừng khi force thì
   lần sau không force vẫn resume được nhờ manifest mới ghi dần).
9. **Dọn file mồ côi** sau khi xong: xoá `NNNNNN.mp3` trong `tts/` không
   thuộc entry `ok` nào (id biến mất, hoặc câu nay thành rỗng). Chỉ xoá file
   khớp `^\d{6}\.mp3$`, không đụng file khác.
10. **SKIP**: nếu không có segment nào cần gọi TTS và không có failed →
    `skipped=True`, CLI in `[tts] SKIP: tts/ đã đủ (dùng --force để tạo lại).`
    Vẫn ghi lại manifest (rẻ) để phản ánh đúng translated.json hiện tại.
11. **Exit code**: 0 kể cả có segment failed (in `CẢNH BÁO: N segment lỗi (id …) — chạy lại lệnh để thử lại.`), 1 khi `TTSError`/`ConfigError`.
12. Log tiến trình mỗi segment: `[tts] 12/58 id=12 ok (1.4s)` / `cached` / `failed: …`
    — với cached chỉ in một dòng tổng, không in 400 dòng.
13. Không kiểm tra `target_language` khớp voice; chỉ in voice đang dùng ở đầu log.

## Test (unittest, mock tiến trình/dịch vụ ngoài)
`tests/test_tts.py` — dùng `FakeEngine(TTSEngine)` ghi bytes giả, đếm lời gọi,
có thể cấu hình lỗi theo text/số lần; `tempfile.TemporaryDirectory`; `sleep` no-op; `concurrency=1` trừ case song song.
- sinh đủ file cho mọi segment có chữ; tên theo id (`000001.mp3`, id không liên tiếp vẫn đúng); manifest đúng thứ tự, đủ id.
- segment `translated_text` rỗng / chỉ dấu câu → `empty`, engine không được gọi; id trong `failed_ids` của translated.json đếm đúng.
- chạy lần 2 → engine 0 lời gọi, `skipped=True`.
- sửa `translated_text` một segment → chỉ segment đó gọi lại.
- đổi rate (engine khác rate) → gọi lại tất cả.
- file mp3 bị xoá tay / size 0 → gọi lại riêng file đó.
- `force=True` → gọi lại tất cả.
- engine lỗi 2 lần rồi ok → ok, `sleep` được gọi với 2.0, 5.0.
- một segment (không phải đầu tiên) lỗi hết lượt → `failed`, stage tiếp tục, các segment khác ok; chạy lại → chỉ segment đó được gọi.
- segment đầu tiên lỗi hết lượt → raise `TTSError`, các segment khác không được gọi.
- engine ghi file 0 byte → retry, cuối cùng failed nếu vẫn 0 byte; không để lại `.mp3` hay `.tmp`.
- `.tmp` sót lại từ trước bị xoá; file mồ côi `000099.mp3` bị xoá, `notes.txt` giữ nguyên.
- thiếu translated.json / JSON hỏng → `TTSError`.
- `concurrency=4` với 10 segment → đủ 10 file, manifest đúng thứ tự.
- `cache_key` đổi khi đổi bất kỳ trong provider/voice/rate/volume/text.
- `EdgeTTSEngine`: patch `sys.modules["edge_tts"]` bằng mock có `Communicate` (method `save` là coroutine) → kiểm tra truyền đúng voice/rate/volume và path; `Communicate(...).save` raise → `TTSError`.

`tests/test_config.py`: section `tts` hợp lệ; mặc định; key lạ bị từ chối; `rate: "0%"`/`"fast"` lỗi; `concurrency: 0` lỗi; `provider: azure` lỗi.

`tests/test_cli.py`: `tts` gọi stage với config đúng và flag ghi đè (patch `synthesize_translation` + `create_tts_engine`); `--rate=bad` → exit 1; failed_ids khác rỗng → exit 0 và in CẢNH BÁO.

## Chạy thật (BẮT BUỘC)
Episode: `output/zGuIUytF_6U__Guess How Much I Love You Read Aloud _ Kids Books Read Aloud`
(đã có `translated.json`, 58 segment, `failed_ids: []`). Gọi `EP` cho gọn.

1. `.venv/Scripts/python.exe -m app tts "$EP"` → exit 0.
   - Mở `tts/manifest.json`: 58 entry, đúng thứ tự id; số `ok` + `empty` = 58; không `failed`.
   - Số file `*.mp3` trong `tts/` = số entry `ok`; không còn `.tmp`.
   - `ffprobe` ít nhất 3 file (đầu, giữa, cuối): `codec_name=mp3`, duration > 0.3s,
     và hợp lý so với độ dài câu (câu dài ~ vài giây, không phải 0.1s hay 60s).
     Ghi bảng id / số ký tự / duration vào báo cáo.
   - Ghép thử 3 file đầu bằng ffmpeg thành `$SCRATCH/sample.mp3` (ngoài repo) — xác nhận ffmpeg đọc được, không lỗi decode.
   - Ghi tổng thời gian chạy (để ước lượng cho playlist 26 tập).
2. Chạy lại y hệt → in `SKIP`, thời gian < vài giây, mtime các mp3 không đổi.
3. Copy **chỉ** `translated.json` sang `output/_cp4_demo/` (xoá sau khi xong), chạy `tts` một lần, rồi:
   - sửa tay `translated_text` của id 2 → chạy lại → log chỉ gọi TTS cho id 2;
   - đặt `translated_text` của id 3 thành `""` → chạy lại → id 3 `empty`, `000003.mp3` bị xoá;
   - `--rate=+20%` → gọi lại tất cả, duration file id 1 ngắn hơn lần trước;
   - `--voice vi-VN-KhongCoGiong` → raise sớm (fail fast), exit 1, thông báo gợi ý kiểm tra voice, và **chỉ 1 segment** bị thử.
4. Kill giữa chừng (Ctrl+C / `Stop-Process`) một lần `--force` trên `_cp4_demo` rồi chạy lại không `--force` → chỉ tổng hợp phần còn lại, manifest cuối đủ 58.

## Ngoài phạm vi
- Đo/co giãn duration, `normalized.json`, `tts_rate` từng segment (CP5).
- Ghép `voice_track.wav`, mix, render (CP6); lệnh `dub`/`playlist` (CP7/8).
- Provider TTS khác (Piper, Azure…), chọn voice theo `target_language`, pitch.
- Dời `Segment` sang `models/`.

## Điểm phải escalate
- edge-tts không cài được trên Python của `.venv` (3.14) hoặc API `Communicate` khác đáng kể so với spec.
- Microsoft trả 403/throttle khi `concurrency: 4` → không tự hạ mặc định, báo số liệu (bao nhiêu lỗi ở concurrency nào).
- Cần đổi schema `translated.json` hay contract CP3 để làm CP4.
- Nếu thấy CP5 cần thêm field vào manifest (vd duration) — ghi đề xuất vào decisions `[CẦN DUYỆT]`, không tự thêm ffprobe vào stage TTS.

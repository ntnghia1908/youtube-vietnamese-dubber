# CP5 — Timing normalization

## Mục tiêu
Đo độ dài thật của từng `tts/*.mp3`, so với slot gốc (`end - start`) và
tăng tốc nhẹ bằng ffmpeg `atempo` những câu hơi dài, để tiếng Việt không
đè sang câu sau. Câu quá dài thì đánh dấu `too_long`. Xuất `normalized.json`
(contract cho CP6) và in report normal/stretched/too_long (plan §12, CP5 ở
dòng 1010).

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|
| `app/synchronization/timing.py` | Stage mới (xem Interface). Đặt ở package `app/synchronization/` đã có sẵn — **không** tạo `alignment/` như plan ghi |
| `app/synchronization/__init__.py` | Sửa docstring (bỏ "Chưa implement") |
| `app/config.py` | `TimingConfig` + section `timing` (thiếu thì mọi lệnh lỗi `Section không hợp lệ`) |
| `app/cli.py` | Subcommand `normalize` + cập nhật docstring đầu file |
| `config.example.yaml` | Section `timing:` có comment |
| `tests/test_timing.py` (mới), `tests/test_config.py`, `tests/test_cli.py` | Xem mục Test |
| `docs/decisions/checkpoint-5.md` | Quyết định + mục A contract cho CP6 |

Không sửa `app/tts/*` (không thêm `duration` vào `tts/manifest.json` — xem
"Quyết định đã chốt").

## Quyết định đã chốt (đọc trước khi code)
1. **[A2 của CP4] CP5 tự ffprobe**, không bắt CP4 ghi `duration`. Chi phí
   thấp (~58 file mất vài giây) và được cache theo segment trong chính
   `normalized.json` (key = `tts_cache_key`), nên chạy lại chỉ probe câu
   mới đổi.
2. **Co giãn bằng ffmpeg `atempo` cục bộ**, không gọi lại edge-tts với
   `rate` khác: không tốn mạng, tempo tính chính xác, resume đơn giản. Vì
   vậy `normalized.json` có `tempo` (float), **không** có `tts_rate` như ví
   dụ ở plan §8; plan §8 `duration` đổi tên thành `slot` cho khỏi nhầm với
   độ dài audio.
3. **`too_long` vẫn được tăng tốc tối đa** (`tempo = max_tempo`) để giảm
   đè, và ghi `overflow` (giây tràn ra ngoài slot). Rút gọn câu bằng LLM
   rồi TTS lại (plan §12 Case 3) là ngoài phạm vi.
4. **Slot = `end - start`**, không mượn khoảng lặng tới segment sau: đo trên
   episode thật, segment Whisper nằm liền nhau nên mượn khoảng lặng không
   đổi kết quả (48/6/4 cả hai cách).

## Interface

```python
# app/synchronization/timing.py
NORMALIZED_FILENAME = "normalized.json"
TIMING_DIRNAME = "timing"          # chứa file đã co giãn: timing/000007.wav

class TimingError(RuntimeError): ...

@dataclass(frozen=True)
class TimingResult:
    normalized_path: Path
    normal_ids: list[int] = field(default_factory=list)
    stretched_ids: list[int] = field(default_factory=list)
    too_long_ids: list[int] = field(default_factory=list)
    silent_ids: list[int] = field(default_factory=list)    # tts status "empty"
    missing_ids: list[int] = field(default_factory=list)   # tts failed / không có entry / file mất / ffprobe lỗi
    skipped: bool = False

def probe_duration(path: Path) -> float:
    """ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 <path>.
    Raise TimingError nếu không có ffprobe, exit != 0, hoặc output không phải số."""

def stretch_audio(src: Path, dst: Path, tempo: float) -> None:
    """ffmpeg -y -i src -filter:a atempo=<tempo:.4f> -ac 1 -c:a pcm_s16le <dst.tmp.wav>,
    rồi os.replace sang dst. Giữ sample rate gốc (không -ar). Raise TimingError nếu lỗi."""

def classify(tts_duration: float, slot: float, *, normal_max_ratio: float,
             max_tempo: float) -> tuple[str, float | None, float]:
    """Trả (status, ratio, tempo). Hàm thuần, không I/O — test trực tiếp.
    slot <= 0            -> ("too_long", None, max_tempo)
    ratio <= normal_max_ratio -> ("normal", ratio, 1.0)
    ratio <= max_tempo   -> ("stretched", ratio, ratio)   # vừa khít slot
    còn lại              -> ("too_long", ratio, max_tempo)"""

def normalize_timing(
    episode_dir: Path, *,
    normal_max_ratio: float = 1.05,
    max_tempo: float = 1.25,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> TimingResult
```

- Tìm ffmpeg/ffprobe bằng `shutil.which` như `app/audio/ffmpeg.py:39`
  (thông báo lỗi tương tự, nhắc PATH). Chỉ cần ffmpeg khi có ít nhất một
  segment phải co giãn.
- Tái sử dụng: `read_translated()` ở `app/translation/translate.py:123`
  (trả `(src_lang, tgt_lang, list[TranslatedSegment])`, segment có `id,
  start, end, source_text, translated_text`); `TRANSLATED_FILENAME` cùng
  module; `TTS_DIRNAME`, `MANIFEST_FILENAME` ở `app/tts/synthesize.py`.
  Ghi JSON atomic: copy pattern `_write_json_atomic` của
  `app/tts/synthesize.py:59` (hàm private, không import chéo).

## Artifact
- Vào: `<ep>/translated.json` (nguồn timing và thứ tự segment),
  `<ep>/tts/manifest.json` (schema: `docs/decisions/checkpoint-4.md` A1):
  ```json
  {"provider": "edge", "voice": "vi-VN-HoaiMyNeural", "rate": "+0%", "volume": "+0%",
   "segments": [
     {"id": 1, "status": "ok", "file": "000001.mp3", "cache_key": "9f2c…", "text": "…"},
     {"id": 17, "status": "empty", "file": null, "cache_key": null, "text": ""},
     {"id": 23, "status": "failed", "file": null, "cache_key": null, "text": "…", "error": "…"}]}
  ```
  **Chỉ** lấy audio từ entry `status == "ok"`, đường dẫn `tts_dir / entry["file"]`.
  Không glob `tts/*.mp3`.
- Ra: `<ep>/normalized.json` + `<ep>/timing/NNNNNN.wav` (chỉ cho segment
  có `tempo != 1.0`):
  ```json
  {
    "fingerprint": "sha256…",
    "params": {"normal_max_ratio": 1.05, "max_tempo": 1.25},
    "summary": {"segments": 58, "normal": 48, "stretched": 6, "too_long": 4, "silent": 0, "missing": 0},
    "too_long_ids": [12, 30, 41, 55],
    "missing_ids": [],
    "segments": [
      {"id": 1, "start": 0.0, "end": 6.0, "slot": 6.0,
       "source_text": "…", "translated_text": "…",
       "status": "normal", "tts_file": "tts/000001.mp3", "tts_cache_key": "9f2c…",
       "tts_duration": 5.208, "ratio": 0.868, "tempo": 1.0,
       "audio": "tts/000001.mp3", "audio_duration": 5.208, "overflow": 0.0},
      {"id": 7, "…": "…", "status": "stretched", "tts_duration": 5.4, "slot": 5.0,
       "ratio": 1.08, "tempo": 1.08, "audio": "timing/000007.wav", "audio_duration": 5.003, "overflow": 0.003},
      {"id": 12, "…": "…", "status": "too_long", "ratio": 1.4, "tempo": 1.25,
       "audio": "timing/000012.wav", "audio_duration": 4.48, "overflow": 0.48},
      {"id": 17, "…": "…", "status": "silent", "tts_file": null, "tts_cache_key": null,
       "tts_duration": null, "ratio": null, "tempo": null, "audio": null, "audio_duration": null, "overflow": 0.0},
      {"id": 23, "…": "…", "status": "missing", "…": null, "error": "tts failed: …"}
    ]
  }
  ```
  - `segments` đúng thứ tự/đủ id của `translated.json`. Entry manifest có
    id không nằm trong `translated.json` thì bỏ qua.
  - Mọi path là **tương đối với episode dir, dùng `/`** (`Path.as_posix()`).
  - `audio_duration` là **ffprobe của file cuối cùng** (atempo không chính
    xác tuyệt đối) — không tính bằng `tts_duration / tempo`.
  - `overflow = max(0, audio_duration - slot)`; số thực làm tròn 3 chữ số,
    `ratio`/`tempo` 4 chữ số.
  - `fingerprint` = sha256 của `json.dumps(..., sort_keys=True)` trên
    `{"params": params, "segments": [[id, start, end, tts_status, tts_cache_key], ...]}`
    — không hash bytes của manifest (CP4 ghi lại manifest mỗi lần chạy, B5).

## Config
```yaml
timing:
  normal_max_ratio: 1.05   # tts/slot <= giá trị này: giữ nguyên
  max_tempo: 1.25          # tăng tốc tối đa (atempo); vượt quá -> too_long
```
- `TimingConfig(normal_max_ratio: float = 1.05, max_tempo: float = 1.25)`,
  thêm `timing` vào `AppConfig`. Validate: `1.0 <= normal_max_ratio <
  max_tempo <= 2.0`, kiểu `(int, float)`; sai -> `ConfigError`.
- CLI: `python -m app normalize EPISODE_DIR [--max-tempo X] [--force]`.
  `--max-tempo` ghi đè config, validate cùng luật (lỗi -> in `[normalize]
  LỖI: …`, exit 1). Không thêm flag cho `normal_max_ratio`.

## Hành vi bắt buộc
- Thiếu `translated.json` hoặc `tts/manifest.json` -> `TimingError` với
  gợi ý chạy `translate`/`tts` trước -> CLI exit 1. Manifest JSON hỏng ->
  cũng `TimingError` (không tự tổng hợp lại).
- **Resume**: nếu `normalized.json` tồn tại, `fingerprint` khớp, và mọi
  `audio` không-null đều tồn tại trên đĩa -> SKIP (`skipped=True`), không
  gọi ffprobe/ffmpeg. `--force` bỏ qua cả SKIP lẫn cache dưới đây.
- **Cache theo segment** khi không SKIP (vd chạy lại `tts` đổi vài câu, hoặc
  đổi `--max-tempo`): nếu entry cũ có cùng `tts_cache_key` -> dùng lại
  `tts_duration` (không probe lại); nếu thêm cùng `tempo` và file `audio`
  còn -> dùng lại file + `audio_duration` (không chạy ffmpeg lại).
  `normalized.json` cũ hỏng -> log rồi tính lại từ đầu.
- Phân loại segment không có audio:
  - manifest `status: "empty"` -> `silent` (không phải lỗi, CP6 để im lặng).
  - manifest `failed`, không có entry, file mp3 không tồn tại, hoặc
    ffprobe lỗi trên file đó -> `missing` + `error` mô tả. Không dừng stage.
- `missing_ids` khác rỗng -> CLI in `CẢNH BÁO: N segment thiếu audio (id …)
  — chạy lại \`tts\` rồi \`normalize\``, vẫn **exit 0** (giống C3/A3). Lỗi
  ffmpeg khi co giãn (môi trường) -> `TimingError`, exit 1.
- Atomic: ffmpeg ghi ra `timing/NNNNNN.tmp.wav` (phải có đuôi `.wav` để
  ffmpeg chọn muxer) rồi `os.replace`. Đầu stage xoá `timing/*.tmp.wav`.
  Cuối stage xoá `timing/*.wav` không được `normalized.json` mới tham chiếu
  (file mồ côi khi câu đổi từ stretched thành normal).
- Ghi `normalized.json` **sau cùng** (atomic), sau khi mọi file `timing/`
  đã xong — kill giữa chừng thì lần sau không SKIP nhầm.
- CLI in report:
  ```
  [normalize] segments  : 58
  [normalize] normal    : 48
  [normalize] stretched : 6
  [normalize] too_long  : 4 (id 12, 30, 41, 55)
  [normalize] silent    : 0
  [normalize] missing   : 0
  [normalize] output    : <ep>/normalized.json
  ```
  SKIP thì in `[normalize] SKIP: normalized.json đã khớp (dùng --force để tính lại).`
  rồi vẫn in report (đọc từ `summary`).

## Test (unittest, mock tiến trình/dịch vụ ngoài)
`tests/test_timing.py` — mock `probe_duration`/`stretch_audio` (hoặc
`subprocess.run` + `shutil.which`), dựng episode giả trong `TemporaryDirectory`
với `translated.json` + `tts/manifest.json` + mp3 giả (bytes bất kỳ):
- `classify`: ratio 1.0 / đúng 1.05 -> normal; 1.10 -> stretched, tempo=1.10;
  đúng 1.25 -> stretched; 1.30 -> too_long, tempo=1.25; slot 0 -> too_long, ratio None.
- Episode hỗn hợp (normal, stretched, too_long, empty, failed, id thiếu
  trong manifest, file mp3 bị xoá): đúng status/summary/`too_long_ids`/
  `missing_ids`, path dạng `tts/000001.mp3` và `timing/000002.wav`,
  `stretch_audio` chỉ gọi cho stretched + too_long với đúng tempo.
- Chạy lần 2 không đổi gì -> `skipped=True`, không gọi probe/stretch.
- `--force` -> probe + stretch lại tất cả.
- Đổi `cache_key` của một segment trong manifest -> chỉ probe lại segment đó.
- Đổi `max_tempo` -> không probe lại, chỉ stretch lại segment có tempo đổi.
- File trong `timing/` bị xoá tay -> không SKIP, tạo lại đúng file đó.
- File mồ côi `timing/000099.wav` và `timing/000001.tmp.wav` bị dọn.
- Thiếu manifest -> `TimingError`; ffprobe lỗi 1 file -> `missing` + `error`, không raise.
- `probe_duration`: parse stdout `"5.208000\n"`; exit != 0 -> `TimingError`;
  `shutil.which` None -> `TimingError`.
- `stretch_audio`: lệnh chứa `atempo=1.1000`, ghi qua `.tmp.wav` rồi replace.

`tests/test_config.py`: default `TimingConfig`; đọc section `timing`;
`max_tempo <= normal_max_ratio`, `max_tempo > 2.0`, `normal_max_ratio < 1.0`,
sai kiểu -> `ConfigError`.
`tests/test_cli.py`: `normalize --help` chạy được; `--max-tempo 3` -> exit 1;
thiếu manifest -> exit 1 (patch nếu cần).

## Chạy thật (BẮT BUỘC)
Episode đã có `translated.json` + `tts/` (58 segment):
```bash
EP="output/zGuIUytF_6U__Guess How Much I Love You Read Aloud _ Kids Books Read Aloud"
.venv/Scripts/python.exe -m app normalize "$EP"            # lần 1
.venv/Scripts/python.exe -m app normalize "$EP"            # lần 2 -> SKIP, < 1s
.venv/Scripts/python.exe -m app normalize "$EP" --max-tempo 1.4   # tính lại, không probe lại
.venv/Scripts/python.exe -m app normalize "$EP"            # quay về 1.25
.venv/Scripts/python.exe -m app normalize "$EP" --force
```
Tiêu chí đạt (mở artifact, không chỉ xem exit code):
- Report lần 1 xấp xỉ **normal 48 / stretched 6 / too_long 4 / missing 0**
  (Opus đã đo trước bằng ffprobe với ngưỡng mặc định). Lệch nhiều -> escalate.
- Mở `normalized.json`: đủ 58 segment đúng thứ tự, `tts_duration` khớp
  ffprobe chạy tay trên 2–3 file.
- Với **mọi** segment stretched: ffprobe `timing/*.wav` -> `audio_duration`
  trong khoảng `slot ± 0.05s`; `ffprobe -show_streams` thấy 1 stream audio
  mono `pcm_s16le`, duration > 0 (không phải file câm/rỗng).
- Too_long: `audio_duration ≈ tts_duration / 1.25`, `overflow > 0`.
- Sau `--max-tempo 1.4`: vài too_long chuyển thành stretched, số file trong
  `timing/` khớp số segment có `tempo != 1.0`; sau khi quay về 1.25 không
  còn file mồ côi.
- Ghi số liệu (thời gian lần 1, lần SKIP) vào mục D của decisions.

## Ngoài phạm vi
- Rút gọn câu `too_long` bằng LLM rồi TTS lại (plan §12 Case 3) — CP9.
- Cắt khoảng lặng đầu/cuối của mp3 edge-tts; mượn khoảng lặng tới segment sau.
- Ghép `voice_track.wav`, mix, render — CP6. Không tạo `app/pipeline/*`.
- Sửa CP4 (`tts/manifest.json`) để ghi `duration`.

## Điểm phải escalate
- Số normal/stretched/too_long thực tế lệch xa 48/6/4.
- `atempo` làm giọng méo/nghe tệ rõ ở tempo 1.25 (nếu kiểm tra được), hoặc
  `audio_duration` của file co giãn lệch slot > 0.1s.
- Muốn đổi schema `normalized.json` hoặc cách đặt path (`audio`) so với spec
  — CP6 sẽ đọc đúng schema này.
- `read_translated()` hoặc schema manifest thực tế khác mô tả ở trên.

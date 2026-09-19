# CP6 — Build voice track + render

## Mục tiêu
Đặt audio từng segment (`normalized.json`) vào `voice_track.wav` đúng
timestamp, mix với audio gốc (hạ volume), giữ nguyên video stream
(`-c:v copy`), xuất `output_vi.mp4` (plan §14–15, CP6 ở dòng 1046).

## Quyết định đã chốt (đọc trước khi code)
1. **Một module `app/audio/render.py`** (dựng track + mux + orchestrator),
   theo cách CP5 gom vào `timing.py`. Package `app/audio/` đã có sẵn.
2. **Dựng `voice_track.wav` bằng Python stdlib** (`wave` + `array`), mỗi
   segment giải mã qua `ffmpeg ... pipe:1` ra PCM s16le mono. **Không** dùng
   một lệnh `adelay+amix` 58–400 input (giới hạn độ dài dòng lệnh Windows,
   khó debug, overlap không kiểm soát được). **Không** dùng `audioop` (đã bị
   gỡ khỏi Python 3.13+, repo chạy 3.14) và không thêm numpy.
3. **`too_long` còn `overflow > 0` → DỜI câu sau, có chặn trần** (không đè
   ngay). Đè hai giọng vào nhau khó nghe hơn nhiều so với lệch tối đa vài
   trăm ms; drift tự hồi phục vì câu `normal` ngắn hơn slot của nó (~13%
   khoảng dư). Trần `mixing.max_shift_seconds` (mặc định 1.0) chặn lệch tích
   luỹ; chạm trần thì mới đè. `max_shift_seconds: 0` = đè hoàn toàn (đặt
   đúng `start`), một núm chỉnh cho cả hai cách.
4. **`missing` → mặc định BÁO LỖI** (exit 1), `--allow-missing` mới chèn
   im lặng và đi tiếp. Khác CP3–5 (exit 0 kèm cảnh báo) vì đây là sản phẩm
   cuối: một bản thuyết minh lặng lẽ thiếu câu là lỗi không được lọt ra
   ngoài. `silent` (CP4 dịch rỗng) không phải lỗi, luôn là im lặng.
5. **Mix một lần ffmpeg**: `source.mp4` + `voice_track.wav` → `output_vi.mp4`,
   **không** ghi `mixed_audio.wav` trung gian (plan §layout có liệt kê nhưng
   `voice_track.wav` đã đủ để debug; đỡ 1 lần encode và file lớn).
6. **Không ducking động** (sidechain): hạ volume audio gốc cố định
   (`mixing.original_volume`, plan §15: 25–35%). Ducking là cải tiến sau.
7. Định dạng track: **mono s16 24000 Hz** (đúng sample rate gốc của edge-tts,
   không phải resample). Hằng nội bộ `VOICE_SAMPLE_RATE_HZ = 24000`, không
   thành config.

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|
| `app/audio/render.py` | Module mới (xem Interface) |
| `app/audio/__init__.py` | Sửa docstring: bỏ "Chưa implement", nêu `ffmpeg.py` (CP2) + `render.py` (CP6) |
| `app/config.py` | `MixingConfig`, `validate_mixing()`, section `mixing`, field `AppConfig.mixing`, thêm `"mixing"` vào `top_level` trong `parse_config` |
| `app/cli.py` | Subcommand `render` + `_cmd_render` + đăng ký vào `_COMMANDS` + cập nhật docstring đầu file |
| `config.example.yaml` | Section `mixing:` có comment |
| `tests/test_render.py` (mới), `tests/test_config.py`, `tests/test_cli.py` | Xem mục Test |
| `docs/decisions/checkpoint-6.md` | Quyết định + mục A contract cho CP7 (mẫu `checkpoint-5.md`) + mục số liệu đo được |

Không sửa `app/synchronization/*`, `app/tts/*`, `app/translation/*`.

## Interface

```python
# app/audio/render.py
VOICE_TRACK_FILENAME = "voice_track.wav"
OUTPUT_FILENAME = "output_vi.mp4"
RENDER_FILENAME = "render.json"          # sidecar: fingerprint + report, để resume
VOICE_SAMPLE_RATE_HZ = 24000
_AUDIO_BITRATE = "192k"                  # aac cho output_vi.mp4

class RenderError(RuntimeError): ...

@dataclass(frozen=True)
class Placement:
    id: int
    audio: str               # đường dẫn tương đối episode dir (dấu /), lấy từ normalized["audio"]
    start: float             # start gốc của segment
    placed_at: float         # thời điểm thực sự đặt vào track
    audio_duration: float
    shift: float             # placed_at - start, luôn >= 0
    overlap: float           # giây đè lên audio câu trước (> 0 chỉ khi chạm max_shift)

@dataclass(frozen=True)
class RenderResult:
    voice_track_path: Path
    output_path: Path
    render_path: Path
    placed_ids: list[int]
    silent_ids: list[int]
    missing_ids: list[int]   # khác rỗng chỉ khi allow_missing=True
    shifted_ids: list[int]   # shift > 0.001
    overlap_ids: list[int]   # overlap > 0.001
    max_shift_seen: float
    duration: float          # giây, độ dài source.mp4
    voice_track_skipped: bool
    output_skipped: bool

def plan_placements(segments: list[dict[str, Any]], *, max_shift: float) -> list[Placement]:
    """Hàm thuần. Chỉ lấy segment có audio != None, sắp theo (start, id).
    cursor = 0.0
    với mỗi segment:
        placed_at = min(max(start, cursor), start + max_shift)   # dời, chặn trần
        overlap   = max(0.0, cursor - placed_at)
        cursor    = max(cursor, placed_at + audio_duration)
    Dùng audio_duration (ffprobe, từ normalized.json), KHÔNG dùng tts_duration/tempo/overflow."""

def decode_pcm(path: Path, sample_rate: int) -> bytes:
    """ffmpeg -nostdin -v error -i <path> -f s16le -acodec pcm_s16le -ac 1 -ar <sr> pipe:1
    (subprocess.run capture_output=True, KHÔNG text=True — stdout là bytes).
    RenderError nếu không có ffmpeg (shutil.which), exit != 0, hoặc stdout rỗng.
    Nếu len lẻ thì cắt bỏ 1 byte cuối."""

def build_voice_track(
    episode_dir: Path, placements: list[Placement], dst: Path, *,
    total_seconds: float, sample_rate: int, log: Callable[[str], None] = print,
) -> None:
    """Ghi dst (WAV mono s16, sample_rate, đúng ceil(total_seconds*sample_rate) frame).
    Ghi ra dst.with_name(dst.stem + ".tmp.wav") rồi os.replace."""

def mix_video(
    source: Path, voice_track: Path, dst: Path, *,
    original_volume: float, speech_volume: float,
) -> None:
    """Mux bằng một lệnh ffmpeg (xem 'Lệnh mux'). Ghi ra dst.with_name(dst.stem + ".tmp.mp4")
    rồi os.replace; lỗi thì xoá tmp và raise RenderError (kèm 2000 ký tự cuối của stderr)."""

def render_episode(
    episode_dir: Path, *,
    original_volume: float = 0.30, speech_volume: float = 1.0,
    max_shift: float = 1.0, allow_missing: bool = False,
    force: bool = False, log: Callable[[str], None] = print,
) -> RenderResult
```

- Tái sử dụng: `probe_duration`, `TimingError`, `NORMALIZED_FILENAME` ở
  `app/synchronization/timing.py` (bắt `TimingError` rồi raise lại
  `RenderError`); `SOURCE_FILENAME` ở `app/youtube/download.py`. Ghi JSON
  atomic: copy pattern `_write_json_atomic` của `app/synchronization/timing.py:57`
  (hàm private, không import chéo).
- **Thuật toán `build_voice_track`** (`track = bytearray(total_samples*2)`,
  toàn số 0 = im lặng; `written_end = 0` tính bằng sample):
  ```
  với mỗi placement (placed_at tăng dần):
      pcm = decode_pcm(episode_dir / p.audio, sample_rate); n = len(pcm)//2
      off = round(p.placed_at * sample_rate)
      n = min(n, total_samples - off)            # vượt track thì cắt, không raise
      ov = max(0, min(off + n, written_end) - off)   # số sample đè lên vùng đã có audio
      ov sample đầu: cộng từng sample bằng array('h') và kẹp [-32768, 32767]
      phần còn lại: gán slice track[(off+ov)*2 : (off+n)*2] = pcm[ov*2 : n*2]
      written_end = max(written_end, off + n)
  ```
  Vòng lặp từng sample **chỉ** chạy trên vùng đè (ngắn); phần còn lại phải
  là slice-assign (không lặp từng sample cả track). Dùng số sample thật của
  pcm để tính `written_end`, không dùng `audio_duration`.
- **Lệnh mux** (`mix_video`), `ffmpeg = shutil.which("ffmpeg")`:
  ```
  ffmpeg -y -nostdin -v error -i <source> -i <voice_track>
    -filter_complex "[0:a]aformat=channel_layouts=stereo,volume={ov:.4f}[bg];
                     [1:a]pan=stereo|c0=c0|c1=c0,volume={sv:.4f}[fg];
                     [bg][fg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]"
    -map 0:v:0 -map [aout] -c:v copy -c:a aac -b:a 192k -movflags +faststart <dst.tmp.mp4>
  ```
  (viết filter trên **một** chuỗi, không xuống dòng.) Đã thử tay trên
  `source.mp4` thật với ffmpeg 7.1.1: chạy được, ra h264 copy + aac
  44100 Hz stereo. Ý nghĩa: `pan` nhân đôi mono ra hai kênh **không** bị
  giảm 3 dB như upmix mặc định; `aformat` ép audio gốc về stereo để `amix`
  không phải đoán layout; `normalize=0` để `amix` không tự chia đôi mức mỗi
  input; `alimiter` chống clip khi cộng hai track; `duration=first` = kết
  thúc theo audio gốc (voice track dài hơn video thì bị cắt).

## Artifact
- Vào:
  - `<ep>/normalized.json` (schema: `docs/decisions/checkpoint-5.md` mục A1). CP6
    chỉ dùng các field của mỗi segment: `id, start, status, audio,
    audio_duration, tts_cache_key, tempo`. Đường dẫn `audio` tương đối
    episode dir, dùng `/` (`tts/000001.mp3` hoặc `timing/000008.wav`) →
    `episode_dir / audio`. **Không** dùng `tts_file`, `overflow`, `fingerprint`.
  - `<ep>/source.mp4` (video + audio gốc).
- Ra:
  - `<ep>/voice_track.wav` — mono, s16, 24000 Hz, dài
    `max(độ dài source.mp4, thời điểm kết thúc audio cuối)`.
  - `<ep>/output_vi.mp4` — video stream copy nguyên, audio aac stereo mix.
  - `<ep>/render.json` (ghi atomic):
    ```json
    {
      "voice_track": {
        "fingerprint": "sha256…",
        "sample_rate": 24000,
        "duration": 243.554,
        "params": {"max_shift_seconds": 1.0},
        "summary": {"placed": 58, "silent": 0, "missing": 0,
                    "shifted": 5, "overlap": 0, "max_shift_seen": 0.51},
        "placements": [
          {"id": 1, "start": 0.0, "placed_at": 0.0, "audio_duration": 5.208, "shift": 0.0, "overlap": 0.0},
          {"id": 9, "start": 34.0, "placed_at": 34.51, "audio_duration": 2.983, "shift": 0.51, "overlap": 0.0}
        ]
      },
      "output": {
        "fingerprint": "sha256…",
        "params": {"original_volume": 0.3, "speech_volume": 1.0},
        "duration": 243.554
      }
    }
    ```
    Số thực làm tròn 3 chữ số. `placements` có một entry cho **mỗi** segment
    có audio, đúng thứ tự.
  - Fingerprint (sha256 của `json.dumps(..., sort_keys=True, ensure_ascii=False)`):
    - `voice_track.fingerprint` = `{"v": 1, "sample_rate": VOICE_SAMPLE_RATE_HZ,
      "max_shift": max_shift, "source_duration": round(d, 3), "rows": [[id, start, audio,
      audio_duration, tts_cache_key, tempo], ...]}` — rows chỉ gồm segment có `audio`.
    - `output.fingerprint` = `{"v": 1, "voice": <voice fingerprint>,
      "original_volume": ov, "speech_volume": sv, "source_size": st_size,
      "source_mtime_ns": st_mtime_ns}` (của `source.mp4`).

## Config
```yaml
mixing:
  original_volume: 0.30    # volume audio gốc (0.0–1.0); 0 = tắt hẳn audio gốc
  speech_volume: 1.00      # volume giọng tiếng Việt (>0, <= 2.0)
  max_shift_seconds: 1.0   # dời tối đa một câu khi câu trước tràn slot; 0 = không dời (đè)
```
- `MixingConfig(original_volume: float = 0.30, speech_volume: float = 1.0,
  max_shift_seconds: float = 1.0)`, thêm `mixing: MixingConfig` vào
  `AppConfig`. Kiểu `(int, float)` cho cả ba (bool bị `_check_section` chặn
  sẵn). Key lạ → `ConfigError` như các section khác.
- `validate_mixing(original_volume, speech_volume, max_shift_seconds)` raise
  `ConfigError`: `0.0 <= original_volume <= 1.0`, `0.0 < speech_volume <= 2.0`,
  `max_shift_seconds >= 0.0`. Gọi ở cả `parse_config` và `_cmd_render`
  (cùng thông báo lỗi; mẫu: `validate_timing_ratios`).
- CLI: `python -m app render EPISODE_DIR [--original-volume X] [--max-shift S]
  [--allow-missing] [--force]` (+ `--config` qua parent parser). Flag mặc
  định `None` (trừ `--allow-missing`/`--force` là `store_true`); ghi đè
  config rồi validate, sai → `[render] LỖI: …` exit 1. Không có flag cho
  `speech_volume` (đã có `tts.volume`), không có config cho `--allow-missing`.

## Hành vi bắt buộc
- **Kiểm tra đầu vào** (raise `RenderError` → CLI exit 1, thông báo có gợi ý
  lệnh cần chạy trước):
  - thiếu `normalized.json` → "Chạy `normalize`…"; JSON hỏng/thiếu `segments`
    → `RenderError` (không tự chạy lại `normalize`);
  - thiếu `source.mp4` → "Chạy `download`…";
  - segment có `audio` mà file **không tồn tại trên đĩa** hoặc `audio_duration`
    là `None` → liệt kê hết các id rồi raise, gợi ý "chạy lại `normalize`"
    (kể cả khi `allow_missing=True` — đây là `normalized.json` cũ/hỏng,
    không phải câu "missing" hợp lệ);
  - `missing_ids` (status `"missing"`) khác rỗng và `allow_missing=False` →
    raise: "N segment thiếu audio (id …): chạy lại `tts` rồi `normalize`,
    hoặc dùng `--allow-missing` để chèn im lặng". `allow_missing=True` → bỏ
    qua chúng như `silent`, ghi vào `RenderResult.missing_ids`, CLI in `CẢNH BÁO`.
- **Resume / `--force`**:
  - Đầu stage xoá `voice_track.tmp.wav`, `output_vi.tmp.mp4` sót lại.
  - `voice_track.wav` SKIP khi tồn tại **và** `render.json` có
    `voice_track.fingerprint` khớp. Không khớp / thiếu file / `render.json`
    hỏng (log rồi coi như chưa có) → dựng lại.
  - `output_vi.mp4` SKIP khi tồn tại **và** `output.fingerprint` khớp. Vì
    fingerprint output chứa fingerprint voice, dựng lại voice track (nội dung
    đổi) tự động kéo theo mux lại; đổi `--original-volume` **chỉ** mux lại,
    không dựng lại voice track.
  - Thứ tự ghi `render.json`: sau khi `voice_track.wav` đã `os.replace` xong →
    ghi `render.json` chỉ có section `voice_track` (bỏ section `output` cũ);
    sau khi `output_vi.mp4` đã `os.replace` xong → ghi thêm section `output`.
    Mux lỗi giữa chừng thì lần sau vẫn SKIP voice, chỉ mux lại. `--force`
    làm lại cả hai.
  - Tuyệt đối không gọi lại TTS/dịch/Whisper/`normalize` từ `render`.
- `total_seconds = max(duration của source.mp4 (probe_duration), max(placed_at +
  audio_duration))`. Nếu audio cuối kết thúc muộn hơn video > 0.05s → `log`
  cảnh báo "phần thừa bị cắt ở output_vi.mp4", không raise.
- Không có segment nào có audio (toàn `silent`) vẫn hợp lệ: track toàn im
  lặng, vẫn mux.
- `log` các mốc: dựng voice track (N segment), SKIP voice track, mux, SKIP
  mux. CLI truyền `lambda m: print(m, flush=True)` như `_cmd_normalize`.
- CLI in report sau cùng (SKIP thì vẫn in, đọc từ tính toán lại/`render.json`):
  ```
  [render] segments     : 58
  [render] placed       : 58
  [render] silent       : 0
  [render] missing      : 0
  [render] shifted      : 5 (tối đa 0.51s)
  [render] overlap      : 0
  [render] voice_track  : <ep>/voice_track.wav
  [render] output       : <ep>/output_vi.mp4
  ```
  `overlap` có id thì in ` (id 9, 19)` sau số đếm (như `too_long` của
  `normalize`). `missing` khác rỗng (chỉ khi `--allow-missing`) → thêm dòng
  `[render] CẢNH BÁO: N segment thiếu audio (id …) được thay bằng im lặng.`
  `RenderError` → `[render] LỖI: …` ra stderr, exit 1.

## Test (unittest, mock tiến trình/dịch vụ ngoài)
`tests/test_render.py` — dựng episode giả trong `TemporaryDirectory`
(`normalized.json`, `source.mp4` bytes bất kỳ, file audio giả); patch
`app.audio.render.probe_duration`, `decode_pcm`, `mix_video`,
`VOICE_SAMPLE_RATE_HZ` (=100 cho nhẹ; `render_episode` phải đọc hằng này
lúc gọi, `build_voice_track` nhận `sample_rate` không mặc định):
- `plan_placements`:
  - không chồng → `placed_at == start`, shift 0, overlap 0;
  - A `start=0, audio=3.5`, B `start=3.0, audio=2.0` → B `placed_at=3.5`,
    shift 0.5, overlap 0; C `start=5.5` sau đó → shift 0 (hồi phục);
  - `max_shift=0.3` → B `placed_at=3.3`, shift 0.3, overlap 0.2;
    `max_shift=0` → `placed_at == start`, overlap 0.5;
  - chuỗi nhiều `too_long` liên tiếp → `shift` không bao giờ vượt `max_shift`;
  - bỏ segment `audio=None`; input đảo thứ tự vẫn ra thứ tự `(start, id)`.
- `build_voice_track` (sr=100, `decode_pcm` trả `array('h',[v]*n).tobytes()`):
  - đặt đúng vị trí (sample `[100,150)` = 1000, còn lại = 0); tổng số frame =
    `ceil(total_seconds*sr)`; header WAV mono / sampwidth 2 / framerate = sr;
  - vùng đè được **cộng** (1000 + 2000 = 3000), kẹp `32767`/`-32768`;
  - pcm vượt cuối track bị cắt, không raise;
  - `decode_pcm` raise → không có `voice_track.wav` và không còn `.tmp.wav`.
- `decode_pcm`: lệnh chứa `s16le`, `-ac 1`, `-ar 24000`; trả đúng bytes
  stdout; len lẻ bị cắt 1 byte; exit != 0 / stdout rỗng / `shutil.which`
  None → `RenderError`.
- `mix_video`: lệnh chứa `-c:v copy`, `-map 0:v:0`,
  `amix=inputs=2:duration=first:normalize=0`, `volume=0.3000`, ghi qua
  `output_vi.tmp.mp4` rồi replace; exit != 0 → `RenderError` + tmp bị xoá;
  ffmpeg không có → `RenderError`.
- `render_episode`:
  - lần 1 dựng voice + mux, ghi `render.json` (đủ hai section,
    `placements` đúng số segment có audio); lần 2 → cả hai `skipped`, không
    gọi `decode_pcm`/`mix_video`;
  - `force=True` → làm lại cả hai;
  - đổi `original_volume` → `voice_track_skipped=True`, `output_skipped=False`
    (`decode_pcm` không được gọi);
  - đổi `max_shift` → fingerprint đổi (kể cả khi placement thực tế không đổi)
    → dựng lại voice + mux lại;
  - sửa `audio_duration`/`tts_cache_key` một segment trong `normalized.json` →
    dựng lại voice + mux lại;
  - xoá tay `output_vi.mp4` → chỉ mux lại; xoá `voice_track.wav` → dựng lại
    voice (mux SKIP nếu fingerprint output vẫn khớp và file còn);
  - `render.json` hỏng → dựng lại cả hai, không raise;
  - dọn `voice_track.tmp.wav`/`output_vi.tmp.mp4` mồ côi;
  - mux raise lần 1 → `render.json` chỉ có `voice_track`; lần 2 SKIP voice,
    mux lại;
  - `missing` + `allow_missing=False` → `RenderError` (nêu đủ id, gợi ý `tts`
    rồi `normalize`); `allow_missing=True` → thành công, `missing_ids` có id,
    segment đó không nằm trong `placements`;
  - `silent` → không nằm trong `placements`, không lỗi;
  - file `audio` không tồn tại trên đĩa (dù status `normal`) → `RenderError`;
  - thiếu `normalized.json` / JSON hỏng / thiếu `source.mp4` → `RenderError`;
  - toàn `silent` → vẫn ra voice track im lặng + mux.
`tests/test_config.py`: `MixingConfig` mặc định (0.30 / 1.0 / 1.0); đọc section
`mixing`; key lạ; `original_volume` < 0 hoặc > 1; `speech_volume` = 0 hoặc > 2;
`max_shift_seconds` < 0; sai kiểu (`"0.3"`, `true`) → `ConfigError`.
`tests/test_cli.py`: `render --help` chạy được; `--original-volume 2` → exit 1;
thiếu `normalized.json` → exit 1; `RenderError` → exit 1 + `[render] LỖI`;
báo cáo in đủ dòng (patch `app.audio.render.render_episode`); `--allow-missing`
được truyền xuống `render_episode`.

## Chạy thật (BẮT BUỘC)
Episode đã có `normalized.json` (58 segment: 48 normal / 6 stretched / 4
too_long id 8, 18, 24, 38 / silent 0 / missing 0), `source.mp4` 640x360 h264 +
aac 44100 stereo, ~243.55s:
```bash
EP="output/zGuIUytF_6U__Guess How Much I Love You Read Aloud _ Kids Books Read Aloud"
PY=.venv/Scripts/python.exe
$PY -m app render "$EP"                          # 1: dựng voice_track + mux
$PY -m app render "$EP"                          # 2: SKIP cả hai, < 1s
$PY -m app render "$EP" --original-volume 0.5    # 3: voice_track SKIP, chỉ mux lại
$PY -m app render "$EP" --max-shift 0            # 4: dựng lại voice_track (có overlap) + mux
$PY -m app render "$EP" --force                  # 5: về mặc định, làm lại cả hai
```
Bước 5 để episode kết thúc ở cấu hình mặc định. Kiểm tra bằng script tạm
trong scratchpad (không thêm vào repo) và ffprobe/ffmpeg — **mở artifact, không
chỉ xem exit code**:
- **Report lần 1**: placed 58, silent 0, missing 0, `overlap` 0 (id trống).
  `shifted` > 0 và `max_shift_seen` ≈ 0.51 (từ id 8 → id 9; xấp xỉ).
  `overlap` khác rỗng ở mặc định → escalate.
- **`voice_track.wav`** (module `wave`): 1 kênh, sampwidth 2, framerate 24000,
  duration ≈ 243.55s (± 0.05s), kích thước ≈ 11.7 MB.
- **Vị trí đúng (kiểm độc lập với `render.json`)**: RMS (đơn vị int16) —
  cửa sổ `[5.4, 5.9]s` **bằng đúng 0** (id 1 chỉ dài 5.208s, id 2 bắt đầu ở 6.0s)
  và `[6.2, 6.7]s` **> 200** (id 2, chưa bị dời). Nếu lệch → placement sai
  (chỉ khi mp3 có lead-in im lặng dài thì mới nới cửa sổ tới `[6.2, 7.0]s` và
  ghi chú lại).
- **Từ `render.json` (bước 1)**: `placements` có 58 entry đúng thứ tự id; id 9
  `placed_at ≈ 34.51` (`shift ≈ 0.51`); id 1, 2 `shift == 0`. Mọi khoảng trống
  ≥ 0.3s giữa hai placement liên tiếp (`[placed_i + audio_duration_i + 0.05,
  placed_{i+1} − 0.05]`) có RMS **bằng đúng 0** (gồm 3 khoảng trống 1.0s của
  video: id 6→7, 29→30, 43→44). Mọi placement, RMS toàn đoạn
  `[placed_at, placed_at + audio_duration]` **> 200**; báo giá trị nhỏ nhất.
- **`output_vi.mp4`**: `ffprobe -show_streams` → đúng 1 stream video `h264`
  640x360 + đúng 1 stream audio `aac` 2 kênh (ghi lại sample_rate); `ffprobe
  -show_entries format=duration` trong ± 0.1s của `source.mp4`.
- **Video không bị encode lại**: md5 khớp giữa
  `ffmpeg -v error -i <file> -map 0:v:0 -c copy -f md5 -` của `source.mp4` và
  `output_vi.mp4` (nếu khác, so thêm `ffprobe -count_packets -select_streams v
  -show_entries stream=nb_read_packets`; vẫn khác không giải thích được →
  escalate).
- **Mức âm**: `ffmpeg -i output_vi.mp4 -af volumedetect -f null -` → ghi
  `mean_volume`/`max_volume` của `output_vi.mp4` và của `source.mp4` vào
  decisions. `max_volume` ≥ −0.1 dB (nghi clip) → escalate.
- **Resume**: lần 2 in SKIP cho cả hai (mtime `voice_track.wav` và
  `output_vi.mp4` không đổi, < 1s); lần 3 SKIP voice_track (mtime giữ nguyên),
  `output_vi.mp4` mới hơn; lần 4 `render.json` có `overlap > 0` ở id 9 (xấp xỉ
  0.51) và `output.params.original_volume` về 0.3 sau lần 5; lần 5 mtime cả hai
  file đều mới.
- Ghi vào mục D của decisions: thời gian lần 1, lần SKIP, lần chỉ-mux,
  kích thước hai file, `max_shift_seen`, số `shifted`.

## Ngoài phạm vi
- **Nghe bằng tai người** (chất lượng giọng ở tempo 1.25 quanh 0:33–0:36 = id
  8; độ to/nhỏ audio gốc; có nên hạ `timing.max_tempo` hay đổi
  `original_volume`): việc của user sau khi có `output_vi.mp4`, implementer
  không có tiêu chí này.
- Ducking động (sidechaincompress), source separation (plan §16), rút gọn câu
  `too_long` bằng LLM (CP9), cắt khoảng lặng mp3 edge-tts.
- Lệnh `dub` end-to-end + `app/pipeline/*` (CP7), playlist (CP8).
- Tối ưu bộ nhớ khi dựng track cho video rất dài: `bytearray` cả track tốn
  ~2.9 MB/phút (video 2 giờ ≈ 350 MB) — chấp nhận; ghi lại giới hạn này ở
  decisions, không stream-hoá (plan §23: không tối ưu sớm).
- Xử lý audio gốc không phải stereo/không có audio stream ngoài việc để ffmpeg
  báo lỗi (đưa nguyên stderr vào `RenderError`).

## Điểm phải escalate
- ffmpeg trên máy báo không có option `normalize` của `amix` (ffmpeg cũ) hoặc
  filter graph ở trên lỗi — đừng tự đổi cách bù volume.
- Video stream của `output_vi.mp4` không khớp `source.mp4` (mất `-c:v copy`),
  duration lệch > 0.1s, hoặc nghi clip (`max_volume` ≥ −0.1 dB).
- Ở tham số mặc định vẫn có `overlap` > 0, hoặc `shifted` lớn bất thường
  (vd > 30 trên 58 segment; dự đoán ~10–15 vì mỗi `too_long` kéo theo 2–4 câu
  sau, drift hồi phục dần) — dấu hiệu thuật toán dời sai.
- Kiểm tra vị trí RMS ở trên không đạt.
- `normalized.json` thật khác schema `checkpoint-5.md` mục A1 (cần đổi contract).
- Muốn đổi mặc định `original_volume`/`max_shift_seconds`, hoặc đổi quyết định
  "missing → lỗi" / "dời có trần" — Opus quyết.

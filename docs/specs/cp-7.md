# CP7 — End-to-end command `dub`

## Mục tiêu
`python -m app dub VIDEO_URL` tự chạy download → transcribe → translate → tts →
normalize → render, gọi thẳng các hàm stage (không đi qua `_cmd_*` của CLI con).
Chạy lại cùng lệnh phải skip hết stage đã xong; thiếu audio/câu dịch lỗi thì tự
sửa trong số vòng giới hạn rồi mới render. Plan: `docs/IMPLEMENTATION_PLAN.md`
dòng 1072–1094 (chỉ có acceptance "một command tạo được output từ URL video").

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|
| `app/pipeline/dub.py` | **Tạo.** `DubOptions`, `DubResult`, `DubError`, `run_dub()` — toàn bộ logic điều phối. |
| `app/pipeline/__init__.py` | Thay docstring placeholder (đang báo "Chưa implement") bằng một dòng mô tả; không re-export gì (import `dub.py` kéo theo yt-dlp/faster-whisper). |
| `app/config.py` | Thêm `PipelineConfig` + section `pipeline` (xem Config). |
| `app/cli.py` | Thêm subparser `dub` + `_cmd_dub` (mỏng: dựng `DubOptions`, gọi `run_dub`, in tổng kết); thêm vào `_COMMANDS`; cập nhật docstring đầu file ("Checkpoint 7: subcommand ``dub``"). |
| `config.example.yaml` | Thêm section `pipeline`. |
| `tests/test_pipeline_dub.py` | **Tạo.** |
| `tests/test_config.py`, `tests/test_cli.py` | Thêm case cho `pipeline` và parser `dub`. |
| `docs/decisions/checkpoint-7.md` | **Tạo**, mục A là contract cho CP8 (playlist sẽ gọi `run_dub` cho từng video). |

## Interface

```python
# app/pipeline/dub.py
# Import stage ở cấp module (không import cục bộ) để test patch được
# `app.pipeline.dub.download_video`, `app.pipeline.dub.translate_transcript`, ...
from app.youtube.download import VideoDownloadError, download_video
from app.audio.ffmpeg import AUDIO_FILENAME, AudioExtractionError, extract_audio
from app.transcription.whisper import TRANSCRIPT_FILENAME, TranscriptionError, transcribe_audio
from app.translation import create_translator
from app.translation.base import TranslationError          # GlossaryError là subclass
from app.translation.glossary import GLOSSARY_FILENAME, load_effective_glossary
from app.translation.translate import TRANSLATED_FILENAME, translate_transcript
from app.tts import create_tts_engine
from app.tts.base import TTSError
from app.tts.synthesize import TTS_DIRNAME, synthesize_translation
from app.synchronization.timing import TimingError, normalize_timing
from app.audio.render import RenderError, render_episode

STAGES = ("download", "transcribe", "translate", "tts", "normalize", "render")

class DubError(RuntimeError):
    """Lỗi ở một stage; ``stage`` là một phần tử của STAGES."""
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage

@dataclass(frozen=True)
class DubOptions:
    workspace: Path
    source_lang: str | None = None        # None = auto-detect
    shared_glossary: Path | None = None   # đã resolve flag > config
    original_volume: float = 0.30          # đã resolve flag > config
    allow_missing: bool = False
    force: bool = False

@dataclass
class DubResult:
    episode_dir: Path
    output_path: Path                      # <ep>/output_vi.mp4
    source_language: str                   # ngôn ngữ ghi trong transcript.json
    segments: int
    translate_failed_ids: list[int]        # còn lỗi sau mọi vòng -> câu im lặng trong output
    missing_ids: list[int]                 # chỉ khác rỗng khi allow_missing=True
    too_long_ids: list[int]
    repair_rounds_used: int                # tổng vòng lặp lại (translate + tts/normalize)
    glossary_paths: list[Path]             # rỗng = dịch không glossary
    stage_seconds: dict[str, float]        # thời gian thực mỗi stage (cả khi skip)
    skipped_stages: list[str]              # stage không làm gì (artifact đã khớp)

def run_dub(
    url: str, config: AppConfig, options: DubOptions, *,
    log: Callable[[str], None] = print,
) -> DubResult
```

Tái sử dụng (chữ ký đã chốt, **không sửa** các hàm này):
- `download_video(url, workspace_dir, *, force) -> EpisodeInfo` (`.episode_dir`, `.source_path`) — `app/youtube/download.py:165`. Luôn gọi `_extract_info` (mạng) kể cả khi skip.
- `extract_audio(source_path, audio_path, *, force)` — `app/audio/ffmpeg.py:25`.
- `transcribe_audio(audio_path, transcript_path, *, model_size, device, compute_type, language, force) -> TranscriptResult(language, segments, transcript_path)` — `app/transcription/whisper.py:108`. Có transcript thì đọc lại, **không kiểm `language`**.
- `load_effective_glossary(episode_dir, shared: Path | None) -> (Glossary | None, list[Path])` — `app/translation/glossary.py`.
- `translate_transcript(transcript_path, translated_path, translator, *, target_language, batch_size, context_size, max_attempts, force, glossary, log) -> TranslationResult(.skipped, .failed_ids, .segments, .source_language)` — `app/translation/translate.py:211`. Gọi lại không `force` ⇒ tự thử lại các `failed_ids` (CP3 A1).
- `synthesize_translation(translated_path, tts_dir, engine, *, max_attempts, concurrency, force, log) -> TTSResult(.skipped, .failed_ids, ...)` — `app/tts/synthesize.py:182`.
- `normalize_timing(episode_dir, *, normal_max_ratio, max_tempo, force, log) -> TimingResult(.missing_ids, .too_long_ids, .skipped, ...)` — `app/synchronization/timing.py:190`.
- `render_episode(episode_dir, *, original_volume, speech_volume, max_shift, allow_missing, force, log) -> RenderResult(.output_path, .missing_ids, .voice_track_skipped, .output_skipped, ...)` — `app/audio/render.py:393`.
- `create_translator(config.translation)`, `create_tts_engine(config.tts)`; validate: `validate_mixing`, `validate_timing_ratios`, `validate_rate_or_volume` ở `app/config.py`.
- Cách nối tham số config → hàm: copy đúng như `_cmd_transcribe/_cmd_translate/_cmd_tts/_cmd_normalize/_cmd_render` trong `app/cli.py` (vd `batch_size=tconfig.batch_size`, `concurrency=config.tts.concurrency`, `speech_volume=config.mixing.speech_volume`).

## Artifact
- Vào: chỉ URL. Không có artifact mới — `dub` chỉ ghi các artifact stage vốn có
  (`metadata.json`, `source.mp4`, `audio.wav`, `transcript.json`, `translated.json`,
  `tts/`, `timing/`, `normalized.json`, `voice_track.wav`, `render.json`,
  `output_vi.mp4`). **Không** tạo `dub.json`/state file riêng (resume dựa hoàn toàn
  vào cache của từng stage).
- Ra: `<workspace>/<video_id>__<title>/output_vi.mp4` (schema `render.json` theo CP6 A3, không đổi).

## Config
`config.example.yaml` thêm cuối file:
```yaml
pipeline:
  repair_rounds: 2   # `dub`: số vòng tối đa chạy lại translate (câu dịch lỗi) và tts+normalize (thiếu audio); 0 = không thử lại
```
`app/config.py`: `@dataclass(frozen=True) class PipelineConfig: repair_rounds: int = 2`;
`AppConfig.pipeline: PipelineConfig = field(default_factory=PipelineConfig)`;
`_PIPELINE_TYPES = {"repair_rounds": (int,)}`; thêm `"pipeline"` vào `top_level`;
`repair_rounds < 0` → `ConfigError`; `True/False` không được coi là int (kiểm `type(v) is bool` nếu `_check_section` chưa chặn).

CLI `dub` (flag mặc định `None` để phân biệt "không truyền", như các lệnh khác):

| Flag | Nguồn khi không truyền |
|---|---|
| `url` (positional) | — |
| `--workspace` | `config.workspace` |
| `--source-lang` (mặc định `"auto"`) | `auto` → `None` |
| `--glossary` | `config.translation.glossary` |
| `--original-volume` (float) | `config.mixing.original_volume` |
| `--allow-missing` (store_true) | False |
| `--force` (store_true) | False — làm lại **mọi** stage (tải lại, whisper lại, dịch lại, TTS lại). Help phải nói rõ là tốn thời gian/gọi lại AI. |
| `--config` | parent `common` như các lệnh khác |

Không thêm flag model/voice/max-tempo: chỉnh qua config.

## Hành vi bắt buộc

Luồng trong `run_dub` (mỗi stage bọc `try/except <LỗiStage> as exc: raise DubError(stage, str(exc)) from exc`):

0. **Validate trước khi chạm mạng**: `validate_mixing(original_volume, speech_volume, max_shift_seconds)`, `validate_timing_ratios(...)`, `validate_rate_or_volume` cho `tts.rate/volume`; `config.translation.model` là `None` → `DubError("translate", ...)` ngay (đừng để tải + whisper 10 phút rồi mới báo thiếu model). `ConfigError` → `DubError(<stage liên quan>, ...)`.
1. **download**: `download_video(url, options.workspace, force=options.force)`.
2. **transcribe**: `extract_audio` + `transcribe_audio(language=options.source_lang, force=options.force)`.
   **Kiểm ngôn ngữ**: nếu `options.source_lang` khác `None` và khác `result.language` (transcript cache cũ nhận sai ngôn ngữ) → `DubError("transcribe", ...)` nêu cả hai mã và lệnh sửa:
   `python -m app transcribe "<ep>" --source-lang <lang> --force` rồi chạy lại `dub`.
   Không tự xoá/ghi đè transcript (làm vậy sẽ kéo theo dịch lại cả tập mà người dùng chưa đồng ý).
   Nếu `source_lang is None` và `result.language != "en"` → log một dòng `[dub] LƯU Ý: Whisper tự nhận ngôn ngữ '<lang>' — nếu sai, chạy lại với --source-lang` (bẫy zh→en trong CLAUDE.md).
3. **glossary** (không phải stage riêng): `load_effective_glossary(ep, options.shared_glossary)`; `GlossaryError` → `DubError("translate", ...)`. Không có `<ep>/glossary.yaml` → log đúng một dòng:
   `[dub] Chưa có glossary.yaml — nên chạy: python -m app glossary "<ep>", sửa file, rồi chạy lại dub.`
   **Không** gọi `draft_glossary_file`. Có glossary → log `[dub] glossary : p1, p2`.
4. **translate**: `translate_transcript(..., force=options.force, glossary=glossary)`. Nếu `failed_ids` khác rỗng: gọi lại **không force** tối đa `repair_rounds` lần (dừng sớm khi rỗng). Còn lỗi sau đó → **không** dừng pipeline (các câu này thành `status: "empty"` ở tts → im lặng ở output, CP6.5 A3), ghi vào `DubResult.translate_failed_ids` và log `CẢNH BÁO`.
5. **tts**: `synthesize_translation(..., force=options.force)`. `TTSError` (fail-fast/toàn bộ lỗi) → `DubError("tts")`.
6. **normalize**: `normalize_timing(..., force=options.force)`.
7. **vòng sửa thiếu audio** (CP5 A3 / CP6 A2): `while missing_ids and rounds < repair_rounds`: gọi lại `synthesize_translation(force=False)` rồi `normalize_timing(force=False)`. **Không** truyền `force` vào vòng sửa (dù `options.force`) — nếu không sẽ tổng hợp lại toàn bộ mỗi vòng. Đếm tổng vòng (bước 4 + bước 7) vào `repair_rounds_used`.
8. **render**: còn `missing_ids` và không `allow_missing` → `DubError("render", "N segment thiếu audio (id ...) sau <R> vòng thử lại — chạy lại dub, hoặc thêm --allow-missing để chèn im lặng")` **trước** khi gọi `render_episode` (thông điệp rõ hơn RenderError). Ngược lại gọi `render_episode(..., original_volume=options.original_volume, speech_volume=config.mixing.speech_volume, max_shift=config.mixing.max_shift_seconds, allow_missing=options.allow_missing, force=options.force)`.

Log:
- Trước mỗi stage: `[dub] (i/6) <stage> ...`; sau: `[dub] (i/6) <stage> xong (12.3s)` hoặc `... SKIP (0.4s)`. Log con của stage truyền nguyên (`log`), prefix `[translate]`/`[tts]`… của stage giữ nguyên.
- `skipped_stages`: download khi `source.mp4` đã có và không force (so `exists()` **trước** khi gọi); transcribe khi `transcript.json` đã có trước khi gọi; translate/tts/normalize theo `.skipped` của lần gọi đầu và không có vòng sửa; render khi `voice_track_skipped and output_skipped`.
- CLI in `flush=True` (như các lệnh khác — playlist chạy hàng giờ).

`_cmd_dub` in tổng kết:
```
[dub] episode    : output\zGuIUytF_6U__Guess How Much ...
[dub] ngôn ngữ   : en -> vi
[dub] segments   : 58
[dub] too_long   : 1 (id 23)
[dub] sửa lại    : 0 vòng
[dub] thời gian  : download 3.1s, transcribe 0.0s, translate 0.0s, tts 0.1s, normalize 0.2s, render 0.3s (tổng 3.7s)
[dub] output     : output\...\output_vi.mp4
```
+ dòng `CẢNH BÁO` riêng cho `translate_failed_ids` và cho `missing_ids` (khi `--allow-missing`).
`DubError` → `print(f"[dub] LỖI {exc}", file=sys.stderr)`, exit 1. `ConfigError` khi dựng options (vd `--original-volume 2`) → exit 1.

Edge case:
- Ctrl+C giữa chừng: không bắt `KeyboardInterrupt`; các stage đã ghi atomic, chạy lại `dub` tiếp tục.
- `options.force` chỉ áp cho lần gọi đầu của mỗi stage (không áp vào các vòng sửa).
- Không đổi hành vi các lệnh con cũ.

## Test (unittest, mock tiến trình/dịch vụ ngoài)
`tests/test_pipeline_dub.py` — patch các tên ở `app.pipeline.dub` (`download_video`, `extract_audio`, `transcribe_audio`, `create_translator`, `load_effective_glossary`, `translate_transcript`, `create_tts_engine`, `synthesize_translation`, `normalize_timing`, `render_episode`); episode dir là `tempfile.TemporaryDirectory`; kết quả giả bằng `SimpleNamespace`/dataclass thật.
1. Đường thẳng: gọi đủ 6 stage đúng thứ tự, tham số lấy từ config (`batch_size`, `concurrency`, `max_tempo`, `speech_volume`, `max_shift`), `original_volume` từ options; trả `DubResult.output_path` đúng.
2. `force=True` truyền vào lần gọi đầu mọi stage; các vòng sửa gọi với `force=False`.
3. `source_lang="zh"`, transcript cache trả `language="en"` → `DubError` stage `transcribe`, message chứa `--source-lang zh --force`; `translate_transcript` không được gọi.
4. `source_lang=None`, language `"zh"` → có dòng `LƯU Ý` trong log, pipeline chạy tiếp.
5. Thiếu `translation.model` → `DubError("translate")` và `download_video` **không** được gọi.
6. Glossary: không có `<ep>/glossary.yaml` → log chứa `python -m app glossary`; có glossary → `translate_transcript` nhận `glossary=` đúng object; `GlossaryError` → `DubError("translate")`. Không có đường nào gọi `draft_glossary_file`.
7. Translate `failed_ids=[5]` lần 1, `[]` lần 2 → gọi 2 lần, `repair_rounds_used == 1`, `translate_failed_ids == []`.
8. Translate luôn `failed_ids=[5]`, `repair_rounds=2` → gọi 3 lần, pipeline vẫn render, `translate_failed_ids == [5]`.
9. Normalize `missing_ids=[3]` rồi `[]` → tts gọi 2 lần, normalize 2 lần, render được gọi với `allow_missing=False`.
10. Normalize luôn `missing_ids=[3]`, `repair_rounds=2` → tts 3 lần, normalize 3 lần, `DubError("render")` chứa `--allow-missing`, `render_episode` không được gọi.
11. Như 10 nhưng `allow_missing=True` → render gọi với `allow_missing=True`, `DubResult.missing_ids == [3]` (lấy từ `RenderResult`).
12. `repair_rounds=0` + missing → không gọi lại tts.
13. Mỗi loại lỗi stage (`VideoDownloadError`, `AudioExtractionError`, `TranscriptionError`, `TranslationError`, `TTSError`, `TimingError`, `RenderError`) → `DubError` với `.stage` đúng, stage sau không được gọi.
14. `skipped_stages`: source/transcript tồn tại sẵn + mọi `.skipped=True` + render skip cả hai → đủ 6 tên.

`tests/test_config.py`: `pipeline.repair_rounds` mặc định 2; đọc được `0`; âm → `ConfigError`; kiểu sai (`"2"`, `true`) → `ConfigError`; section lạ vẫn báo lỗi và thông điệp liệt kê `pipeline`.
`tests/test_cli.py`: parse `dub URL` mặc định (`source_lang == "auto"`, `force False`); `_cmd_dub` với `run_dub` patch: flag ghi đè config (`--workspace`, `--original-volume`, `--glossary`), `--source-lang auto` → `None`; `--original-volume 1.5` → exit 1 không gọi `run_dub`; `DubError` → exit 1 và stderr có `[dub] LỖI`.

## Chạy thật (BẮT BUỘC)
Trước khi chạy: `ollama ps` sau lần dịch đầu phải thấy `GPU` ở cột PROCESSOR (xem CLAUDE.md). URL dùng thử (episode đã có đủ artifact CP6.5 trong `output/`):
`https://www.youtube.com/watch?v=zGuIUytF_6U` (tiếng Anh, ~4 phút, 58 segment).

1. **Resume trên episode có sẵn**:
   `.venv/Scripts/python.exe -m app dub "https://www.youtube.com/watch?v=zGuIUytF_6U"`
   Đạt: exit 0; `skipped_stages` đủ 6 (log mỗi stage `SKIP`); không có dòng `[translate]`/`[tts]` gọi model/mạng TTS; `LastWriteTime` của `output_vi.mp4`, `translated.json`, `tts/manifest.json` **không đổi** (ghi lại trước/sau); tổng thời gian chỉ vài giây ngoài `_extract_info`. Không in dòng nhắc glossary (tập này đã có `glossary.yaml`).
2. **Từ đầu, workspace mới**:
   `.venv/Scripts/python.exe -m app dub "https://www.youtube.com/watch?v=zGuIUytF_6U" --workspace output/cp7-e2e`
   Đạt: có dòng nhắc chạy `glossary`; `output/cp7-e2e/<ep>/output_vi.mp4` tồn tại; `ffprobe -v error -show_entries stream=codec_type,codec_name,sample_rate,channels -of compact <mp4>` ra đúng `video|h264` + `audio|aac|44100|2`; `render.json` `summary.missing == 0`, `placed + silent == 58` (hoặc bằng số segment trong `transcript.json` mới); `translated.json` `glossary_sha256 == null`, `failed_ids == []`; `output.duration` ≈ 243.55. Ghi thời gian từng stage vào decisions mục D.
3. **Chạy lại lệnh 2** → mọi stage `SKIP`, mtime `output_vi.mp4` không đổi.
4. **Sửa một phần**: xoá **một** file mp3 trong `output/cp7-e2e/<ep>/tts/` rồi chạy lại lệnh 2. Đạt: log tts `tổng hợp 1`, cache 57 (hoặc tương đương); normalize/render dựng lại; translate SKIP.
5. **Glossary**: `.venv/Scripts/python.exe -m app glossary "output/cp7-e2e/<ep>"`, rồi chạy lại lệnh 2. Đạt: dòng `[dub] glossary : ...`; translate dịch lại (không cần `--force`); `translated.json` `glossary_sha256` khác `null`; tts chỉ tổng hợp các câu có text đổi (ghi số `tổng hợp X, cache Y`).
6. **Bẫy ngôn ngữ**: lệnh 1 + `--source-lang zh` → exit 1, stderr có `en` và `zh` và lệnh `transcribe ... --force`; không stage nào sau transcribe chạy; `transcript.json` không đổi.
7. **Mở bằng tai/mắt**: mở `output/cp7-e2e/<ep>/output_vi.mp4`, tua 3 chỗ (đầu, 0:33, cuối) — có giọng Việt, video chạy, audio gốc nhỏ phía sau. Không nghe được thì ghi rõ "chưa nghe" vào báo cáo.

Không commit `output/cp7-e2e/` (đã gitignore `output/`? — kiểm `git status` sau khi chạy).

## Ngoài phạm vi
- Playlist / nhiều URL / nhận `episode_dir` thay cho URL (CP8).
- Tự tạo glossary trong `dub`; `--force-from <stage>`; flag model/voice/tempo riêng cho `dub`.
- File trạng thái `dub.json`, report tổng hợp, retry mạng cho `_extract_info` khi offline.
- Sửa các hàm stage hoặc schema artifact của CP1–CP6.5.
- Refactor `_cmd_*` cũ để dùng chung code với `dub` (chỉ copy cách nối tham số).
- Cập nhật README/SETUP/CLAUDE.md (làm ở commit docs riêng sau khi review).

## Điểm phải escalate
- Cần sửa chữ ký/hành vi một hàm stage để `dub` gọi được (vd `translate_transcript` gọi lại không force mà **không** thử lại `failed_ids`, hoặc `synthesize_translation` không tự tổng hợp lại file mp3 bị xoá).
- `download_video` khi chạy lại tạo thư mục episode **khác** với lần trước (title đổi → tên thư mục đổi → mất resume) — ghi lại, không tự sửa.
- `output/` không được gitignore.
- Chạy thật bước 2 lệch lớn so với episode gốc (số segment khác, `too_long` tăng mạnh, dịch trượt xưng hô ba–con) — báo số liệu, không tự đổi model/tham số.

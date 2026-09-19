# CP8 — Playlist

## Mục tiêu
`python -m app playlist PLAYLIST_URL` lấy danh sách video của playlist (yt-dlp
flat), gọi `run_dub` **tuần tự** cho từng tập, ghi trạng thái từng tập vào
`playlist.json` sau mỗi tập để resume, bỏ qua tập đã xong, một tập lỗi không
chặn cả playlist, in summary cuối (`completed / skipped / failed`).

## SỬA ĐỔI 1 (user yêu cầu giữa chừng — ưu tiên hơn mọi chỗ khác trong spec)

Tải về trước, xử lý offline, **hai việc chạy song song**:

- **Luồng tải** (`threading.Thread`, daemon): tải lần lượt từng tập được chọn
  theo `index` bằng `download_video(entry.url, playlist_dir, force=options.dub.force)`,
  **một tập mỗi lần** (không tải song song nhiều tập — rate limit YouTube).
  Bỏ qua tập sẽ bị `skipped` (hành vi #4). Kết quả từng tập đẩy vào
  `queue.Queue` hoặc dict + `threading.Event` theo index.
- **Luồng chính** xử lý tuần tự theo `index`: chờ kết quả tải của tập đó, rồi
  gọi `run_dub(..., episode=<EpisodeInfo>)` → bước download của `run_dub` được
  bỏ qua hoàn toàn (không `_extract_info`, không mạng YouTube). Tải lỗi
  (`VideoDownloadError`) → outcome `failed`, `error_stage="download"`, được
  tính vào đếm lỗi liên tiếp như mọi lỗi khác.
- **Sửa `run_dub`** (được phép, user đã duyệt): thêm keyword-only
  `episode: EpisodeInfo | None = None`. Khác `None` → không gọi
  `download_video`, dùng luôn `episode`, stage `download` ghi vào
  `skipped_stages`, `stage_seconds["download"] = 0.0`, log `(1/6) download SKIP`.
  `None` → giữ nguyên hành vi CP7. `dub` đơn lẻ không đổi.
- `playlist.json` mỗi entry thêm `"downloaded": true|false`; `episode_dir`
  được ghi ngay khi tải xong (trước khi xử lý). Tập đã `downloaded` và thư mục
  còn `source.mp4` + `metadata.json` → luồng tải **không gọi mạng**, dựng lại
  `EpisodeInfo` từ `metadata.json` (thêm hàm
  `load_episode_info(episode_dir: Path, url: str) -> EpisodeInfo` ở
  `app/youtube/download.py`).
- Mọi thao tác sửa entry + ghi `playlist.json` phải đi qua **một
  `threading.Lock`** (hai luồng cùng ghi).
- Flag mới `--download-only`: chỉ chạy luồng tải cho các tập được chọn, không
  xử lý; summary in `downloaded X | failed Y`.
- Dừng sớm (`aborted`) hoặc Ctrl+C: đặt `threading.Event` báo luồng tải dừng
  sau tập đang tải; không `join` vô hạn khi Ctrl+C (daemon thread).
  `source.mp4` chỉ xuất hiện sau khi yt-dlp merge xong nên tập tải dở không bị
  coi là đã tải.
- Test thêm: luồng tải chạy trước xử lý (tập 2 được tải trong lúc tập 1 đang
  `run_dub` — dùng `threading.Event` trong mock để kiểm); `run_dub` nhận
  `episode=` và không gọi `download_video`; tập tải lỗi → failed stage
  `download`, tập sau vẫn xử lý; `--download-only` không gọi `run_dub`;
  entry `downloaded` + file còn → không gọi `download_video`; test `dub.py`
  cho nhánh `episode=`.
- Chạy thật thêm: `--download-only --items 1-3` → 3 `source.mp4` có audio
  (`ffprobe`), `downloaded: true`; sau đó `--items 1-3` → log cho thấy
  `[dub] (1/6) download SKIP (0.0s)` và không có lần gọi mạng YouTube nào
  cho các tập đó. Có ít nhất một lần chạy thấy log tải tập N+1 xen giữa log
  xử lý tập N.

**Điều kiện trước:** CP7 (`app/pipeline/dub.py`, `_cmd_dub`) phải đã được
commit. Nếu `git status` còn file CP7 chưa commit → dừng, báo user.

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|
| `app/youtube/playlist.py` (mới) | `fetch_playlist()` — yt-dlp `extract_flat`, trả `PlaylistInfo` |
| `app/pipeline/playlist.py` (mới) | `run_playlist()`, đọc/ghi `playlist.json`, `parse_item_spec()` |
| `app/pipeline/__init__.py` | export thêm `run_playlist`, `PlaylistOptions`, `PlaylistResult`, `PlaylistError` (theo cách đang export `run_dub`) |
| `app/cli.py` | subcommand `playlist`; tách flag chung của `dub` ra `_add_dub_arguments(parser)` + `_resolve_dub_options(args, config) -> DubOptions \| None` (None = đã in lỗi, exit 1), dùng cho cả `_cmd_dub` và `_cmd_playlist` — hành vi `dub` không đổi |
| `app/config.py` | `PipelineConfig.max_consecutive_failures: int = 3` (int ≥ 0, validate như `repair_rounds`) |
| `config.example.yaml` | thêm key ở mục `pipeline` |
| `app/youtube/download.py` | chỉ sửa docstring đầu module (bỏ câu "Playlist sẽ được xử lý ở checkpoint sau", trỏ sang `app/youtube/playlist.py`) |
| `tests/test_youtube_playlist.py` (mới), `tests/test_pipeline_playlist.py` (mới), `tests/test_cli.py`, `tests/test_config.py` | xem mục Test |
| `docs/decisions/checkpoint-8.md` (mới) | quyết định nhỏ + mục A contract cho CP9 |

## Interface

```python
# app/youtube/playlist.py
class PlaylistError(RuntimeError): ...   # lỗi lấy/đọc playlist (cũng dùng cho playlist.json hỏng, --items sai)

@dataclass(frozen=True)
class PlaylistEntry:
    index: int        # 1-based, theo thứ tự trong playlist
    video_id: str
    title: str        # "untitled" nếu thiếu
    url: str

@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str
    url: str          # URL người dùng truyền vào
    entries: list[PlaylistEntry]

def fetch_playlist(url: str) -> PlaylistInfo
```
- yt-dlp opts: `{"quiet": True, "no_warnings": True, "skip_download": True,
  "extract_flat": "in_playlist", "logger": _SilentYtdlpLogger()}` — tái sử dụng
  `_SilentYtdlpLogger` ở `app/youtube/download.py` (import, không copy).
  Import `yt_dlp` cục bộ trong hàm (như `_extract_info`).
- `info.get("_type") != "playlist"` → `PlaylistError("URL không phải playlist — dùng `python -m app dub URL` cho một video.")`.
- `yt_dlp.utils.DownloadError` → `PlaylistError` (kèm URL + chi tiết).
- `entries` là generator → `list()`. Bỏ entry `None` hoặc không có `id`.
- `index`: `entry.get("playlist_index")` nếu có, không thì vị trí 1-based.
- `url`: `entry["url"]` nếu bắt đầu bằng `http`, không thì
  `f"https://www.youtube.com/watch?v={id}"`.
- Trùng `video_id` → giữ lần xuất hiện đầu, bỏ các lần sau.
- 0 entry sau khi lọc → `PlaylistError("Playlist rỗng ...")`.
- Video private/deleted (flat vẫn trả id, title `[Private video]`) **không** lọc
  ở đây — để `run_dub` fail ở stage download, ghi `failed`.

```python
# app/pipeline/playlist.py
PLAYLIST_STATE_FILENAME = "playlist.json"

@dataclass(frozen=True)
class PlaylistOptions:
    dub: DubOptions               # workspace = workspace GỐC (chưa có thư mục playlist)
    items: frozenset[int] | None = None   # None = mọi tập
    recheck: bool = False
    max_consecutive_failures: int = 3     # 0 = không bao giờ dừng sớm

@dataclass
class EpisodeOutcome:
    index: int
    video_id: str
    title: str
    outcome: str              # "completed" | "skipped" | "failed" | "not_run"
    error_stage: str | None = None
    error: str | None = None
    result: DubResult | None = None

@dataclass
class PlaylistResult:
    playlist_dir: Path
    total: int                # số entry của playlist
    selected: int             # số entry khớp --items
    episodes: list[EpisodeOutcome]   # chỉ entry được chọn, theo index
    aborted: bool             # dừng sớm do max_consecutive_failures

def parse_item_spec(spec: str) -> frozenset[int]     # "1-3,5" -> {1,2,3,5}; sai -> PlaylistError
def run_playlist(url: str, config: AppConfig, options: PlaylistOptions, *,
                 log: Callable[[str], None] = print) -> PlaylistResult
```
- Tái sử dụng: `run_dub`, `DubOptions`, `DubResult`, `DubError` ở
  `app/pipeline/dub.py`; `build_episode_dir_name` ở `app/youtube/download.py`
  (đặt tên thư mục playlist); `OUTPUT_FILENAME` ở `app/audio/render.py`.
- Ghi JSON atomic: viết `_write_json_atomic` riêng trong module (cùng mẫu
  `app/synchronization/timing.py:57` — `.tmp` rồi `os.replace`).
- `parse_item_spec`: phần tử cách nhau dấu phẩy, mỗi phần tử `N` hoặc `A-B`
  (A ≤ B), số nguyên ≥ 1, cho phép khoảng trắng. Rỗng / `0` / `3-1` / `a` → lỗi.

## Artifact

Workspace (khác plan §19 `001_episode-name/` — cố ý, xem "Hành vi" #1):
```text
<workspace>/<playlist_id>__<playlist_title>/
├── playlist.json
├── <video_id>__<title>/        # do run_dub/download_video tạo, y như CP7
│   └── ... output_vi.mp4
└── ...
```

- Vào: `PLAYLIST_URL` (mạng) + `playlist.json` cũ nếu có.
- Ra: `playlist.json` — ghi sau khi fetch (merge) và **sau mỗi tập**:
```json
{
  "playlist_id": "PLxxxxxxxx",
  "title": "Guess How Much I Love You",
  "url": "https://www.youtube.com/playlist?list=PLxxxxxxxx",
  "fetched_at": "2026-09-19T21:05:11+07:00",
  "entries": [
    {
      "index": 1,
      "video_id": "abc123",
      "title": "Episode 1",
      "url": "https://www.youtube.com/watch?v=abc123",
      "status": "completed",
      "episode_dir": "abc123__Episode 1",
      "output_path": "abc123__Episode 1/output_vi.mp4",
      "error_stage": null,
      "error": null,
      "warnings": {"translate_failed_ids": [], "missing_ids": [], "too_long_ids": [8]},
      "seconds": 1834.2,
      "updated_at": "2026-09-19T21:35:45+07:00"
    },
    {
      "index": 2, "video_id": "def456", "title": "Episode 2",
      "url": "https://www.youtube.com/watch?v=def456",
      "status": "failed", "episode_dir": null, "output_path": null,
      "error_stage": "translate", "error": "[translate] Không kết nối được Ollama ...",
      "warnings": null, "seconds": 412.0, "updated_at": "2026-09-19T21:42:37+07:00"
    },
    {
      "index": 3, "video_id": "ghi789", "title": "Episode 3",
      "url": "https://www.youtube.com/watch?v=ghi789",
      "status": "pending", "episode_dir": null, "output_path": null,
      "error_stage": null, "error": null, "warnings": null, "seconds": null, "updated_at": null
    }
  ]
}
```
- `status` lưu trong file chỉ có `pending | completed | failed`. `skipped` và
  `not_run` là kết quả **của một lần chạy**, không lưu.
- `episode_dir`/`output_path` tương đối so với thư mục playlist (dạng POSIX `/`).
- Thời gian: ISO 8601 có timezone local (`datetime.now().astimezone().isoformat(timespec="seconds")`).

## Config
```yaml
pipeline:
  repair_rounds: 2
  max_consecutive_failures: 3   # `playlist`: dừng sau N tập lỗi liên tiếp (lỗi hệ thống: Ollama tắt, hết mạng...); 0 = không dừng
```
Không có flag CLI cho key này.

Flag của `playlist`: đúng bộ flag của `dub` (`--workspace`, `--source-lang`,
`--glossary`, `--original-volume`, `--allow-missing`, `--force`, cùng resolve
flag > config) + riêng:
- `url` (positional) — URL playlist.
- `--items SPEC` — vd `1-3,5`; chỉ xử lý các tập này.
- `--recheck` — gọi lại `run_dub` cả với tập đã `completed` (dùng sau khi sửa
  glossary chung: stage tự resume, chỉ làm lại phần đổi).

## Hành vi bắt buộc
1. **Thư mục playlist** = `options.dub.workspace / build_episode_dir_name(playlist_id, title)`;
   gọi `run_dub(entry.url, config, dataclasses.replace(options.dub, workspace=playlist_dir), log=...)`.
   Tên thư mục tập giữ `<video_id>__<title>` của CP1 (không đổi sang
   `001_...`): khoá resume là `video_id`, ổn định khi playlist bị sắp xếp lại;
   thứ tự nằm trong `playlist.json`.
2. **Mỗi lần chạy luôn fetch lại playlist** (tập mới thêm vào được nhận).
   Merge với `playlist.json` cũ theo `video_id`: giữ `status/episode_dir/output_path/error*/warnings/seconds/updated_at`
   cũ; cập nhật `index/title/url` theo bản mới; id mới → `pending`; id không còn
   trong playlist → bỏ khỏi `entries` (không xoá thư mục), log một dòng
   `[playlist] N tập không còn trong playlist (giữ nguyên thư mục)`.
   Ghi `playlist.json` ngay sau merge, trước khi chạy tập nào.
3. `playlist.json` tồn tại nhưng JSON hỏng / thiếu `entries` → `PlaylistError`
   nói rõ đường dẫn, bảo người dùng sửa hoặc xoá file. **Không** tự ghi đè.
4. **Skip**: entry được chọn có `status == "completed"` **và**
   `playlist_dir / output_path` tồn tại **và** không `recheck` **và** không
   `force` → outcome `skipped`, **không gọi `run_dub`** (không tốn mạng). Nếu
   `completed` nhưng file output mất → chạy lại như thường.
5. `pending`/`failed` luôn được chạy (tập lỗi lần trước tự thử lại).
6. Chạy **tuần tự** theo `index` tăng dần, chỉ các entry khớp `items` (index
   trong `items` mà playlist không có → log cảnh báo một dòng, bỏ qua). Entry
   không được chọn: không đụng tới state, không xuất hiện trong `episodes`.
7. Mỗi tập: log `[EP03/26] <title>` trước khi chạy; `log` truyền cho `run_dub`
   thêm tiền tố `[EP03] ` (độ rộng số = `max(2, len(str(total)))`).
8. **Chỉ bắt `DubError`** (CP7 A1/A3): ghi `failed` + `error_stage = exc.stage`
   + `error = str(exc)`, log `[EP03] LỖI ở stage <stage> — tiếp tục tập sau`.
   Không retry theo stage (CP7 A3). Exception khác (bug) để nổi lên — state
   các tập trước đã được ghi.
9. Thành công → `completed`, lưu `episode_dir`, `output_path`, `warnings` (3
   list id từ `DubResult`), `seconds = sum(result.stage_seconds.values())`.
10. **Ghi `playlist.json` sau mỗi tập** (cả completed lẫn failed), atomic.
    Ctrl+C giữa tập: tập đó giữ status cũ, lần sau chạy lại từ artifact.
11. **Dừng sớm**: đếm lỗi liên tiếp chỉ trên các tập thực sự gọi `run_dub`
    (skipped không reset, không tăng; completed reset về 0). Đạt
    `max_consecutive_failures` (> 0) → log
    `[playlist] N tập lỗi liên tiếp — dừng (kiểm tra Ollama/mạng/ffmpeg rồi chạy lại)`,
    các tập được chọn còn lại → outcome `not_run`, `aborted=True`.
12. `force=True` → không skip tập nào và truyền `force` xuống `run_dub`
    (help text phải cảnh báo: làm lại toàn bộ mọi tập, nên dùng kèm `--items`).
13. Glossary: không làm gì thêm — `run_dub` tự nạp `<ep>/glossary.yaml` +
    glossary chung (`--glossary` / `translation.glossary`) và tự in dòng nhắc
    khi thiếu glossary tập.

### CLI `_cmd_playlist`
- `--items` sai → `[playlist] LỖI: ...` ra stderr, exit 1, không fetch.
- `PlaylistError` → stderr, exit 1.
- `KeyboardInterrupt` → in `[playlist] Đã dừng (Ctrl+C). Chạy lại đúng lệnh này để tiếp tục.`, exit 130.
- Summary (stdout):
```text
[playlist] thư mục   : output/PLxxxx__Guess How Much I Love You
[playlist] 26 tập (chọn 26)
[playlist] completed 23 | skipped 2 | failed 1 | not_run 0
[playlist] LỖI  EP07 abc123 [translate] Không kết nối được Ollama ...   <- dòng đầu của error
[playlist] CẢNH BÁO EP03: 2 câu dịch lỗi (id 4, 9) — im lặng trong output
[playlist] CẢNH BÁO EP05: 1 segment thiếu audio (id 12) — chèn im lặng
```
  Cảnh báo chỉ in cho tập `completed` trong lần chạy này có
  `translate_failed_ids`/`missing_ids` khác rỗng (too_long không in).
- Exit 0 nếu không có `failed` và không `aborted`; ngược lại exit 1.

## Test (unittest, mock tiến trình/dịch vụ ngoài)
- `tests/test_youtube_playlist.py` (patch `yt_dlp.YoutubeDL`):
  opts có `extract_flat="in_playlist"`; parse entry đủ field; thiếu
  `playlist_index` → vị trí; thiếu/không-http `url` → build từ id; entry `None`/không id bị bỏ;
  trùng id giữ cái đầu; `_type="video"` → `PlaylistError`; `DownloadError` →
  `PlaylistError`; playlist rỗng → `PlaylistError`; thiếu title → `"untitled"`.
- `tests/test_pipeline_playlist.py` (patch `fetch_playlist` và `run_dub` trong
  module `app.pipeline.playlist`, `tempfile.TemporaryDirectory`):
  - lần đầu: gọi `run_dub` đúng thứ tự index, `DubOptions.workspace == playlist_dir`, state có 3 entry `completed` + `warnings`.
  - lần 2: tất cả `skipped`, `run_dub` không được gọi.
  - `completed` nhưng xoá `output_vi.mp4` → chạy lại.
  - tập 2 ném `DubError("translate", ...)` → tập 3 vẫn chạy; state tập 2 `failed`, `error_stage="translate"`; lần sau tập 2 được chạy lại.
  - `recheck=True` → gọi `run_dub` cho tập completed; `force=True` → gọi và truyền `force=True`.
  - `items={2}` → chỉ tập 2 chạy, `episodes` chỉ có tập 2, entry khác giữ nguyên status; `items={2, 99}` → log cảnh báo 99.
  - `max_consecutive_failures=2`: lỗi, lỗi → `aborted`, tập còn lại `not_run`, `run_dub` không gọi thêm; lỗi, ok, lỗi → không abort; `0` → không bao giờ abort.
  - merge: state cũ có id bị bỏ khỏi playlist + playlist có id mới → id cũ biến mất khỏi entries, id mới `pending`, status id chung giữ nguyên, title cập nhật.
  - `run_dub` ném `KeyboardInterrupt` ở tập 2 → exception nổi lên, `playlist.json` trên đĩa có tập 1 `completed`, tập 2 không phải `completed`.
  - `playlist.json` hỏng → `PlaylistError`, file không bị ghi đè.
  - `parse_item_spec`: `"1-3,5"`, `" 2 , 4-4 "`, lỗi với `""`, `"0"`, `"3-1"`, `"a"`, `"1-"`.
- `tests/test_cli.py`: `playlist` parse đủ flag; `--items` sai → exit 1, không gọi `run_playlist`; `--original-volume 1.5` → exit 1; resolve `--glossary`/`--workspace` flag > config (như test `dub`); exit 0 / 1 (có failed) / 1 (aborted) / 130 (KeyboardInterrupt); summary chứa `completed 2 | skipped 1 | failed 0`; các test `dub` cũ vẫn pass sau refactor.
- `tests/test_config.py`: default `max_consecutive_failures == 3`; `-1` và kiểu sai → `ConfigError`.

## Chạy thật (BẮT BUỘC)
Playlist thật: **user cung cấp URL** khi giao việc (playlist series mục tiêu).
Không có URL trong prompt → dừng, hỏi user; không tự chọn playlist. Dùng
`--source-lang` đúng ngôn ngữ của series. Chỉ chạy 2–3 tập bằng `--items`.

1. `.venv/Scripts/python.exe -m app playlist "<URL>" --items 1 --source-lang <lang>`
   → đạt: `playlist.json` liệt kê **đủ** số tập của playlist (so với trang
   YouTube), EP1 `completed`; mở `output_vi.mp4` của EP1 có tiếng Việt; exit 0.
2. Chạy lại y hệt → EP1 `skipped`, tổng thời gian vài giây (chỉ fetch playlist),
   không có dòng `[EP01] [dub]` nào; exit 0.
3. `OLLAMA_HOST=http://127.0.0.1:1` (PowerShell: `$env:OLLAMA_HOST=...`) rồi
   `--items 1-2` → EP1 `skipped`, EP2 `failed` ở `translate` sau khi
   download+transcribe xong; summary có dòng LỖI; exit 1. Bỏ biến môi trường.
4. Chạy lại `--items 1-2` → EP2 download/transcribe **SKIP**, dịch tiếp,
   `completed`; `playlist.json` EP2 `failed` → `completed`, `error` về `null`.
5. `--items 1 --recheck` → `run_dub` chạy, mọi stage `SKIP`, outcome completed.
6. Ctrl+C khi EP3 đang transcribe (`--items 3`) → exit 130, thông báo đúng;
   `playlist.json` vẫn parse được, EP1–2 `completed`.
7. Đọc `playlist.json` cuối: đường dẫn tương đối, không có entry `skipped`,
   `warnings` đúng với log.
Ghi số liệu (thời gian mỗi tập, số segment, too_long) vào mục D của
`docs/decisions/checkpoint-8.md`.

## Ngoài phạm vi
- Xử lý (transcribe/translate/tts/render) song song nhiều tập (plan §19: MVP
  tuần tự). Chỉ việc *tải* được chạy song song với việc xử lý (SỬA ĐỔI 1).
- Tự nạp glossary cấp playlist (`<playlist_dir>/glossary.yaml`) — người dùng
  truyền `--glossary` hoặc đặt `translation.glossary`.
- Đổi tên thư mục tập sang `001_...`, di chuyển episode đã dub bằng `dub` đơn lẻ vào thư mục playlist.
- Retry theo stage ở tầng playlist; retry yt-dlp khi fetch playlist lỗi.
- Sửa các mục `[CẦN DUYỆT]` của CP7 (C0 Whisper phân đoạn khác, C1 manifest mtime).
- `--force` từng stage (plan §17).

## Điểm phải escalate
- yt-dlp flat không trả `title`/`id` cho entry, hoặc trả URL dạng khác
  `watch?v=` làm `run_dub` fail hàng loạt ở download.
- Tên thư mục `<video_id>__<title>` khác nhau giữa các lần chạy (title đổi) →
  tập bị tải lại từ đầu. Ghi nhận, không tự đổi quy tắc đặt tên của CP1.
- Cần đổi chữ ký/hành vi `run_dub` hay bất kỳ hàm stage nào để làm CP8 —
  **ngoài** tham số `episode=` đã cho phép ở SỬA ĐỔI 1.
- `run_dub` ném exception không phải `DubError` khi chạy thật.
- Playlist chứa video private/deleted: ghi cách yt-dlp flat trả về và thông báo lỗi thực tế.

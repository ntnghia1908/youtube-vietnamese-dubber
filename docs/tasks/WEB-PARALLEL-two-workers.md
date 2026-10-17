# Task: WEB-PARALLEL — Hàng đợi web chạy song song tối đa 2 job + `whisper.cpu_threads` tự theo CPU từng máy

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 (HUMAN LEAD: "ACCEPTED nhưng thêm điều kiện phải kiểm tra CPU của từng máy") — ngoài boundary ADR-001 mục 0 (đổi D3; sửa `app/transcription/whisper.py`, `app/pipeline/dub.py` ngoài path được phép)
- Parallel group: —
- Owned paths: `app/hardware.py` (mới), `tests/test_hardware.py` (mới), `app/web/jobs.py`, `app/web/server.py`, `app/config.py`, `app/cli.py`, `app/transcription/whisper.py`, `app/pipeline/dub.py`, `config.example.yaml`, `tests/test_web_jobs.py`, `tests/test_web_cli_config.py`, `tests/test_config.py`, `tests/test_transcription_whisper.py`, `README.md`, `docs/adr/ADR-001-web-ui.md`, `docs/decisions/WEB-PARALLEL.md`
- Dependencies: WEB-1, WEB-2 (đã commit `5a5f01a`)
- Base commit / branch: 5a5f01a / main
- Human Lead approval: accepted 2026-10-17 (kèm điều kiện: giá trị mặc định tính theo CPU của từng máy — mục "Tự dò CPU")
- Implementation authorized: YES

Mã `WEB-3` đã dành cho "sửa câu dịch từng segment" (ADR-001 mục 6) nên task này đặt tên riêng như `WEB-AUTH`.

## Goal

Hàng đợi web chạy **tối đa 2 job cùng lúc** (FIFO, không bao giờ 2 job cùng ghi một thư mục), và mỗi tiến trình Whisper dùng nhiều thread CPU hơn mức ngầm ~4 của faster-whisper/CTranslate2. Cả hai giá trị mặc định là `auto`: **dò số CPU (và GPU) của máy đang chạy** rồi tính — máy Linux 32 core hiện tại ra `max_jobs=2`, `cpu_threads=12`; máy khác ra giá trị khác. Ghi đè được bằng số cụ thể trong config.

## Scope

- In scope:
  - Hàm dò phần cứng dùng chung (mục "Tự dò CPU") + in giá trị đã chọn ra log.
  - `web.max_jobs` (`"auto"` mặc định | int 1–2) + flag `app web --max-jobs N`.
  - `JobManager` chạy N worker thread; lập lịch FIFO có **tránh xung đột target**.
  - `whisper.cpu_threads` (`"auto"` mặc định | int ≥ 0, `0` = để CTranslate2 tự chọn) truyền vào `WhisperModel(cpu_threads=...)` ở cả `dub`/`playlist` và lệnh `transcribe`.
  - Sửa đổi ADR-001 (mục 10 mới), README, decision log.
- Out of scope:
  - `max_jobs` > 2, chạy song song nhiều tập *bên trong* một job playlist (đã có luồng tải song song CP8; dịch/transcribe vẫn tuần tự trong job).
  - Lock file `<episode>/.lock` chống CLI chạy tay song song với web (ADR-001 mục 7 — vẫn chỉ là rủi ro đã biết).
  - Flag CLI `--cpu-threads` cho `dub`/`transcribe` (chỉ config).
  - Đổi UI trang Jobs ngoài những gì cần để hiển thị nhiều job `running` (trang đã liệt kê theo status — kiểm, chỉ sửa nếu đang giả định một job running).

## Authority / key decisions

- HUMAN LEAD 2026-10-17 (chat): "cho hàng đợi có thể xử lý song song hai việc một lượt và tối đa là hai việc"; "mặc định là 12" thread; đã thử server chạy được 3 job Whisper song song.
- HUMAN LEAD 2026-10-17, khi duyệt: "phải kiểm tra CPU của từng máy … server này 32 core nhưng server khác có thể thay đổi nên kiểm tra trước để phù hợp với từng server" → mặc định `auto` theo phần cứng; 12 và 2 là kết quả trên máy 32 core, không phải hằng số.
- ADR-001 D3, mục 3 ("GPU dùng chung → tối đa một job"), mục 4.3 (1 worker FIFO) — bị sửa bởi task này. Lý do gốc (GPU dùng chung) không còn đúng trên máy Linux hiện tại (CPU 32 core, Ollama qua tunnel).
- ADR-001 mục 7: hai writer trên cùng episode là rủi ro → task này bắt buộc chặn ở mức web (tránh xung đột target).
- Đã kiểm: `libctranslate2` 4.x có đọc `OMP_NUM_THREADS`; faster-whisper `WhisperModel(..., cpu_threads=0)` là mặc định (≈4 thread). Đo thực tế: job đang chạy ~380% CPU, load ~4/32.

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/config.py` | `WhisperConfig.cpu_threads: int \| str = "auto"`; `_WHISPER_TYPES["cpu_threads"] = (int, str)`; validate: `"auto"` hoặc int ≥ 0 (bool, chuỗi khác, số âm → `ConfigError`). `WebConfig.max_jobs: int \| str = "auto"`; `_WEB_TYPES["max_jobs"] = (int, str)`; `validate_web_max_jobs(v)` nhận `"auto"` hoặc int 1–2 (dùng lại cho flag CLI, như `validate_web_port`). Config giữ nguyên `"auto"` — **không** resolve lúc load (resolve ở nơi dùng, mục "Tự dò CPU"). |
| `app/hardware.py` (mới, stdlib) | `cpu_count()`, `cuda_device_count()`, `resolve_whisper_cpu_threads(...)`, `resolve_web_max_jobs(...)` — mục "Tự dò CPU". |
| `config.example.yaml` | thêm `cpu_threads: auto` dưới `whisper:` và `max_jobs: auto` dưới `web:`, comment tiếng Việt ngắn (xem mục Config). |
| `app/transcription/whisper.py` | `_run_whisper(..., cpu_threads: int)` → `WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=cpu_threads)`; `transcribe_audio(..., cpu_threads: int = 0)` truyền xuống. Mặc định tham số hàm là `0` (hành vi cũ cho caller khác/test); giá trị 12 đến từ config. |
| `app/pipeline/dub.py` | truyền `cpu_threads=resolve_whisper_cpu_threads(config.whisper.cpu_threads)` vào `transcribe_audio` (dòng ~186). Chỉ resolve khi stage transcribe thật sự chạy Whisper (transcript đã có → không in gì). |
| `app/cli.py` | `_cmd_transcribe` truyền `cpu_threads=resolve_whisper_cpu_threads(config.whisper.cpu_threads)`; subparser `web` thêm `--max-jobs` (type=int, default None, help tiếng Việt "Số job chạy song song tối đa (1–2; mặc định `web.max_jobs` trong config, hoặc 2)"); `_cmd_web` lấy `args.max_jobs if not None else config.web.max_jobs`, validate (lỗi → in `[web] LỖI: ...` stderr, return 2 như port), resolve bằng `resolve_web_max_jobs(value, whisper_device=config.whisper.device)`, in một dòng stderr `[web] Hàng đợi: tối đa N job song song (<lý do>)`, truyền N vào `run(...)`. |
| `app/web/server.py` | `run(..., max_jobs: int = 1)` → `JobManager(workspace, config_path, max_jobs=max_jobs)`. Grep `_current_id`/`_current_proc` trong server/template/JS: nếu chỗ nào giả định đúng một job running thì sửa. |
| `app/web/jobs.py` | lập lịch N worker (chi tiết dưới); cập nhật docstring module (bỏ "Một worker, FIFO"). |
| `tests/test_web_jobs.py` | case mới (mục Required verification); case FIFO 1 worker cũ giữ với `max_jobs=1`. |
| `tests/test_config.py`, `tests/test_web_cli_config.py`, `tests/test_transcription_whisper.py` | case config/flag/cpu_threads. |
| `tests/test_hardware.py` (mới) | bảng resolve với `cpu`/`cuda` inject (mục "Tự dò CPU"). |
| `README.md` | mục "Web UI (local)": hàng đợi chạy tối đa `web.max_jobs` job; job trùng target chờ. Mục config Whisper: `cpu_threads`. |
| `docs/adr/ADR-001-web-ui.md` | thêm **mục 10** (văn bản mục dưới); không sửa nội dung cũ, chỉ thêm ở mục 3 và 4.3 một dòng `> Sửa đổi 2026-10-17: xem mục 10.` |
| `docs/decisions/WEB-PARALLEL.md` | decision log theo khuôn `docs/decisions/WEB-1.md`. |

Văn bản mục 10 ADR-001:

```markdown
## 10. Sửa đổi 2026-10-17 — D3: hàng đợi tối đa 2 job song song

HUMAN LEAD (2026-10-17): máy chạy thật là Linux 32 core, Whisper chạy CPU, Ollama ở máy khác — lý do "GPU dùng chung" ở mục 3 không còn đúng cho máy này nhưng vẫn đúng cho máy có GPU. Hàng đợi chạy tối đa `web.max_jobs` job cùng lúc (trần cứng 2), FIFO; job có target trùng với job đang chạy (cùng video, cùng playlist, hoặc tập nằm trong playlist đang chạy) phải chờ, không chạy song song. Mặc định `web.max_jobs` và `whisper.cpu_threads` là `auto`: tính theo CPU/GPU dò được trên **từng máy** lúc chạy (có GPU CUDA → 1 job; CPU ≥ 8 → 2 job; thread Whisper = CPU / 2, trần 12) — máy 32 core ra 2 job × 12 thread. Đặt số cụ thể để ghi đè. Task: `docs/tasks/WEB-PARALLEL-two-workers.md`.
```

### Tự dò CPU (điều kiện duyệt của HUMAN LEAD)

`app/hardware.py`, thuần stdlib (import `ctranslate2` lười trong `cuda_device_count`):

```python
WHISPER_THREADS_CAP = 12          # trên ~12 thread/tiến trình Whisper CPU tăng tốc kém
MIN_CPUS_FOR_PARALLEL = 8

def cpu_count() -> int:
    """CPU thực sự được dùng: len(os.sched_getaffinity(0)) nếu có (tôn trọng taskset/cgroup cpuset), không thì os.cpu_count(); tối thiểu 1."""

def cuda_device_count() -> int:
    """ctranslate2.get_cuda_device_count(); ImportError/lỗi bất kỳ → 0."""

def resolve_whisper_cpu_threads(value: int | str, *, cpus: int | None = None) -> int:
    """int → trả nguyên (0 = để thư viện tự chọn). "auto" → max(1, min(WHISPER_THREADS_CAP, cpus // MAX_WEB_JOBS))."""

def resolve_web_max_jobs(value: int | str, *, whisper_device: str, cpus: int | None = None,
                         cuda_devices: int | None = None) -> tuple[int, str]:
    """int → (value, "theo config"). "auto": device "cuda", hoặc "auto" mà cuda_devices > 0 → (1, "có GPU CUDA dùng chung");
    cpus < MIN_CPUS_FOR_PARALLEL → (1, f"{cpus} CPU"); còn lại → (MAX_WEB_JOBS, f"{cpus} CPU")."""
```

`cpus`/`cuda_devices` = None → gọi hàm dò; test luôn inject. Bảng kỳ vọng (test bắt buộc):

| cpus | device / cuda | `max_jobs` auto | `cpu_threads` auto |
|---|---|---|---|
| 32 | cpu / 0 | 2 | 12 |
| 16 | auto / 0 | 2 | 8 |
| 8 | auto / 0 | 2 | 4 |
| 4 | auto / 0 | 1 | 2 |
| 1 | auto / 0 | 1 | 1 |
| 32 | auto / 1 | 1 | 12 |
| 32 | cuda / 0 | 1 | 12 |

`cpu_threads` auto chia cho `MAX_WEB_JOBS` (2) cố định, không phụ thuộc web: tiến trình pipeline không biết nó chạy từ web hay CLI, nên giả định xấu nhất là 2 job song song. Ghi rõ trong decision log.

Log khi Whisper thật sự chạy (stderr hoặc log stage hiện có của `transcribe_audio`/`run_dub`, một dòng): `[transcribe] Whisper dùng 12 thread CPU (auto, 32 CPU)`; giá trị từ config: `(... theo config)`. In cả khi chạy CUDA (giá trị bị bỏ qua nhưng in cho đơn giản).

### Interface

```python
# app/config.py
MAX_WEB_JOBS = 2
def validate_web_max_jobs(value: object) -> None: ...   # ConfigError "`web.max_jobs` phải là \"auto\" hoặc số nguyên 1–2 (đang là X)."

# app/web/jobs.py
def job_targets(kind: str, request: dict[str, Any], command: list[str]) -> frozenset[str]: ...

class JobManager:
    def __init__(self, workspace, config_path, *, max_jobs: int = 1, python=..., popen=..., killpg=None,
                 cancel_grace_seconds=..., pid_alive=..., pid_is_pipeline=...) -> None: ...
```

Mặc định `max_jobs=1` ở `JobManager` để test cũ (FIFO 1 worker, AC6 WEB-1) không đổi nghĩa; giá trị 2 đến từ config qua `run()`.

`job_targets` (thuần, không đọc đĩa; test trực tiếp):

| kind | targets |
|---|---|
| `dub` | `{"video:<id>"}` — id từ `v=`, `youtu.be/<id>` hoặc `/shorts/<id>` (cùng luật parse như `validate_request`; tách thành helper `_video_id(url)` dùng chung) |
| `playlist` | `{"playlist:<list>"}` — từ query `list=` |
| `glossary` | thư mục tập = `command[4]` (`build_command` đặt ở đó). `{"video:<prefix tên thư mục tập trước "__">"}`, cộng `"playlist:<prefix tên thư mục cha trước "__">"` nếu thư mục cha **khác** workspace (tập nằm trong playlist) |

Thư mục do `build_episode_dir_name(video_id, title)` (`app/youtube/download.py:85`) đặt tên `<id>__<title>`; playlist `<list_id>__<title>/<video_id>__<title>/`. Hai job **xung đột** khi `job_targets` giao nhau khác rỗng. Bảo thủ có chủ ý: job `dub` video X và tập X trong một playlist bị coi là xung đột dù thư mục khác nhau — chấp nhận.

### Lập lịch (thay `_current_id` / `_current_proc`)

- State: `self._running: dict[str, tuple[Any | None, frozenset[str]]]` (job_id → (proc hoặc None khi chưa spawn, targets)); `self._threads: list[threading.Thread]`.
- `start()`: recovery như cũ (dọn mồ côi **mọi** job `running` trước khi bật worker), rồi bật `max_jobs` thread `job-worker-<i>`.
- `_next_queued()` (dưới `self._cond`): duyệt `self._queue` từ đầu; bỏ khỏi queue job không còn `queued` (đã hủy); chọn **job đầu tiên** có targets không giao với target của mọi job trong `_running`; gỡ nó khỏi queue, **đăng ký vào `_running` ngay trong cùng critical section** (tránh hai worker cùng lấy hai job xung đột), trả id. Không có job chạy được → `self._cond.wait(timeout=1.0)`. Job bị bỏ qua vì xung đột giữ nguyên vị trí trong queue.
- `_run_job`: sau `popen` cập nhật proc trong `_running[job_id]`; `finally` gỡ `job_id` khỏi `_running` rồi `self._cond.notify_all()` (đánh thức worker đang chờ job xung đột).
- `cancel(job_id)` running: lấy proc từ `_running.get(job_id)`; proc None (chưa spawn) → chỉ thêm `_cancel_requested`, `_run_job` đã kiểm sau spawn như cũ.
- `stop()`: set stop event, `notify_all`, kill (force) **mọi** proc trong `_running`, join mọi thread (timeout 15 s mỗi thread như cũ).
- Targets của job lấy bằng `job_targets(job["kind"], job["request"], job["command"])` — **không thêm field mới** vào job JSON (job cũ trên đĩa vẫn chạy được).

### Artifact

Không đổi schema job JSON (`<workspace>/.web/jobs/<id>.json`) hay artifact pipeline nào. `transcript.json` không đổi (số thread không ảnh hưởng nội dung đáng kể; không thêm vào metadata).

### Config

```yaml
whisper:
  cpu_threads: auto   # thread CPU cho mỗi tiến trình Whisper. auto = số CPU của máy / 2, tối đa 12 (máy 32 core → 12); 0 = để thư viện tự chọn (~4); hoặc một số cụ thể
web:
  max_jobs: auto      # job chạy song song tối đa trên Web UI (1–2). auto = 1 nếu có GPU CUDA (dùng chung) hoặc máy < 8 CPU, còn lại 2
```

Flag: `app web --max-jobs N` ghi đè `web.max_jobs` (chỉ nhận số 1–2; muốn auto thì bỏ flag). `config.yaml` local (gitignore) **không** sửa.

### Hành vi bắt buộc

- `max_jobs=1`: hành vi y hệt hiện tại (test WEB-1 AC6 vẫn PASS không sửa assertion).
- Không bao giờ quá `max_jobs` subprocess cùng lúc, kể cả sau recovery khi có nhiều job `queued`.
- Job xung đột không bao giờ chạy song song; job không xung đột phía sau nó được vượt lên (không chặn đầu hàng).
- Retry job (tạo job mới cùng request) đi qua cùng luật xung đột.
- `cpu_threads` bool/âm/chuỗi khác `"auto"` → `ConfigError` tiếng Việt khi load config.
- Dò CPU chạy lúc dùng (start `web`, lúc Whisper chạy), không lúc load config; dò lỗi không bao giờ làm hỏng lệnh (fallback 1 CPU / 0 GPU).

### Điểm phải escalate

- Template/JS trang Jobs/Job giả định chỉ một job `running` theo cách cần đổi UI đáng kể.
- Phát hiện `faster_whisper.WhisperModel` của bản đang ghim không nhận `cpu_threads`.
- Cần thêm field vào job JSON hoặc đổi API JSON (`/api/jobs`).

## Acceptance Criteria

1. `max_jobs=2`: hai job không xung đột submit liên tiếp → cả hai `running` cùng lúc; job thứ ba `queued` tới khi một trong hai xong.
2. Hai job cùng target (2 job playlist cùng `list=`, hoặc glossary của một tập trong playlist đang chạy) → job sau `queued` tới khi job trước kết thúc; một job không xung đột submit sau nó vẫn được chạy trước.
3. `max_jobs=1` → FIFO một worker như WEB-1 (không bao giờ hai subprocess).
4. Hủy job running khi có 2 job running chỉ dừng đúng job đó; `stop()` dừng cả hai; recovery dọn mọi pipeline mồ côi rồi mới chạy queued, tôn trọng `max_jobs`.
5. `web.max_jobs` mặc định `"auto"`; `1`, `2`, `"auto"` hợp lệ; 0, 3, `"2"`, `true` → `ConfigError`; `--max-jobs 3` → `app web` thoát mã 2 với thông báo lỗi tiếng Việt.
6. `whisper.cpu_threads` mặc định `"auto"`, đi tới `WhisperModel(cpu_threads=<giá trị đã resolve>)` qua cả `run_dub` và lệnh `transcribe`; `0` và số dương hợp lệ; âm/bool/chuỗi khác → `ConfigError`.
8. `auto` tính theo phần cứng dò được, khớp bảng ở mục "Tự dò CPU"; `app web` in số job đã chọn kèm lý do, Whisper in số thread đã chọn. Trên máy 32 core hiện tại: `max_jobs=2`, `cpu_threads=12`.
7. ADR-001 có mục 10; README và `config.example.yaml` mô tả hai key mới.

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS. Case mới:
  - `tests/test_web_jobs.py`: `job_targets` cho dub (`v=`, `youtu.be`, `shorts`), playlist, glossary (tập lẻ / tập trong playlist); 2 worker chạy 2 job song song với `popen` giả chặn bằng `threading.Event` (AC1); job thứ 3 chờ (AC1); xung đột chờ + job không xung đột vượt lên (AC2); `max_jobs=1` (AC3); cancel một trong hai, `stop()` kill cả hai, recovery + queued với `max_jobs=2` (AC4). Mọi test có timeout, không sleep dài.
  - `tests/test_hardware.py`: toàn bộ bảng "Tự dò CPU" (inject `cpus`/`cuda_devices`); `cpu_count()` fallback khi không có `sched_getaffinity`; `cuda_device_count()` trả 0 khi import lỗi (AC8).
  - `tests/test_config.py` (AC5, AC6 phần config), `tests/test_web_cli_config.py` (`--max-jobs`, ghi đè config, lỗi → mã 2), `tests/test_transcription_whisper.py` (`cpu_threads` tới `_run_whisper`; patch `faster_whisper.WhisperModel` để kiểm kwarg).
- **Chạy thật** (sau khi hai job đang chạy trên server LAN đã xong — restart server sẽ làm job đang chạy thành `interrupted`):
  0. `$PY -c "from app.hardware import *; print(cpu_count(), cuda_device_count(), resolve_web_max_jobs('auto', whisper_device='auto'), resolve_whisper_cpu_threads('auto'))"` → máy này `32 0 (2, '32 CPU') 12` (AC8).
  1. Restart server: `pkill -f "app web --workspace output"; . ~/.config/dubber/web.env && setsid nohup .venv/bin/python -m app web --workspace output --host 10.8.102.102 > output/.web/server.log 2>&1 &`.
  2. Submit qua `POST /api/jobs` (có cookie đăng nhập) hai job không xung đột: video ngắn `https://www.youtube.com/watch?v=fcfQkxwz4Oo` với `force=true`, và playlist Ocean Girl `PLllZo-pkRkaEhoPJ6mM1DdIV94fifKPsn` `items=3` → `GET /api/jobs` thấy **2 job `running`**; `ps` thấy 2 tiến trình `app dub|playlist`; trong lúc job nào đang ở stage transcribe, `ps -o pcpu,nlwp` tiến trình đó > ~800% CPU (chứng minh 12 thread, AC6).
  3. Submit thêm job playlist Ocean Girl `items=4` trong khi `items=3` đang chạy → `queued` tới khi `items=3` xong (AC2).
  4. Hủy job video ngắn khi đang running → chỉ nó `cancelled`, job playlist vẫn `running` (AC4).
  5. Ghi lệnh, `GET /api/jobs` trích đoạn và `ps` vào decision log.

## Manual test checklist (Tech Lead)

- Không chạm database / security model / public API. Không đổi schema job JSON hay API JSON.
- [ ] Trên trang Jobs thấy hai job `running` cùng lúc, log trực tiếp của từng job đúng job đó.
- [ ] Submit hai job cùng playlist → job sau chờ.
- [ ] Không đổi âm thanh/video output — không cần nghe lại.
- [ ] Trên máy khác (vd Windows có GPU), `server.log` dòng `[web] Hàng đợi:` ra 1 job (có GPU CUDA).

## Result

- Main changes: `app/hardware.py` mới (dò CPU qua `sched_getaffinity`, GPU qua `ctranslate2`; resolve `auto`); `whisper.cpu_threads` + `web.max_jobs` mặc định `"auto"` (`app/config.py`, `config.example.yaml`); `cpu_threads` tới `WhisperModel` qua `run_dub` và lệnh `transcribe`, log số thread khi Whisper thật sự chạy; `JobManager` N worker với `job_targets` tránh xung đột (job sau vượt lên), `cancel`/`stop` theo `_running`; `app web --max-jobs`, in `[web] Hàng đợi: ...`; ADR-001 mục 10; README; decision log `docs/decisions/WEB-PARALLEL.md`.
- Tests: `Ran 566 tests ... OK` (ORCHESTRATOR chạy lại); mới `tests/test_hardware.py` + case trong `test_web_jobs.py`, `test_config.py`, `test_web_cli_config.py`, `test_transcription_whisper.py`. `framework-check` PASS.
- Review: một vòng, không blocking. ORCHESTRATOR sửa field `Change class` (checker) và dòng `12`/`2` sót trong bảng file (B5 → `auto`).
- Important findings / decisions: chạy thật ở decision log mục C — 2 job `running` song song, job cùng playlist `queued`, hủy một job không ảnh hưởng job kia, Whisper ~956% CPU so với ~380% trước đây.
- Known limitations: `cpu_threads` auto chia cố định cho 2 (giả định xấu nhất), kể cả khi chạy CLI một mình; `dub` video X và tập X trong playlist coi là xung đột (bảo thủ); CLI chạy tay song song với web vẫn không có lock (ADR-001 mục 7).
- PR: — (commit trên `main`, chờ HUMAN LEAD)

# Task: CP9-C — Lệnh/job `playlist` xử lý 2 tập song song

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17
- Parallel group: —
- Owned paths: `app/pipeline/playlist.py`, `app/config.py`, `app/hardware.py`, `app/cli.py`, `app/web/jobs.py`, `app/web/server.py`, `config.example.yaml`, `docs/SETUP.md` (mục A4, đoạn "Dòng cuối chỉ có lợi…"), `docs/decisions/checkpoint-9.md` (mục CP9-C mới), `tests/test_playlist*.py`, `tests/test_config*.py`, `tests/test_hardware*.py`, `tests/test_cli*.py`, `tests/test_web_jobs*.py`
- Dependencies: CP8, WEB-PARALLEL, WEB-PARALLEL-PLAYLIST (đã xong)
- Base commit / branch: cc028bb / main
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

## Goal

Một lệnh `python -m app playlist ...` (CLI, job playlist trên web, nút "Dịch lại các tập cũ") chạy `run_dub` cho **tối đa 2 tập cùng lúc** thay vì lần lượt. Với Ollama đặt `OLLAMA_NUM_PARALLEL=2`, hai tập gửi request dịch song song (đo trên RTX 3050: 1,33× thông lượng dịch, `docs/SETUP.md` A4); transcribe/TTS/render của hai tập cũng chồng lên nhau. Trên web, tổng số `run_dub` chạy đồng thời vẫn ≤ `max_jobs` (≤ 2).

## Scope

- In scope:
  - `pipeline.episode_workers` (`auto` | 1–2) + flag `playlist --episode-workers N|auto`.
  - `run_playlist` chạy pool tối đa N tập; luồng tải giữ nguyên (tuần tự, đi trước).
  - Hàng đợi web tính theo **slot**: job playlist chiếm tối đa 2 slot (= số worker tập nó được giao), tổng slot ≤ `max_jobs`; web luôn truyền `--episode-workers` tường minh.
  - Cập nhật đoạn cuối SETUP A4 (giờ code đã gửi 2 request song song → nên đặt `OLLAMA_NUM_PARALLEL=2`).
- Out of scope:
  - Song song trong MỘT tập (các batch dịch phụ thuộc ngữ cảnh batch trước — `context_for` ở `app/translation/translate.py:382`).
  - Lập lịch theo stage (vd chỉ cho 2 tập cùng ở bước dịch). Không semaphore/giới hạn chung cho TTS giữa hai tập (xem Điểm phải escalate).
  - Hơn 2 worker; đổi `MAX_WEB_JOBS`; đổi lệnh `dub`.
  - Hiển thị tiến độ nhiều tập trên web (`progress` vẫn là dòng tiến độ cuối cùng — sẽ nhảy qua lại giữa hai tập; ghi Known limitation).
  - Đặt `OLLAMA_NUM_PARALLEL` trên server Ollama (HUMAN LEAD làm).

## Authority / key decisions

- S2 vì đổi mô hình chạy của `playlist` (CP8 chốt "xử lý tuần tự, chỉ tải song song", `docs/decisions/checkpoint-8.md` dòng ~319) và luật xếp lịch của hàng đợi web.

- HUMAN LEAD 2026-10-17 (AskUserQuestion khi `/spec`): chọn hướng "run_playlist 2 tập", không phải "chỉ song song bước dịch" hay "chỉ tài liệu"; HUMAN LEAD sẽ đặt `OLLAMA_NUM_PARALLEL=2` cho Ollama đang dùng, nhưng **để sau** (HUMAN LEAD 2026-10-17): chạy thật của task chỉ kiểm tính đúng; số đo tốc độ dịch song song chuyển sang Manual test checklist.
- Quyết định này thay thế giới hạn "xử lý tuần tự" của CP8 (`docs/decisions/checkpoint-8.md` mục A/"chưa làm") và docstring module `app/pipeline/playlist.py`. Mọi điều khác của CP8 mục A (khoá resume `video_id`, ghi `playlist.json` sau mỗi tập, lỗi tải không tính vào lỗi liên tiếp) giữ nguyên.
- WEB-PARALLEL B1: Whisper `cpu_threads: auto` chia cho `MAX_WEB_JOBS` (2) vì giả định xấu nhất là 2 pipeline song song. Task này phải giữ giả định đó đúng: **mỗi lần chạy CLI ≤ 2 `run_dub` đồng thời; toàn web ≤ `max_jobs` `run_dub` đồng thời.**
- WEB-PARALLEL-PLAYLIST mục A: `_persist_entry` (file lock) là đường ghi `playlist.json` duy nhất; thứ tự khoá `entries_lock` rồi file lock. Không đổi.

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/config.py` | `PipelineConfig.episode_workers: int \| str = "auto"`; nạp từ YAML; `validate_episode_workers(value)` cùng luật với `validate_web_max_jobs` (`"auto"` hoặc int 1–`MAX_WEB_JOBS`, bool bị từ chối) — tách helper chung nếu gọn, không đổi chữ ký `validate_web_max_jobs`. |
| `app/hardware.py` | `resolve_episode_workers(...)` (Interface). Dùng chung logic với `resolve_web_max_jobs` (tách hàm nội bộ), không đổi hành vi/chữ ký của hàm cũ. |
| `app/pipeline/playlist.py` | `PlaylistOptions.episode_workers: int = 1`; vòng xử lý chạy pool; cập nhật docstring module + `run_playlist`. |
| `app/cli.py` | Flag `--episode-workers` cho `playlist`; resolve + log; `_cmd_web` resolve `episode_workers` của config và truyền xuống `server.run`. |
| `app/web/jobs.py` | Slot (Interface); chèn `--episode-workers N` vào command lúc dispatch. |
| `app/web/server.py` | `run(..., episode_workers: int = 1)` (keyword) → `JobManager(..., episode_workers=...)`. |
| `config.example.yaml` | Key mới dưới `pipeline:` (mục Config). |
| `docs/SETUP.md` | A4: thay câu "pipeline hiện tại dịch tuần tự, **đừng** đặt `OLLAMA_NUM_PARALLEL`" bằng hướng dẫn đặt `OLLAMA_NUM_PARALLEL=2` khi `episode_workers` = 2 (Linux: biến môi trường của service `ollama`; Windows: như lệnh `FLASH_ATTENTION` ngay trên). |
| `docs/decisions/checkpoint-9.md` | Mục `## CP9-C — …` (A. Contract, B. Quyết định nhỏ, C. Số đo). |

### Interface

```python
# app/hardware.py
def resolve_episode_workers(
    value: int | str, *, whisper_device: str,
    cpus: int | None = None, cuda_devices: int | None = None,
) -> tuple[int, str]:
    """``auto``: cùng luật với resolve_web_max_jobs (GPU CUDA dùng chung hoặc < 8 CPU -> 1, còn lại 2)."""

# app/pipeline/playlist.py
@dataclass(frozen=True)  # giữ đúng decorator hiện có của PlaylistOptions
class PlaylistOptions:
    ...
    episode_workers: int = 1  # 1 = hành vi tuần tự cũ; trần MAX_WEB_JOBS

# app/web/jobs.py
class JobManager:
    def __init__(..., max_jobs: int = 1, episode_workers: int = 1, ...): ...
    # _running: job_id -> (proc | None, targets, slots)
```

Tái sử dụng: `MAX_WEB_JOBS` (`app/config.py:29`), `cpu_count`/`cuda_device_count` (`app/hardware.py`), `parse_item_spec` (`app/pipeline/playlist.py:116`), `_persist_entry`, `targets_conflict`.

### `run_playlist` — hành vi

- `episode_workers == 1`: đường chạy **giống hệt hiện tại** (vòng `for` trên luồng gọi). Test cũ không được sửa kỳ vọng.
- `episode_workers == 2`: N luồng worker (`threading.Thread`, daemon) lấy tập theo **thứ tự `selected_indexes`** từ một hàng chung (có lock). Mỗi worker làm đúng thân vòng `for` hiện tại cho một tập (skip / chờ `download_events[idx]` theo nhịp 0,5 s / `download_only` / `run_dub` / ghi kết quả qua `entries_lock` + `_persist_entry`).
  - Tách thân vòng thành một hàm `_process_one(idx) -> EpisodeOutcome` dùng chung cho cả hai đường để không nhân đôi logic.
  - Luồng gọi (main thread) chờ các worker bằng `join(timeout=0.5)` lặp lại — để Ctrl+C vẫn ngắt được ngay (cùng lý do với vòng chờ download hiện tại). Khi `KeyboardInterrupt`: set cờ dừng, set `stop_download`, raise lại (CLI đã xử lý → exit; worker daemon chết theo tiến trình; artifact atomic nên resume được).
  - `episodes` của `PlaylistResult` **sắp theo `index`** (worker xong không theo thứ tự).
  - `consecutive_failures` / `aborted`: cập nhật dưới lock, theo thứ tự *hoàn thành*. Khi `aborted`: worker không nhận tập mới; tập đang chạy dở được chạy hết (không hủy giữa chừng); tập chưa nhận → `not_run`.
  - Exception không phải `DubError` trong worker (bug, lỗi lạ ở luồng tải được raise lại): lưu lại, dừng nhận tập mới, main thread raise lại sau khi join — không được nuốt.
  - Không bao giờ có 2 worker cùng xử lý một `idx`.
- Log: mọi dòng của tập đã có tiền tố `[EPxx]` (`_ep_log`). Thêm một dòng đầu khi N = 2: `[playlist] xử lý song song 2 tập (<lý do>)`. `log` được gọi từ nhiều luồng — mỗi lời gọi in một dòng trọn vẹn (print + flush), không cần lock thêm.

### CLI

- `playlist --episode-workers N|auto` (mặc định: `pipeline.episode_workers`). Giá trị sai → `[playlist] LỖI: ...`, exit 2 trước khi chạm mạng (giống `--items` sai).
- Resolve bằng `resolve_episode_workers(value, whisper_device=config.whisper.device)`; khi `download_only` thì log/pool không quan trọng nhưng vẫn hợp lệ.
- `_cmd_web`: resolve `pipeline.episode_workers` của config, `episode_workers = min(kết quả, max_jobs)`, log `[web] Job playlist: tối đa <n> tập song song (<lý do>)`, truyền `episode_workers=` (keyword) cho `server.run`.

### Web — slot

- Mỗi job chiếm `slots` ≥ 1; tổng `slots` của `_running` ≤ `max_jobs`.
  - `dub`, `glossary`: 1 slot.
  - `playlist`: `min(episode_workers, free_slots, n_items)` với `free_slots = max_jobs - tổng slots đang chạy` lúc dispatch và `n_items = len(parse_item_spec(items))` nếu request có `items` (spec lỗi → coi như không biết), không có `items` → không giới hạn. Tối thiểu 1.
- `_next_queued`: chỉ dispatch khi `free_slots >= 1` (giữ FIFO + vượt lên khi xung đột target như hiện tại). Không bao giờ chờ đủ 2 slot — job playlist gặp lúc chỉ còn 1 slot chạy với 1 worker (tránh đói).
- Lúc dispatch job playlist: thêm `["--episode-workers", str(slots)]` vào `job["command"]` và ghi job JSON **trước** `_popen` (để log/UI thấy đúng lệnh đã chạy). Job dub/glossary không thêm flag. `build_command` không đổi; `retry` dựng lại command từ request nên không mang flag cũ.
- Worker thread vẫn là `max_jobs` luồng; luồng thừa khi một job chiếm 2 slot thì chờ trên `_cond` như khi gặp xung đột (được `notify_all` ở `_unregister`).
- Mặc định `JobManager(episode_workers=1)`: hành vi web cũ (mọi job 1 slot, playlist chạy `--episode-workers 1`).

### Artifact

- `playlist.json`: **không đổi schema**. Hai worker cùng ghi qua `_persist_entry` (đã khoá).
- Job JSON (`output/.web/jobs/<id>.json`): không thêm field; `command` của job playlist có thêm `--episode-workers N`.
- Thư mục tập, `translated.json`, … : không đổi.

### Config

```yaml
pipeline:
  episode_workers: auto   # `playlist`: số tập xử lý song song (1–2). auto = 1 nếu có GPU CUDA (dùng chung) hoặc máy < 8 CPU, còn lại 2. Dịch song song cần Ollama đặt OLLAMA_NUM_PARALLEL=2 (docs/SETUP.md A4)
```

Flag: `playlist --episode-workers`. Không có flag cho `dub`/`web` (web lấy từ config).

### Điểm phải escalate

- **TTS**: hai tập cùng TTS = `2 × tts.concurrency` kết nối edge-tts. Nếu chạy thật thấy tỉ lệ câu TTS lỗi vĩnh viễn tăng (nợ F1 `docs/decisions/checkpoint-8.md`) → DỪNG, báo số liệu, không tự thêm semaphore.
- Thấy cần đổi chữ ký `run_dub`, schema `playlist.json`, format job JSON, hoặc luật `targets_conflict`.
- `run_dub` hoặc stage nào đó dùng state toàn cục không an toàn khi chạy 2 luồng trong cùng tiến trình (đã grep sơ bộ: `asyncio.run` mỗi lần gọi ở `app/tts/edge.py:39`, `lru_cache` ở `app/translation/glossary.py:59` — cả hai an toàn; nếu thấy chỗ khác → báo).
- Bộ nhớ: hai model Whisper nạp cùng lúc trong một tiến trình. Nếu chạy thật OOM/swap nặng → báo.

## Acceptance Criteria

1. `pipeline.episode_workers` nhận `auto`/1/2, từ chối 0, 3, `true`, chuỗi khác; `auto` resolve theo luật trên (GPU hoặc < 8 CPU → 1, còn lại 2). Flag `--episode-workers` ghi đè config; giá trị sai exit 2 không chạm mạng.
2. `episode_workers=1`: hành vi và log của `run_playlist` y như trước (toàn bộ test playlist cũ PASS không sửa kỳ vọng).
3. `episode_workers=2`: hai `run_dub` chạy chồng thời gian; không tập nào xử lý hai lần; `PlaylistResult.episodes` sắp theo index; `playlist.json` có đủ kết quả của cả hai tập (không mất update).
4. `episode_workers=2`: lỗi `DubError` một tập không chặn tập kia; `max_consecutive_failures` vẫn dừng nhận tập mới, tập còn lại → `not_run`; exception lạ được raise lại ở luồng gọi.
5. Web: tổng slot của job đang chạy không bao giờ vượt `max_jobs`; job playlist chạy khi trống 2 slot thì nhận `--episode-workers 2`, khi trống 1 slot thì `--episode-workers 1`; job playlist `items` một tập → 1 slot; job dub/glossary 1 slot; `JobManager` mặc định (`episode_workers=1`) giữ hành vi cũ.
6. Chạy thật: hai tập Ocean Girl xử lý song song ra `output_vi.mp4` hợp lệ; chạy lần 2 SKIP cả hai; wall time của lần chạy và stage_seconds từng tập ghi ở `checkpoint-9.md` mục C (không có chỉ tiêu tốc độ — Ollama chưa đặt `OLLAMA_NUM_PARALLEL`).
7. `config.example.yaml`, `docs/SETUP.md` A4, docstring `app/pipeline/playlist.py` mô tả đúng hành vi mới.

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS. Case mới (đặt vào file test sẵn có tương ứng):
  - config: parse/validate `episode_workers` (AC1).
  - hardware: `resolve_episode_workers` với `cpus`/`cuda_devices`/`whisper_device` giả (AC1).
  - cli: `playlist --episode-workers 3` exit 2, `fetch_playlist` không bị gọi; flag truyền vào `PlaylistOptions` (AC1).
  - playlist: `run_dub` giả chờ trên `threading.Barrier(2, timeout=5)` → chỉ pass nếu hai tập thật sự chạy cùng lúc (AC3); thứ tự `episodes`; mỗi idx gọi `run_dub` đúng một lần; `playlist.json` cuối có cả hai `completed`; tập lỗi + `max_consecutive_failures=1` → `not_run` (AC4); `run_dub` giả raise `RuntimeError` → `run_playlist` raise (AC4).
  - web jobs: `max_jobs=2, episode_workers=2` — playlist một mình → command có `--episode-workers 2`, job dub xếp sau phải chờ tới khi playlist xong; dub đang chạy rồi submit playlist → `--episode-workers 1`, chạy ngay; `items="5"` → 1 slot; mặc định `episode_workers=1` không chèn giá trị khác 1 (AC5).
- **Chạy thật** (máy Linux, Ollama `127.0.0.1:11437` **chưa** đặt `OLLAMA_NUM_PARALLEL=2` — request dịch của hai tập bị Ollama xếp hàng, đó là bình thường; ORCHESTRATOR kiểm không có job web nào `queued`/`running` trên playlist Ocean Girl):
  1. (bỏ — đo tốc độ để sau, xem Manual test checklist.)
  2. `$PY -m app playlist "https://www.youtube.com/playlist?list=PLllZo-pkRkaEhoPJ6mM1DdIV94fifKPsn" --items 5,6 --episode-workers 2 --workspace output` (Episode 04, 05 — đã tải, chưa xử lý). Log phải có dòng `[playlist] xử lý song song 2 tập`, các dòng `[EP05] …` và `[EP06] …` xen nhau, có đoạn hai tập cùng chạy (vd một tập transcribe trong lúc tập kia translate, hoặc cả hai translate).
  3. Mở artifact: `playlist.json` entry 5, 6 `completed`, có `output_path`, `warnings`; mỗi tập `ffprobe output_vi.mp4` đúng 1 video + 1 `aac`, độ dài ≈ `source.mp4`; `translated.json` không có câu rỗng ngoài `translate_failed_ids`; so số câu TTS lỗi (`missing_ids`) với Episode 01–03 (escalate nếu tăng rõ).
  4. Ghi wall time cả lệnh và `stage_seconds` từng tập vào `checkpoint-9.md` CP9-C mục C (tham khảo, không phải tiêu chí PASS).
  5. Chạy lại đúng lệnh bước 2 → cả hai `skipped`, không gọi Ollama/edge-tts.
  6. Web: restart server (theo cách đã ghi ở memory: kill đúng PID, không `pkill -f`), log server có dòng `[web] Job playlist: tối đa 2 tập song song`; xếp job playlist Ocean Girl `items=7` (Episode 06) → job JSON command có `--episode-workers 1` (một tập). Không cần chạy hết job đó nếu tốn thời gian — hủy được, ghi lại.

## Manual test checklist (Tech Lead)

- Không chạm database / security model / public API. Job JSON và API JSON không đổi format.
- [ ] HUMAN LEAD nghe thử `output_vi.mp4` của Episode 04 hoặc 05 (chất lượng không đổi so với chạy tuần tự — task không đổi dịch/TTS/mix).
- [ ] HUMAN LEAD bấm "Dịch lại các tập cũ" ở glossary playlist Ocean Girl khi web rảnh → log job thấy hai tập chạy xen nhau.
- [ ] HUMAN LEAD (khi rảnh) đặt `OLLAMA_NUM_PARALLEL=2` cho Ollama `127.0.0.1:11437`, restart, chạy playlist 2 tập mới với `--episode-workers 2` và so giây/batch dịch với Episode 03 (tuần tự, `qwen3:14b`).
- [ ] (Máy Windows GPU) đặt `pipeline.episode_workers: 2` + `OLLAMA_NUM_PARALLEL=2`, so thời gian với số đo SETUP A4.

## Result

- Main changes: `pipeline.episode_workers` (auto|1–2) + `playlist --episode-workers`; `run_playlist` tách `_process_one`, pool 2 luồng `_run_pool`, `episodes` sắp theo index; `resolve_episode_workers` dùng chung luật auto với `web.max_jobs`; hàng đợi web tính slot, job playlist nhận `--episode-workers N` lúc dispatch; SETUP A4 hướng dẫn `OLLAMA_NUM_PARALLEL=2`.
- Tests: 617 PASS (ORCHESTRATOR chạy lại). Case mới: test_config, test_hardware, test_cli, test_pipeline_playlist `TestEpisodeWorkers` (Barrier 2 luồng), test_web_jobs `TestEpisodeSlots`.
- Review: ORCHESTRATOR 2026-10-17 — diff `app/` đạt contract, không blocking. Tự kiểm: playlist.json entry 5, 6 `completed`, `missing_ids`/`translate_failed_ids` rỗng; ffprobe h264 + aac, 1486,64/1486,73 s và 1466,72/1466,78 s.
- Important findings / decisions: chạy thật 2 tập (Episode 04 + 05) wall 41m38s, xen nhau ở mọi stage, lần 2 SKIP 1,3 s; web restart, job `items=7` nhận `--episode-workers 1`. `[CẦN DUYỆT]` thread Whisper 2 × (CPU // 2): ĐÃ DUYỆT — auto chỉ cho 2 tập khi ≥ 8 CPU nên tổng thread ≤ số CPU. Lệch contract nhỏ (log song song do CLI in; sửa lambda ở `tests/test_web_cli_config.py`; thoát `not_run` khi luồng tải đã dừng) — chấp nhận, ghi `checkpoint-9.md` CP9-C B.
- Known limitations:
  - Tiến độ job web chỉ hiện dòng tiến độ cuối cùng, nhảy qua lại giữa hai tập.
  - Chưa đo lợi ích dịch song song: Ollama chưa đặt `OLLAMA_NUM_PARALLEL=2` (Manual test checklist).
- PR: — (commit thẳng main)

# WEB-PARALLEL — Các quyết định nhỏ khi triển khai

Task: `docs/tasks/WEB-PARALLEL-two-workers.md`. Mục **[CẦN DUYỆT]** là chỗ Opus nên xem lại.

---

## A. Contract với task sau

- Job JSON và API JSON **không đổi**. Targets tính từ `kind/request/command` bằng `app.web.jobs.job_targets(kind, request, command, *, workspace=None)`.
- `JobManager(..., max_jobs=1)`; `server.run(..., max_jobs=1)`; `cli._cmd_web` truyền `max_jobs` là tham số vị trí thứ 7 của `run` (test cũ giả `run` bằng `lambda *a`).
- `app/hardware.py`: `cpu_count`, `cuda_device_count`, `resolve_whisper_cpu_threads`, `resolve_web_max_jobs`. Config giữ `"auto"`, resolve ở nơi dùng.
- `transcribe_audio(..., cpu_threads=0)`; `0` = hành vi cũ của CTranslate2.

## B. Quyết định

- B1. `cpu_threads` auto chia cố định cho `MAX_WEB_JOBS` (2), không phụ thuộc web: pipeline không biết nó chạy từ web hay CLI nên giả định xấu nhất là 2 job song song.
- B2. `job_targets` nhận thêm tham số tùy chọn `workspace` (keyword): có thì "tập nằm trong playlist" = thư mục cha khác workspace (đúng như contract); không có thì suy từ tên thư mục cha chứa `__`. `JobManager` luôn truyền workspace.
- B3. Gỡ job khỏi `_running` ở `finally` của `_worker_loop`, sau khi `_finish` đã ghi trạng thái cuối, để job xung đột đang chờ không chạy khi job trước còn ghi dở.
- B4. Log `[transcribe] Whisper dùng N thread CPU (...)` chỉ in khi Whisper thật sự chạy (transcript chưa có hoặc `--force`); `run_dub` in qua `log`, lệnh `transcribe` in stderr.
- B5. [ĐÃ DUYỆT — ORCHESTRATOR 2026-10-17: `auto` đúng; dòng `12`/`2` ở bảng file là sót lại từ bản contract trước khi HUMAN LEAD thêm điều kiện dò CPU] `config.example.yaml` dùng `cpu_threads: auto` / `max_jobs: auto` (mục Config của contract) thay vì `12` / `2` ghi ở bảng file cần sửa — hai chỗ contract mâu thuẫn; chọn `auto` vì khớp mặc định và điều kiện "dò theo từng máy".
- B6. Đã grep `server.py`, template, static: không chỗ nào giả định đúng một job `running`; không sửa UI.

## C. Chạy thật

ORCHESTRATOR, 2026-10-17, máy Linux 32 CPU / 0 GPU, server LAN `10.8.102.102:8081`. HUMAN LEAD cho restart ngay khi job Ocean Girl `20261017-093728-006451` đang transcribe → job đó `interrupted` (đúng recovery), chạy lại bằng retry.

- Bước 0: `32 0 (2, '32 CPU') 12` (AC8).
- Bước 1: `server.log` có `[web] Hàng đợi: tối đa 2 job song song (32 CPU)`.
- Bước 2 (AC1): retry Ocean Girl `items=2` (`20261017-101751-00b33d`) + `dub fcfQkxwz4Oo --force` (`20261017-101751-01ea0d`) → `GET /api/jobs` cả hai `running`; `ps` thấy 2 tiến trình `app playlist` + `app dub`. Log cả hai: `[transcribe] Whisper dùng 12 thread CPU (auto, 32 CPU)`. `top -d 5` lúc cả hai cùng transcribe: 955.7% và 689.4% CPU (trước WEB-PARALLEL: ~380%) (AC6).
- Bước 3 (AC2): `playlist PLllZo… items=3` (`20261017-101755-003671`) → `queued` trong khi `items=2` cùng playlist đang chạy, kể cả sau khi job dub bị hủy (còn trống 1 slot) — xung đột target giữ nó lại.
- Bước 4 (AC4): hủy job dub khi đang transcribe → `cancelled`, `exit_code -15`, tiến trình `app dub` biến mất; job playlist vẫn `running`.
- Khác contract: dùng `items=2` (job đang dở) làm job xung đột thay cho `items=3`/`items=4`; ý nghĩa kiểm như nhau.

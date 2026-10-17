# Project Profile — YouTube Vietnamese Dubber

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Project stage | MVP CLI xong tới CP8; đang làm Web UI local (ADR-001 ACCEPTED, WEB-1..3), sau đó CP9 (quality) |

Canonical owner cho: project là gì, authority order, module map, project policy (gồm luật bắt buộc), integration mechanism, execution profile được phép, setup và Test policy.

## 1. Project

Công cụ CLI chạy local, tạo bản thuyết minh tiếng Việt cho video/playlist YouTube: tải → STT → dịch → TTS → mix/render. Ưu tiên chạy local, chi phí thấp.

- Ngoài phạm vi (theo `docs/IMPLEMENTATION_PLAN.md` §5): voice cloning, lip sync, database, Docker, distributed processing, tự upload lại YouTube, realtime dubbing. Web UI local: `docs/adr/ADR-001-web-ui.md` (ACCEPTED 2026-10-17).
- Chỉ xử lý nội dung người dùng có quyền sử dụng; project không nhằm tái phát hành nội dung có bản quyền.
- Tham chiếu ngoài (tài liệu yt-dlp, Ollama, edge-tts…) KHÔNG phải source of truth.

## 2. Authority order

1. Quyết định của HUMAN LEAD / task contract đã duyệt (`docs/tasks/`) / decision record ACCEPTED (`docs/adr/`).
2. `docs/ai/workflow.md`, `docs/ai/execution-profiles.md` và file này.
3. `docs/IMPLEMENTATION_PLAN.md` (kiến trúc + lộ trình gốc; phần nào mâu thuẫn với mục 1–2 thì mục 1–2 thắng).
4. Source code và tests hiện hành.
5. Mục A (Contract) trong `docs/decisions/checkpoint-N.md` — contract artifact giữa các checkpoint; mục `[CẦN DUYỆT]` chưa phải quyết định.
6. `docs/workflow/current-state.md` chỉ là operational state, không phải authority.
7. `README.md`, `docs/SETUP.md` chỉ mô tả / onboarding.

Lịch sử, không phải authority hiện hành: `docs/specs/cp-*.md` (spec cũ trước adoption).

## 3. Module map

| Path | Vai trò | Trạng thái | Rule riêng |
|---|---|---|---|
| `app/cli.py`, `app/config.py` | CLI argparse, config (flag CLI > `config.yaml` > mặc định) | implemented | §4 "Không hard-code" |
| `app/youtube/` | yt-dlp: tải video, đọc playlist | implemented (CP1, CP8) | |
| `app/transcription/` | faster-whisper | implemented (CP2) | |
| `app/translation/` | dịch qua Ollama, glossary | implemented (CP3, CP6.5) | |
| `app/tts/` | edge-tts, cache theo segment (`tts/manifest.json`) | implemented (CP4) | |
| `app/synchronization/` | đo/co giãn timing, `normalized.json` | implemented (CP5) | |
| `app/audio/` | voice track, mix, render `output_vi.mp4` | implemented (CP6) | |
| `app/pipeline/` | `run_dub` (CP7), `run_playlist` + `playlist.json` (CP8) | implemented | contract: `docs/decisions/checkpoint-8.md` mục A |
| `app/web/` | Web UI local (FastAPI + Jinja2) | **planned** — WEB-1..3 theo ADR-001 | `docs/adr/ADR-001-web-ui.md` |
| `tests/` | unittest, mock mọi tiến trình/dịch vụ ngoài | implemented | §4 luật 1 |

## 4. Project policy

### Luật bắt buộc

1. **Test pass KHÔNG chứng minh checkpoint đã xong.** Toàn bộ test suite mock `ffmpeg`, `yt-dlp`, `faster-whisper`, Ollama, edge-tts. Đã từng có 29/29 test xanh trong khi `source.mp4` tải về không có audio track; ba bug thật cùng tồn tại mà không test nào bắt: (a) format selector khớp DASH stream chỉ có video → file câm; (b) `--force` không ghi đè vì yt-dlp lặng lẽ bỏ qua file đã tồn tại; (c) player client mặc định của YouTube chỉ trả storyboard `mhtml` với một số video public → "This video is not available". Vì vậy **Required verification của mọi task chạm pipeline phải có một lần chạy thật với video thật, rồi đọc artifact sinh ra** — không chỉ nhìn exit code. Lỗi của pipeline nằm ở giao diện với tiến trình ngoài, đúng chỗ mock không chạm tới.
2. **Mỗi lần một checkpoint/task.** Không tự khởi động checkpoint kế tiếp (plan §27). Xong: chạy test → chạy thật → tóm tắt file đã đổi → ghi phần chưa làm → DỪNG (READY).
3. **Mọi stage phải resume được.** Mỗi stage ghi artifact trung gian, bỏ qua nếu artifact đã có trừ khi `--force`. Không gọi lại AI/TTS khi output đã có — playlist 26 tập chạy hàng giờ, không được mất tiến trình giữa chừng.
4. **Không hard-code** model, API key, đường dẫn đặc thù máy: tất cả qua config hoặc CLI; key mới thêm vào `config.example.yaml`.

### Quy ước code và tài liệu

- Comment, docstring, commit message, tài liệu: **tiếng Việt**; tên file, field, thuật ngữ canonical của framework giữ English.
- Comment giải thích *tại sao*, nhất là ở chỗ từng có bug. Theo style file xung quanh.
- Dependency mới là decision gate (`docs/ai/workflow.md` §3); stdlib làm được thì không thêm.
- Không commit video/audio, model AI hay secret.
- Quyết định nhỏ khi triển khai một checkpoint ghi ở `docs/decisions/checkpoint-N.md` (mẫu `checkpoint-3.md`): **mục A. Contract với checkpoint sau** đặt đầu; đánh dấu `[CẦN DUYỆT]` cho chỗ ORCHESTRATOR cần xem. Quyết định cấp kiến trúc/scope (S2) ghi ở `docs/adr/ADR-NNN-*.md` (metadata `Status`: PROPOSED / ACCEPTED / SUPERSEDED).

## 5. Integration mechanism

- Target branch: `main`, remote `origin` (`github.com:ntnghia1908/youtube-vietnamese-dubber`). Repo một người: commit thẳng `main` là mặc định; branch/PR chỉ khi HUMAN LEAD yêu cầu.
- Commit: mỗi checkpoint/task một commit (`checkpoint-N: ...`, gồm cả task contract và `docs/decisions/checkpoint-N.md`); bug fix tách riêng (`fix(scope): ...`); tài liệu `docs: ...`.
- ORCHESTRATOR chỉ commit khi HUMAN LEAD đồng ý; push do HUMAN LEAD yêu cầu. IMPLEMENTER không commit/push.

## 6. Ownership

HUMAN LEAD (chủ repo) giữ: scope, chọn checkpoint/hạng mục CP9, dependency, mọi decision gate, nghe/xem đánh giá chất lượng output thật, commit/push.

## 7. Execution profiles

Được phép: `dual-agent` (mặc định cho checkpoint nhiều file + test + chạy thật) và `single-agent` (fix nhỏ, tài liệu, trả lời câu hỏi — làm trực tiếp, không tạo subagent).

| Cỡ việc | Cách làm |
|---|---|
| Checkpoint / task S1–S2 (nhiều file + test + chạy thật) | `/spec N` → (ngoài boundary đã duyệt: HUMAN LEAD `APPROVE TASK`) → `/implement N` → `/clear` |
| Fix bug nhỏ, sửa docs, trả lời câu hỏi | `single-agent`, làm trực tiếp |

Một IMPLEMENTER mỗi checkpoint, không chạy song song — checkpoint sau ăn output của checkpoint trước (`governance.maxParallelImplementers = 1`).

### Governance mode

`boundary` (HUMAN LEAD 2026-10-17). Ghi trong `framework.config.json`; không tự đổi giữa phiên. Mọi task contract ghi `Authorization mode: boundary` (checker yêu cầu) và `Authorization source` cụ thể:

| Boundary đã duyệt | Phạm vi | Authorization source ghi trong task |
|---|---|---|
| ADR-001 mục 0 | WEB-1, WEB-2, WEB-3 | `ADR-001 boundary (HUMAN LEAD 2026-10-17)` |

Task **không** nằm trong boundary nào ở bảng trên (CP9, `fix(...)`...) vẫn cần HUMAN LEAD duyệt riêng: contract để `Implementation authorized: NO` cho tới khi HUMAN LEAD gõ `APPROVE TASK`, rồi ghi `Authorization source: APPROVE TASK <ngày>`. ORCHESTRATOR không tự mở rộng boundary.

### Danh sách IMPLEMENTER

| Adapter | Điểm mạnh | Giới hạn | Dùng khi | Dự phòng |
|---|---|---|---|---|
| `claude-code` (subagent `implementer`, model Sonnet) | tích hợp sẵn với ORCHESTRATOR (Opus), rẻ hơn Opus, luật project nằm sẵn trong `.claude/agents/implementer.md` | tốn hạn mức session chính | mọi checkpoint `dual-agent` | ORCHESTRATOR làm `single-agent` nếu HUMAN LEAD đồng ý |

Cách chọn:

- ORCHESTRATOR chọn IMPLEMENTER lúc viết task contract và ghi vào field `Implementer`; phải nằm trong bảng trên.
- Không đổi IMPLEMENTER giữa task (một writer), trừ dự phòng đã khai; ghi việc đổi vào Result.
- ORCHESTRATOR (Opus) chỉ thiết kế contract và review; không tự viết code của task `dual-agent` ngoài micro-fix (`docs/ai/execution-profiles.md`).

## 8. Setup / tools

Chi tiết dựng môi trường: `docs/SETUP.md`. Yêu cầu: Python ≥ 3.11, `ffmpeg`/`ffprobe` trong PATH, Ollama chạy với model dịch (khuyến nghị `gemma3:12b`) trên GPU, mạng cho edge-tts. Dependency đã duyệt: `pyproject.toml`.

**Python trong venv** — LUÔN dùng, không dùng `python` trần. Ký hiệu `$PY` trong tài liệu/lệnh:

- Windows: `.venv/Scripts/python.exe`
- Linux/macOS: `.venv/bin/python`

```bash
$PY -m app --help
```

Bẫy đã mất thời gian:

- **ffmpeg báo "không tìm thấy"** → khả năng cao shell đang giữ PATH cũ chứ không phải chưa cài. Windows: kiểm PATH bền vững (`[Environment]::GetEnvironmentVariable("Path","Machine")`) trước khi kết luận.
- **In tiếng Việt/tiếng Trung qua `python -c`** → đặt `PYTHONIOENCODING=utf-8`, nếu không sẽ crash `UnicodeEncodeError` trên console Windows. Chạy qua `python -m app` thì không bị.
- **Video không phải tiếng Anh** → luôn truyền `--source-lang`. Auto-detect từng nhận nhầm `zh` thành `en` (confidence 0.562) rồi *dịch bịa* sang tiếng Anh thay vì phiên âm tiếng gốc.
- **Tốc độ dịch chậm bất thường** → chạy `ollama ps` xem cột PROCESSOR trước. Từng chạy cả CP6.5 với `100% CPU` vì bản cài Ollama dở dang (thiếu `ggml-cuda.dll`, `nvidia-smi` vẫn thấy GPU). Cách kiểm/sửa: `docs/SETUP.md` bảng "Lỗi thường gặp".

Framework checker: `node scripts/framework-check.mjs` (Node ≥ 20).

### Test policy

Canonical owner; áp dụng cho mọi IMPLEMENTER bất kể tool.

- Trong vòng sửa: chạy test liên quan (`$PY -m unittest tests.test_xxx`), ưu tiên dừng ở lỗi đầu tiên (`-f`).
- Toàn bộ suite: một lần trước khi báo READY và một lần sau mỗi vòng fix review; không chạy toàn bộ sau từng lần sửa.
- Lệnh chuẩn chạy toàn bộ suite: `$PY -m unittest discover -s tests`.
- Test xanh **không thay** chạy thật (§4 luật 1): task chạm pipeline phải có mục "Chạy thật" trong Required verification — lệnh, video/episode dùng, tiêu chí khi mở artifact, và chạy lần 2 để xác nhận resume có SKIP.
- Không nới `docs/ai/workflow.md` §7: required verification trong task contract vẫn phải chạy và PASS trước READY.

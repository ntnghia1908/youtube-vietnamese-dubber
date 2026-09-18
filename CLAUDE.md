# CLAUDE.md

Hướng dẫn cho Claude khi làm việc trong repo này. Đọc file này trước khi
sửa bất kỳ thứ gì.

## Project

Công cụ CLI chạy local, tạo bản thuyết minh tiếng Việt cho video/playlist
YouTube: tải → STT → dịch → TTS → mix/render. Ưu tiên chạy local, chi phí thấp.

| Cần gì | Đọc ở đâu |
|---|---|
| Kiến trúc pipeline, lộ trình checkpoint | `docs/IMPLEMENTATION_PLAN.md` |
| Dựng môi trường trên máy mới | `docs/SETUP.md` |
| Trạng thái hiện tại | `README.md` + `git log` |

---

## Quy tắc bắt buộc

### 1. Test pass KHÔNG chứng minh checkpoint đã xong

Toàn bộ test suite đều mock `ffmpeg`, `yt-dlp` và `faster-whisper`. Đã
từng có **29/29 test xanh trong khi `source.mp4` tải về không hề có audio
track**. Ba bug thật cùng tồn tại lúc đó mà không test nào bắt được:

1. Format selector khớp DASH stream *chỉ có video* → file câm.
2. `--force` không ghi đè, vì yt-dlp lặng lẽ bỏ qua file đã tồn tại.
3. Player client mặc định của YouTube chỉ trả storyboard `mhtml` với một
   số video vẫn public → báo "This video is not available".

**Mỗi checkpoint phải kết thúc bằng một lần chạy thật với video thật, rồi
đọc artifact sinh ra** — không chỉ nhìn exit code. Lỗi của pipeline này
nằm ở giao diện với các tiến trình ngoài, đúng chỗ mock không chạm tới.

### 2. Mỗi lần một checkpoint

Chỉ làm checkpoint được giao, **không tự khởi động checkpoint kế tiếp**
(plan §27). Xong thì: chạy test → chạy demo thật → tóm tắt file đã đổi →
ghi rõ phần chưa làm → DỪNG LẠI.

### 3. Mọi stage phải resume được

Mỗi stage ghi artifact trung gian, và bỏ qua nếu artifact đã tồn tại trừ
khi có `--force`. Không gọi lại AI/TTS khi output đã có — playlist 26 tập
chạy hàng giờ, không được phép mất tiến trình giữa chừng.

### 4. Không hard-code

Model, API key, đường dẫn đặc thù máy: tất cả phải qua config hoặc CLI.

---

## Lệnh hay dùng

```bash
# LUON dung python trong .venv, khong dung `python` tran
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe -m app --help
```

Ba cái bẫy đã mất thời gian vì nó:

- **ffmpeg báo "không tìm thấy"** → khả năng cao shell đang giữ PATH cũ
  chứ không phải chưa cài. Kiểm tra PATH bền vững
  (`[Environment]::GetEnvironmentVariable("Path","Machine")`) trước khi
  kết luận với user.
- **In tiếng Việt/tiếng Trung qua `python -c`** → đặt
  `PYTHONIOENCODING=utf-8`, nếu không sẽ crash `UnicodeEncodeError` trên
  console Windows. Chạy qua `python -m app` thì không bị.
- **Video không phải tiếng Anh** → luôn truyền `--source-lang`.
  Auto-detect từng nhận nhầm `zh` thành `en` (confidence 0.562) rồi
  *dịch bịa* sang tiếng Anh thay vì phiên âm tiếng gốc.

---

## Quy ước code

- Comment, docstring, commit message: **tiếng Việt**.
- Comment giải thích *tại sao*, nhất là ở chỗ từng có bug.
- Commit: mỗi checkpoint một commit (`checkpoint-N: ...`); bug fix tách
  riêng (`fix(scope): ...`).
- Không commit video/audio, model AI hay secret.

---

## Cách giao việc (mục tiêu: tiết kiệm token)

| Cỡ việc | Cách làm |
|---|---|
| Checkpoint (nhiều file + test + chạy thật) | `/spec N` → user duyệt `docs/specs/cp-N.md` → `/implement N` → `/clear` |
| Fix bug nhỏ, sửa docs, trả lời câu hỏi | Làm trực tiếp, **không** tạo subagent |

- Opus chỉ thiết kế (spec) và review; subagent `implementer` (Sonnet) viết
  code. Luật của Sonnet nằm ở `.claude/agents/implementer.md` — spec không
  lặp lại.
- Quyết định nhỏ khi triển khai ghi ở `docs/decisions/checkpoint-N.md`;
  mục A là contract cho checkpoint sau.
- Một agent mỗi checkpoint, không chạy song song — checkpoint sau ăn output
  của checkpoint trước.
- Không đọc cả `docs/IMPLEMENTATION_PLAN.md` — chỉ mục đang cần (offset/limit).

---

## Việc tiếp theo

**Checkpoint 5 — Timing normalization**: `alignment/timing.py`, đo độ dài
từng `tts/*.mp3`, so với slot gốc (`end - start`), co giãn khi hợp lý,
đánh dấu câu quá dài, xuất `normalized.json` + report
(normal/stretched/too_long). Đọc trước mục A của
`docs/decisions/checkpoint-4.md`: chỉ lấy audio từ entry `status: "ok"`
trong `tts/manifest.json` (không glob), segment có thể không có file; và
chốt câu hỏi `[CẦN DUYỆT]` A2 (ghi `duration` vào manifest ở CP4 hay
CP5 tự ffprobe).

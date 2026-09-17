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

## Cách giao việc khi chạy nhiều agent

- Opus lên plan và review; Sonnet implement.
- **Một agent mỗi checkpoint, không chạy song song** — các checkpoint ăn
  output của nhau (CP4 đọc `translated.json` do CP3 sinh ra), chạy song
  song thì hai agent phải đoán schema của nhau.
- Sonnet **tự sửa lỗi triển khai**. Chỉ escalate lên Opus khi là quyết
  định thiết kế: đổi schema artifact, đổi contract giữa các stage, hoặc
  trade-off chất lượng/chi phí.
- Spec giao việc **phải kèm yêu cầu chạy thật** ở mục 1 — subagent khởi
  động cold, không tự biết bài học đó.

---

## Việc tiếp theo

**Checkpoint 3 — Translation**: abstraction `Translator` +
`OllamaTranslator`, batch 20–30 segment, structured JSON output, validate
ID (đủ, không trùng, không mất segment), retry theo từng batch lỗi, lưu
tiến trình incremental để resume.

Nên gộp luôn **config loader** vào checkpoint này: `app/config.py` chưa
tồn tại dù nằm trong danh mục công việc của CP0, mà plan §10 yêu cầu
không được hard-code provider/model.

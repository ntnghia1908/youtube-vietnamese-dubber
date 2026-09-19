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

Bốn cái bẫy đã mất thời gian vì nó:

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
- **Số đo tốc độ dịch bất thường (chậm)** → chạy `ollama ps` xem cột
  PROCESSOR trước. Từng chạy cả CP6.5 với `100% CPU` mà không biết vì bản
  cài Ollama dở dang (thiếu `ggml-cuda.dll`, `nvidia-smi` vẫn thấy GPU
  bình thường). Cách kiểm/sửa ở `docs/SETUP.md` bảng "Lỗi thường gặp".

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

Đã xong tới **CP8** (`dub` end-to-end, `playlist` với luồng tải song song
+ resume qua `playlist.json`). Playlist thật đang dùng:
`PLJVKAfvqjvcp9lhYU37emhlRZExZrx0Cm` (22 tập, EP13–21 Private, tập dài
18–36 phút, ~35 phút xử lý/tập). EP1 đã `completed`, EP2 đã có transcript.

**Checkpoint 9 — Quality improvements** (plan §CP9: chọn **một** hạng mục
mỗi lần, chỉ sau khi đánh giá output thật). Việc đầu tiên: **nghe
`output_vi.mp4` của EP1** — chưa ai nghe bằng tai output nào từ CP6.
Ứng viên, theo số liệu đã đo:

1. **Câu dịch quá dài**: EP1 có 79/353 câu `too_long` (22%) — vượt
   `timing.max_tempo` 1.25. Hướng: prompt rút gọn câu / dịch lại riêng câu
   too_long với giới hạn ký tự (plan mục 5 "translation shortening").
2. **Nhiều giọng**: một giọng HoaiMy đọc cả vai ba lẫn con (plan mục 6–8).
3. **Dịch 2 tập song song** (không phải chất lượng, là tốc độ): đo được
   nhanh hơn 1.33× ở bước dịch với `OLLAMA_NUM_PARALLEL=2` — số đo ở
   `docs/SETUP.md` mục A4.

Nợ riêng, làm bằng `fix(...)`, không phải checkpoint:
- `fix(tts)`: subagent CP8 từng thấy edge-tts lỗi vĩnh viễn ~20–25% câu trên
  tập 353 câu (lần chạy lại thì 0%) — nghi rate-limit; cần backoff/hạ
  `tts.concurrency`. Xem `docs/decisions/checkpoint-8.md` F1.
- Mục `[CẦN DUYỆT]` còn mở của CP7: C0 (Whisper chia segment khác giữa hai
  lần chạy), C1 (`tts/manifest.json` bị ghi lại dù không đổi).
- Summary `playlist` chỉ in dòng đầu của lỗi → không thấy lý do thật
  (vd "Private video").

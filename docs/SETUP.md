# Setup trên máy mới

Hướng dẫn dựng môi trường chạy project từ đầu trên một máy mới.

Tài liệu này chia làm hai phần rõ ràng:

- **Phần A — người dùng tự cài**: cần quyền admin, trình cài đặt GUI,
  hoặc tài khoản. Claude không làm thay được.
- **Phần B — Claude làm được**: chạy bằng CLI trong thư mục project.

Mỗi bước đều có lệnh kiểm chứng. **Không bước nào được coi là xong nếu
lệnh kiểm chứng chưa chạy đúng.**

---

## Phần A — Người dùng tự cài

### A1. Python 3.11 trở lên

Tải tại <https://www.python.org/downloads/>. Khi cài trên Windows, nhớ
tick **"Add Python to PATH"**.

```bash
python --version      # ky vong: Python 3.11.x tro len
```

> Nếu máy có sẵn Anaconda/Miniconda thì vẫn dùng được, nhưng **tuyệt đối
> không cài dependency vào base env** — Phần B sẽ tạo `.venv` riêng.

### A2. ffmpeg (bắt buộc)

Cần cho cả `yt-dlp` (ghép audio+video khi tải) lẫn subcommand
`transcribe` (trích audio).

- **Windows**: tải bản build tại <https://www.gyan.dev/ffmpeg/builds/>,
  giải nén ra ví dụ `C:\ffmpeg`, rồi thêm `C:\ffmpeg\bin` vào **PATH hệ
  thống**.
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg`

```bash
ffmpeg -version       # phai in ra thong tin phien ban
ffprobe -version      # ffprobe di kem, cung phai co
```

> ⚠️ Sau khi sửa PATH phải **mở terminal mới**. Terminal đang mở (kể cả
> terminal mà Claude đang dùng) vẫn giữ PATH cũ và sẽ báo "not found"
> dù đã cài đúng.

### A3. Git

```bash
git --version
```

### A4. Ollama — cần cho Checkpoint 3 trở đi

Chưa cần nếu chỉ chạy tới Checkpoint 2 (download + transcribe).

Tải tại <https://ollama.com/download>, sau đó kéo model dịch về:

```bash
ollama pull qwen3:8b       # model mac dinh theo docs/IMPLEMENTATION_PLAN.md muc 10
ollama list                # phai thay qwen3:8b trong danh sach
```

### A5. Kết nối mạng cho TTS — cần cho Checkpoint 4 trở đi

Subcommand `tts` gọi dịch vụ giọng đọc của Microsoft Edge qua WebSocket
(package `edge-tts`, miễn phí, không cần đăng ký/API key) — khác với
Ollama, đây **không phải** dịch vụ chạy local nên máy cần có mạng ra
ngoài lúc chạy `tts`. Không cần cài đặt gì thêm ngoài `pip install -e .`.

### A6. GPU NVIDIA — tuỳ chọn, nhưng đây thường là lý do đổi sang máy mạnh

`faster-whisper` chạy nhanh hơn rất nhiều trên GPU. Cần:

- Driver NVIDIA mới
- **CUDA 12.x** và **cuDNN 9** (yêu cầu của `ctranslate2` 4.x — thư viện
  nền của `faster-whisper`)

```bash
nvidia-smi            # xem GPU va phien ban driver/CUDA
```

Có driver + GPU vẫn **chưa đủ** — `ctranslate2` cần thêm cuBLAS 12.x và
cuDNN 9 (đúng tên file dll, vd `cublas64_12.dll`, `cudnn64_9.dll`), nếu
thiếu sẽ lỗi lúc chạy `transcribe --device cuda` (xem bảng lỗi thường gặp
bên dưới).

**Cách A — qua conda (khuyến nghị nếu máy có Anaconda/Miniconda):**
Đơn giản và không dính bẫy "trang tải mặc định giờ ra bản 13.x" ở Cách B.

```bash
conda install nvidia::cudnn cuda-version=12
```

Lệnh này kéo theo `libcublas` bản 12.x cùng lúc nhờ ràng buộc
`cuda-version=12`. DLL nằm ở `<đường dẫn conda>\Library\bin` (vd
`C:\Users\<user>\miniconda3\Library\bin`) — thư mục này thường đã có sẵn
trong PATH của user nếu cài conda có tick "Add to PATH", **không cần**
CUDA Toolkit cài riêng nữa. Kiểm chứng:

```bash
dir "<đường dẫn conda>\Library\bin\cublas64_12.dll"
dir "<đường dẫn conda>\Library\bin\cudnn64_9.dll"
```

**Cách B — CUDA Toolkit + cuDNN cài tay (máy không có conda):**

1. Nếu `nvidia-smi` đã báo CUDA version ≥ 12.x thì driver đủ mới, **không
   cần** tick cài lại driver ở bước sau.
2. Tải tại <https://developer.nvidia.com/cuda-toolkit-archive> (dùng
   trang **Archive**, không phải trang tải chính — trang chính giờ mặc
   định trỏ tới bản **13.x** mà `ctranslate2` 4.x chưa hỗ trợ). Chọn một
   bản **12.x** cụ thể (vd 12.6.3 hoặc 12.8.1) → Windows → x86_64 → 11 →
   exe (local). (`x86_64` chính là kiến trúc `AMD64` mà Windows báo qua
   `$env:PROCESSOR_ARCHITECTURE`; mục chọn hệ điều hành trên trang này
   chọn **`11`** cho Windows 11 thường, không phải `Server 2022`.)
3. Chạy installer → **Custom (Advanced)** → bỏ tick **"Driver
   components"** nếu driver hiện tại đã mới hơn → chỉ giữ CUDA Toolkit
   (Runtime + Development). Cài bản 12.x không đụng tới CUDA khác đã có —
   mỗi bản nằm trong thư mục `CUDA\vXX.X\` riêng.
4. **Mở terminal mới** (PATH chỉ áp dụng cho terminal mở sau khi cài) rồi
   kiểm chứng:

```bash
nvcc --version
dir "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin\x64\cublas64_12.dll"
```

5. Vào <https://developer.nvidia.com/cudnn> (cần đăng nhập tài khoản
   NVIDIA Developer, miễn phí) → chọn **cuDNN 9.x for CUDA 12.x,
   Windows** → tải bản **zip** (không phải installer .exe).
6. Giải nén, copy đè vào đúng thư mục CUDA Toolkit **v12.x** vừa cài
   (gộp chung, không cài vào chỗ riêng):
   - `bin\*.dll` → `...\CUDA\v12.x\bin` (hoặc `bin\x64` nếu bản 12.x mới
     dùng cấu trúc thư mục tách theo kiến trúc)
   - `include\*.h` → `...\CUDA\v12.x\include`
   - `lib\x64\*.lib` → `...\CUDA\v12.x\lib\x64`
7. Mở terminal mới, kiểm chứng file `cudnn64_9.dll` tồn tại trong thư mục
   bin vừa copy.

**Kiểm chứng cuối cùng (áp dụng cho cả hai cách)** — bằng chính pipeline,
không chỉ nhìn dll tồn tại:

```bash
.venv/Scripts/python.exe -m app transcribe "<episode_dir>" \
    --whisper-model tiny --source-lang en --device cuda --force
```

Không có GPU vẫn chạy được, chỉ chậm hơn — xem mục B4.

---

## Phần B — Claude làm được

### B1. Clone repo

```bash
git clone https://github.com/ntnghia1908/youtube-vietnamese-dubber.git
cd youtube-vietnamese-dubber
```

### B2. Tạo virtualenv và cài dependency

```bash
python -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .

# macOS / Linux
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

> **Luôn gọi python qua đường dẫn trong `.venv`**, đừng dùng `python`
> trần — trên máy có conda, `python` trần trỏ vào base env và sẽ không
> có dependency của project.

Kiểm chứng:

```bash
.venv/Scripts/python.exe -c "import yt_dlp, faster_whisper, ctranslate2; print('OK')"
```

### B3. Chạy test suite

```bash
.venv/Scripts/python.exe -m unittest discover -s tests
```

Kỳ vọng: **toàn bộ test pass** (số lượng tăng dần theo mỗi checkpoint —
xem dòng cuối output, vd `Ran 162 tests ... OK`).

> ⚠️ Test pass **không** chứng minh pipeline chạy được — toàn bộ test
> đều mock `ffmpeg`, `yt-dlp` và `faster-whisper`. Đã từng có 29/29 test
> xanh trong khi file tải về không hề có audio track. **Bắt buộc phải
> làm tiếp bước B4.**

### B4. Smoke test thật (bước quan trọng nhất)

Dùng một video ngắn mà bạn có quyền xử lý:

```bash
.venv/Scripts/python.exe -m app download "VIDEO_URL"

# Xac nhan file tai ve co CA video LAN audio:
ffprobe -v error -show_entries stream=codec_type -of csv "output/<episode>/source.mp4"
# ky vong: thay ca "video" va "audio"

.venv/Scripts/python.exe -m app transcribe "output/<episode>" \
    --whisper-model tiny --source-lang en
```

Kiểm chứng kết quả — **mở `transcript.json` ra đọc**, không chỉ nhìn
exit code:

- `language` đúng ngôn ngữ gốc của video
- các segment có `start`/`end` hợp lý và text đọc được thành câu

Lần chạy đầu sẽ tải model Whisper về (`tiny` ~75MB, `medium` ~1.5GB).

### B5. Chọn model và thiết bị

```bash
# May co GPU NVIDIA:
--whisper-model medium --device cuda

# May chi co CPU:
--whisper-model small --device cpu
```

Luôn truyền `--source-lang` cho video không phải tiếng Anh. Auto-detect
của Whisper từng nhận nhầm một video tiếng Trung thành `en` (confidence
0.562) rồi *dịch bịa* sang tiếng Anh thay vì phiên âm đúng tiếng gốc.

---

## Lỗi thường gặp

| Triệu chứng | Nguyên nhân & cách xử lý |
|---|---|
| `Không tìm thấy ffmpeg trên PATH` dù đã cài | Terminal cũ giữ PATH cũ. Mở terminal mới. Trên Windows kiểm tra PATH bền vững: `[Environment]::GetEnvironmentVariable("Path","Machine")` |
| `This video is not available` nhưng video vẫn xem được | YouTube chỉ trả storyboard cho player client mặc định. Đã xử lý sẵn bằng fallback client `android` trong `app/youtube/download.py` — nếu vẫn lỗi, thử cập nhật `yt-dlp`: `pip install -U yt-dlp` |
| `Output file does not contain any stream` | `source.mp4` không có audio track. Tải lại bằng `--force` |
| `UnicodeEncodeError` khi in tiếng Việt/tiếng Trung | Console Windows dùng cp1252. Đặt `PYTHONIOENCODING=utf-8`. Chạy qua `python -m app` thì không bị |
| `ModuleNotFoundError: faster_whisper` | Đang dùng `python` trần thay vì python trong `.venv` |
| Lỗi cuDNN/CUDA khi `--device cuda` (vd `cublas64_12.dll is not found`) | Thiếu CUDA Toolkit 12.x hoặc cuDNN 9 — có driver/GPU không có nghĩa là đã có hai thứ này. Cài theo mục A6. Tạm thời dùng `--device cpu` trong lúc chờ cài |

---

## Checklist bàn giao

Môi trường được coi là sẵn sàng khi **tất cả** dòng dưới đây đúng:

- [ ] `python --version` ≥ 3.11
- [ ] `ffmpeg -version` và `ffprobe -version` chạy được
- [ ] `pip install -e .` thành công trong `.venv`
- [ ] Test suite pass toàn bộ
- [ ] Smoke test B4 tạo ra `source.mp4` **có audio stream**
- [ ] `transcript.json` đọc được, đúng ngôn ngữ
- [ ] (CP3 trở đi) `ollama list` thấy model dịch
- [ ] (CP4 trở đi) máy có mạng ra ngoài; `python -m app tts <episode_dir>`
      tạo được `tts/*.mp3` nghe được (xem mục A5)
- [ ] (CP5 trở đi) `python -m app normalize <episode_dir>` tạo được
      `normalized.json`; report `too_long` không bất thường so với số
      segment

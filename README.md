# YouTube Vietnamese Dubber

Công cụ chạy local để tạo bản thuyết minh tiếng Việt cho một video hoặc
một playlist YouTube (STT → dịch → TTS → mix/render), ưu tiên chi phí
thấp và tối đa hoá phần chạy local.

> Chỉ xử lý nội dung mà bạn có quyền sử dụng, phù hợp với điều khoản
> của nguồn nội dung. Project không nhằm mục đích tái phát hành nội
> dung có bản quyền.

Kiến trúc pipeline đầy đủ, nguyên tắc thiết kế và lộ trình từng
checkpoint được mô tả chi tiết tại
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

## Trạng thái hiện tại — Checkpoint 3: Translation

Đã có:

- Project skeleton (Checkpoint 0).
- Subcommand `download`: tải một video YouTube (yt-dlp), tạo
  `metadata.json` + `source.mp4` trong một thư mục episode riêng
  (Checkpoint 1).
- Subcommand `transcribe`: trích audio từ `source.mp4` (ffmpeg) rồi
  speech-to-text (faster-whisper), tạo `audio.wav` + `transcript.json`
  trong thư mục episode (Checkpoint 2).
- Subcommand `translate`: dịch `transcript.json` sang tiếng Việt bằng
  Ollama local, tạo `translated.json`; đọc cấu hình từ `config.yaml`
  (Checkpoint 3).

Chưa có: TTS, timing normalization, render, pipeline end-to-end, playlist.

## Yêu cầu

- Python 3.11 trở lên.
- `ffmpeg` cài sẵn trên máy và có trong `PATH` — cần cho `yt-dlp` (merge
  audio+video khi tải) và cho subcommand `transcribe` (trích audio).
- [Ollama](https://ollama.com/download) đang chạy, đã `ollama pull` model
  dịch (vd `qwen3:8b`) — cần cho subcommand `translate`.

## Cài đặt (development)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Dependency hiện tại: `yt-dlp` (subcommand `download`), `faster-whisper`
(subcommand `transcribe`), `pyyaml` (đọc config).

## Cấu hình

```bash
cp config.example.yaml config.yaml   # config.yaml đã được gitignore
```

Mọi lệnh tự đọc `./config.yaml` nếu có, hoặc chỉ định bằng `--config PATH`.
Flag CLI ghi đè giá trị trong config. Riêng `translation.model` không có
mặc định trong code — phải đặt trong config hoặc truyền `--model`.

## Sử dụng

```bash
python -m app --help

# Tải một video, lưu vào ./output/<video_id>__<title>/
python -m app download "https://www.youtube.com/watch?v=VIDEO_ID"

# Chỉ định thư mục workspace khác + ép tải lại dù đã có source.mp4
python -m app download "URL" --workspace ./output --force

# Trích audio + transcribe episode đã tải (mặc định model "medium")
python -m app transcribe "output/VIDEO_ID__title"

# Chọn model Whisper khác + ép chạy lại dù đã có audio.wav/transcript.json
python -m app transcribe "output/VIDEO_ID__title" --whisper-model small --force

# Ép ngôn ngữ gốc khi auto-detect đoán sai (vd video tiếng Trung)
python -m app transcribe "output/VIDEO_ID__title" --source-lang zh

# Dịch transcript sang tiếng Việt (model lấy từ config.yaml)
python -m app translate "output/VIDEO_ID__title"

# Chọn model/batch khác + ép dịch lại từ đầu
python -m app translate "output/VIDEO_ID__title" --model qwen3:8b --batch-size 20 --force
```

`translate` dịch theo batch (mặc định 25 segment), validate đủ/không
trùng ID, retry batch lỗi rồi chia đôi batch nếu vẫn lỗi. Mỗi batch xong
được ghi vào `translated.partial.json`: bị ngắt giữa chừng thì chạy lại
lệnh sẽ dịch tiếp phần còn thiếu, không gọi lại model cho phần đã xong.

Nên dùng `--source-lang` cho video không phải tiếng Anh: auto-detect của
Whisper có thể đoán sai với confidence thấp (nhạc nền ở đầu video), khiến
toàn bộ transcript bị *dịch* sang ngôn ngữ đoán nhầm thay vì phiên âm
đúng tiếng gốc.

Chạy lại lệnh `download`/`transcribe`/`translate` sẽ **không làm lại** các
bước đã có output (`source.mp4`, `audio.wav`, `transcript.json`,
`translated.json`) trừ khi dùng
`--force` (hỗ trợ resume).

## Chạy test

```bash
python -m unittest discover -s tests
```

## Cấu trúc thư mục

```text
youtube-vietnamese-dubber/
├── app/                  # Source code chính (package "app")
│   ├── __main__.py       # Cho phép chạy `python -m app`
│   ├── cli.py            # CLI (argparse); subcommand download, transcribe, translate
│   ├── config.py         # load_config(): config.yaml -> AppConfig
│   ├── youtube/          # Stage: metadata & download video (yt-dlp)
│   │   └── download.py   # download_video(): metadata.json + source.mp4, có resume
│   ├── audio/            # Stage: xử lý audio/video (FFmpeg)
│   │   └── ffmpeg.py     # extract_audio(): source.mp4 -> audio.wav, có resume
│   ├── transcription/    # Stage: speech-to-text (faster-whisper)
│   │   └── whisper.py    # transcribe_audio(): audio.wav -> transcript.json, có resume
│   ├── translation/      # Stage: dịch thuật
│   │   ├── base.py       # Translator (abstraction) + validate output model
│   │   ├── prompt.py     # prompt + JSON schema dùng chung
│   │   ├── ollama.py     # OllamaTranslator
│   │   └── translate.py  # translate_transcript(): transcript.json -> translated.json, có resume
│   ├── tts/               # Stage: text-to-speech tiếng Việt (edge-tts)
│   ├── synchronization/  # Stage: chuẩn hoá timing giữa audio gốc và TTS
│   └── pipeline/         # Điều phối pipeline end-to-end, resume/checkpoint
├── docs/
│   └── IMPLEMENTATION_PLAN.md  # Kế hoạch triển khai đầy đủ, theo checkpoint
├── tests/                 # Unit / smoke test
├── output/                 # Output sinh ra khi chạy (không commit nội dung)
├── temp/                    # File tạm khi xử lý (không commit nội dung)
├── config.example.yaml    # Mẫu cấu hình, copy thành config.yaml
├── .env.example           # Mẫu biến môi trường
├── .gitignore
└── pyproject.toml
```

Các package stage còn lại (`tts`, `synchronization`,
`pipeline`) hiện chỉ chứa `__init__.py` dạng placeholder, tương ứng với
từng checkpoint sẽ được triển khai riêng lẻ theo
`docs/IMPLEMENTATION_PLAN.md`.

## Ghi chú thiết kế

- Không commit video/audio, model AI hoặc secret (`.env`) vào Git.
- Không hard-code model, API key hay path đặc thù máy — đặt trong
  `config.yaml` hoặc truyền qua CLI.
- Mỗi checkpoint được triển khai và review riêng lẻ, không gộp nhiều
  checkpoint trong một lần thay đổi.

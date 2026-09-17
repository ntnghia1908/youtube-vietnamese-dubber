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

## Trạng thái hiện tại — Checkpoint 2: Audio extraction + Whisper

Đã có:

- Project skeleton (Checkpoint 0).
- Subcommand `download`: tải một video YouTube (yt-dlp), tạo
  `metadata.json` + `source.mp4` trong một thư mục episode riêng
  (Checkpoint 1).
- Subcommand `transcribe`: trích audio từ `source.mp4` (ffmpeg) rồi
  speech-to-text (faster-whisper), tạo `audio.wav` + `transcript.json`
  trong thư mục episode (Checkpoint 2).

Chưa có: translation, TTS, timing normalization, render, pipeline
end-to-end, playlist.

## Yêu cầu

- Python 3.11 trở lên.
- `ffmpeg` cài sẵn trên máy và có trong `PATH` — cần cho `yt-dlp` (merge
  audio+video khi tải) và cho subcommand `transcribe` (trích audio).

## Cài đặt (development)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Dependency hiện tại: `yt-dlp` (subcommand `download`), `faster-whisper`
(subcommand `transcribe`).

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
```

Nên dùng `--source-lang` cho video không phải tiếng Anh: auto-detect của
Whisper có thể đoán sai với confidence thấp (nhạc nền ở đầu video), khiến
toàn bộ transcript bị *dịch* sang ngôn ngữ đoán nhầm thay vì phiên âm
đúng tiếng gốc.

Chạy lại lệnh `download`/`transcribe` sẽ **không làm lại** các bước đã
có output (`source.mp4`, `audio.wav`, `transcript.json`) trừ khi dùng
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
│   ├── cli.py            # CLI (argparse); subcommand download, transcribe
│   ├── youtube/          # Stage: metadata & download video (yt-dlp)
│   │   └── download.py   # download_video(): metadata.json + source.mp4, có resume
│   ├── audio/            # Stage: xử lý audio/video (FFmpeg)
│   │   └── ffmpeg.py     # extract_audio(): source.mp4 -> audio.wav, có resume
│   ├── transcription/    # Stage: speech-to-text (faster-whisper)
│   │   └── whisper.py    # transcribe_audio(): audio.wav -> transcript.json, có resume
│   ├── translation/      # Stage: dịch thuật (adapter Ollama/OpenAI/manual)
│   ├── tts/               # Stage: text-to-speech tiếng Việt (edge-tts)
│   ├── synchronization/  # Stage: chuẩn hoá timing giữa audio gốc và TTS
│   └── pipeline/         # Điều phối pipeline end-to-end, resume/checkpoint
├── docs/
│   └── IMPLEMENTATION_PLAN.md  # Kế hoạch triển khai đầy đủ, theo checkpoint
├── tests/                 # Unit / smoke test
├── output/                 # Output sinh ra khi chạy (không commit nội dung)
├── temp/                    # File tạm khi xử lý (không commit nội dung)
├── .env.example           # Mẫu biến môi trường (chưa được đọc ở bước này)
├── .gitignore
└── pyproject.toml
```

Các package stage còn lại (`translation`, `tts`, `synchronization`,
`pipeline`) hiện chỉ chứa `__init__.py` dạng placeholder, tương ứng với
từng checkpoint sẽ được triển khai riêng lẻ theo
`docs/IMPLEMENTATION_PLAN.md`.

## Ghi chú thiết kế

- Không commit video/audio, model AI hoặc secret (`.env`) vào Git.
- Không hard-code model, API key hay path đặc thù máy — cấu hình sẽ
  được đưa vào file config riêng ở checkpoint sau.
- Mỗi checkpoint được triển khai và review riêng lẻ, không gộp nhiều
  checkpoint trong một lần thay đổi.

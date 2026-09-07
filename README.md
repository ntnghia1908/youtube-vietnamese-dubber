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

## Trạng thái hiện tại — Checkpoint 1: Download video

Đã có:

- Project skeleton (Checkpoint 0).
- Subcommand `download`: tải một video YouTube (yt-dlp), tạo
  `metadata.json` + `source.mp4` trong một thư mục episode riêng.

Chưa có: transcription, translation, TTS, timing normalization,
render, pipeline end-to-end, playlist.

## Yêu cầu

- Python 3.11 trở lên.
- `ffmpeg` cài sẵn trên máy nếu sau này cần merge audio+video khi tải
  (chưa bắt buộc ở checkpoint này, nhưng yt-dlp sẽ cần tới).

## Cài đặt (development)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Dependency hiện tại: `yt-dlp` (dùng cho subcommand `download`).

## Sử dụng

```bash
python -m app --help

# Tải một video, lưu vào ./output/<video_id>__<title>/
python -m app download "https://www.youtube.com/watch?v=VIDEO_ID"

# Chỉ định thư mục workspace khác + ép tải lại dù đã có source.mp4
python -m app download "URL" --workspace ./output --force
```

Chạy lại lệnh `download` với cùng URL sẽ **không tải lại** nếu
`source.mp4` đã tồn tại trong thư mục episode (hỗ trợ resume).

## Chạy test

```bash
python -m unittest discover -s tests
```

## Cấu trúc thư mục

```text
youtube-vietnamese-dubber/
├── app/                  # Source code chính (package "app")
│   ├── __main__.py       # Cho phép chạy `python -m app`
│   ├── cli.py            # CLI (argparse); --help/--version + subcommand download
│   ├── youtube/          # Stage: metadata & download video (yt-dlp)
│   │   └── download.py   # download_video(): metadata.json + source.mp4, có resume
│   ├── audio/            # Stage: xử lý audio/video (FFmpeg)
│   ├── transcription/    # Stage: speech-to-text (faster-whisper)
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

Mỗi package stage (`youtube`, `audio`, `transcription`, `translation`,
`tts`, `synchronization`, `pipeline`) hiện chỉ chứa `__init__.py` dạng
placeholder, tương ứng với từng checkpoint sẽ được triển khai riêng lẻ
theo `docs/IMPLEMENTATION_PLAN.md`.

## Ghi chú thiết kế

- Không commit video/audio, model AI hoặc secret (`.env`) vào Git.
- Không hard-code model, API key hay path đặc thù máy — cấu hình sẽ
  được đưa vào file config riêng ở checkpoint sau.
- Mỗi checkpoint được triển khai và review riêng lẻ, không gộp nhiều
  checkpoint trong một lần thay đổi.

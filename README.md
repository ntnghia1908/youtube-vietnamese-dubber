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

## Trạng thái hiện tại — Checkpoint 0: Project skeleton

Đây **chỉ** là bộ khung project. Chưa có logic download, transcription,
translation, TTS hay xử lý video/audio nào được implement. CLI hiện chỉ
hiển thị `--help`.

## Yêu cầu

- Python 3.11 trở lên.

## Cài đặt (development)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Không có dependency bên ngoài nào ở bước skeleton này.

## Sử dụng

```bash
python -m app --help
```

## Chạy test

```bash
python -m unittest discover -s tests
```

## Cấu trúc thư mục

```text
youtube-vietnamese-dubber/
├── app/                  # Source code chính (package "app")
│   ├── __main__.py       # Cho phép chạy `python -m app`
│   ├── cli.py            # CLI (argparse); hiện chỉ có --help/--version
│   ├── youtube/          # Stage: metadata & download video/playlist (yt-dlp)
│   │   └── download.py
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

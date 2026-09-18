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

## Trạng thái hiện tại — Checkpoint 5: Timing normalization

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
- Subcommand `tts`: tổng hợp giọng tiếng Việt cho từng segment bằng
  edge-tts, tạo `tts/000001.mp3`… + `tts/manifest.json` (resume/cache
  theo từng segment) (Checkpoint 4).
- Subcommand `normalize`: đo độ dài thật từng file TTS bằng `ffprobe`, so
  với slot gốc (`end - start`), co giãn nhẹ bằng `ffmpeg atempo` khi hợp
  lý, đánh dấu câu quá dài; tạo `normalized.json` + `timing/*.wav`
  (Checkpoint 5).

Chưa có: build voice track hoàn chỉnh + render video (Checkpoint 6),
pipeline end-to-end (Checkpoint 7), playlist (Checkpoint 8).

## Yêu cầu

- Python 3.11 trở lên.
- `ffmpeg` (kèm `ffprobe`) cài sẵn trên máy và có trong `PATH` — cần cho
  `yt-dlp` (merge audio+video khi tải), cho subcommand `transcribe`
  (trích audio) và cho subcommand `normalize` (đo độ dài + co giãn audio).
- [Ollama](https://ollama.com/download) đang chạy, đã `ollama pull` model
  dịch (vd `qwen3:8b`) — cần cho subcommand `translate`.
- Kết nối mạng khi chạy subcommand `tts` — `edge-tts` gọi dịch vụ giọng
  đọc của Microsoft Edge qua WebSocket (miễn phí, không cần API key).

## Cài đặt (development)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

Dependency hiện tại: `yt-dlp` (subcommand `download`), `faster-whisper`
(subcommand `transcribe`), `pyyaml` (đọc config), `edge-tts` (subcommand
`tts`). Subcommand `normalize` chỉ cần `ffmpeg`/`ffprobe`, không thêm
dependency Python.

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

# Tổng hợp giọng tiếng Việt (edge-tts) cho từng segment đã dịch
python -m app tts "output/VIDEO_ID__title"

# Chọn voice/tốc độ khác (xem toàn bộ voice: `edge-tts --list-voices`)
python -m app tts "output/VIDEO_ID__title" --voice vi-VN-NamMinhNeural --rate=+10%

# Chuẩn hoá timing: so tts/*.mp3 với slot gốc, co giãn khi hợp lý
python -m app normalize "output/VIDEO_ID__title"

# Nâng mức co giãn tối đa (mặc định 1.25 -> tempo tối đa 1.25x)
python -m app normalize "output/VIDEO_ID__title" --max-tempo 1.4
```

`translate` dịch theo batch (mặc định 25 segment), validate đủ/không
trùng ID, retry batch lỗi rồi chia đôi batch nếu vẫn lỗi. Mỗi batch xong
được ghi vào `translated.partial.json`: bị ngắt giữa chừng thì chạy lại
lệnh sẽ dịch tiếp phần còn thiếu, không gọi lại model cho phần đã xong.

Nên dùng `--source-lang` cho video không phải tiếng Anh: auto-detect của
Whisper có thể đoán sai với confidence thấp (nhạc nền ở đầu video), khiến
toàn bộ transcript bị *dịch* sang ngôn ngữ đoán nhầm thay vì phiên âm
đúng tiếng gốc.

`tts` tổng hợp song song (mặc định 4 segment cùng lúc), cache theo từng
segment (`hash(provider + voice + rate + volume + text)`): sửa một câu
dịch chỉ tổng hợp lại đúng câu đó, đổi voice/rate/volume tổng hợp lại
toàn bộ. Một segment lỗi hết số lần thử không chặn cả episode (`tts/
manifest.json` ghi `status: "failed"`), lệnh in cảnh báo kèm id để chạy
lại.

`normalize` đo độ dài thật từng file `tts/*.mp3` bằng `ffprobe`: câu vượt
`normal_max_ratio` (mặc định 1.05× slot) được tăng tốc nhẹ bằng `ffmpeg
atempo` (`timing/000007.wav`); câu vẫn dài hơn `max_tempo` (mặc định
1.25×) sau khi tăng tốc tối đa được đánh dấu `too_long` trong report và
`normalized.json`. Việc rút gọn câu quá dài bằng AI rồi tổng hợp lại chưa
làm ở checkpoint này.

Chạy lại lệnh `download`/`transcribe`/`translate`/`tts`/`normalize` sẽ
**không làm lại** các bước đã có output (`source.mp4`, `audio.wav`,
`transcript.json`, `translated.json`, `tts/manifest.json`,
`normalized.json`) trừ khi dùng `--force` (hỗ trợ resume) — quan trọng
với playlist nhiều tập chạy hàng giờ.

## Chạy test

```bash
python -m unittest discover -s tests
```

## Cấu trúc thư mục

```text
youtube-vietnamese-dubber/
├── app/                  # Source code chính (package "app")
│   ├── __main__.py       # Cho phép chạy `python -m app`
│   ├── cli.py            # CLI (argparse); subcommand download, transcribe, translate, tts, normalize
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
│   ├── tts/              # Stage: text-to-speech tiếng Việt (edge-tts)
│   │   ├── base.py       # TTSEngine (abstraction) + cache_key()
│   │   ├── edge.py       # EdgeTTSEngine
│   │   └── synthesize.py # synthesize_translation(): translated.json -> tts/*.mp3 + manifest.json, có resume
│   ├── synchronization/  # Stage: chuẩn hoá timing giữa audio gốc và TTS
│   │   └── timing.py     # normalize_timing(): tts/*.mp3 -> normalized.json + timing/*.wav, có resume
│   └── pipeline/         # Điều phối pipeline end-to-end, resume/checkpoint (chưa triển khai)
├── docs/
│   ├── IMPLEMENTATION_PLAN.md  # Kế hoạch triển khai đầy đủ, theo checkpoint
│   ├── SETUP.md                # Hướng dẫn dựng môi trường trên máy mới
│   ├── specs/                  # Spec từng checkpoint (Opus viết, duyệt trước khi implement)
│   └── decisions/               # Quyết định triển khai + contract giữa các checkpoint
├── tests/                 # Unit / smoke test
├── output/                 # Output sinh ra khi chạy (không commit nội dung)
├── temp/                    # File tạm khi xử lý (không commit nội dung)
├── config.example.yaml    # Mẫu cấu hình, copy thành config.yaml
├── .env.example           # Mẫu biến môi trường
├── .gitignore
└── pyproject.toml
```

`app/pipeline/` hiện chỉ chứa `__init__.py` dạng placeholder — điều phối
end-to-end (`dub`, `playlist`) sẽ triển khai ở Checkpoint 7/8 theo
`docs/IMPLEMENTATION_PLAN.md`.

## Ghi chú thiết kế

- Không commit video/audio, model AI hoặc secret (`.env`) vào Git.
- Không hard-code model, API key hay path đặc thù máy — đặt trong
  `config.yaml` hoặc truyền qua CLI.
- Mỗi checkpoint được triển khai và review riêng lẻ, không gộp nhiều
  checkpoint trong một lần thay đổi.

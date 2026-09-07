# Kế hoạch triển khai Project: YouTube Vietnamese Dubber

## 1. Mục tiêu

Xây một công cụ đơn giản chạy local để tạo bản thuyết minh tiếng Việt cho một video hoặc một playlist YouTube.

Use case ban đầu:

- Playlist khoảng 26 tập.
- Mỗi tập khoảng 23–25 phút.
- Tổng thời lượng khoảng 10–11 giờ.
- Ưu tiên chi phí thấp.
- Chạy càng nhiều tác vụ local càng tốt.
- Không cần web UI ở phiên bản đầu.
- Không cần clone giọng nhân vật.
- Không cần lip-sync chính xác tuyệt đối.
- Mục tiêu trước tiên là tạo bản xem được, lời dịch tự nhiên, timing tương đối ổn định.

> Lưu ý: chỉ nên xử lý nội dung mà bạn có quyền sử dụng hoặc dùng cho mục đích cá nhân phù hợp với điều khoản của nguồn nội dung. Không thiết kế project với mục tiêu tái phát hành nội dung có bản quyền.

---

# 2. Nguyên tắc thiết kế

Project nên tuân theo các nguyên tắc sau:

1. **MVP trước, tối ưu sau.**
2. Mỗi bước của pipeline phải tạo ra file trung gian để có thể kiểm tra và chạy lại riêng lẻ.
3. Nếu chương trình bị dừng giữa chừng thì chạy lại không làm lại toàn bộ từ đầu.
4. Không gọi AI/TTS lại nếu output của bước đó đã tồn tại.
5. Có log rõ ràng theo từng episode.
6. Có thể chạy một tập trước khi chạy cả playlist.
7. Kiến trúc module hóa để sau này thay Whisper, translator hoặc TTS mà không sửa toàn bộ project.

---

# 3. Pipeline đề xuất

```text
YouTube URL / Playlist URL
        |
        v
      yt-dlp
        |
        v
   source.mp4
        |
        +--------------------------+
        |                          |
        v                          v
  extract audio               video stream
        |
        v
 faster-whisper
        |
        v
 transcript.json
        |
        v
 translation engine
        |
        v
 translated.json
        |
        v
 timing normalization
        |
        v
 Vietnamese TTS
        |
        v
 speech segments
        |
        v
 build Vietnamese audio track
        |
        v
      FFmpeg
        |
        v
 episode_vi.mp4
```

MVP không cần source separation.

Phiên bản đầu sẽ:

- giảm volume audio gốc khi có lời Việt;
- chèn giọng Việt lên trên;
- vẫn giữ nhạc nền và sound effect gốc ở mức tương đối.

Sau khi MVP hoạt động mới thử source separation nếu chất lượng audio gốc gây khó chịu.

---

# 4. Công nghệ

## Ngôn ngữ

Python 3.11 hoặc 3.12.

Lý do:

- Whisper ecosystem mạnh.
- audio processing thuận tiện.
- dễ gọi CLI FFmpeg/yt-dlp.
- dễ tích hợp LLM API hoặc local LLM.

## Thành phần

### Download / metadata

- `yt-dlp`

### Audio/video processing

- `ffmpeg`
- `ffprobe`

### Speech-to-text

- `faster-whisper`

Model khởi đầu:

```text
medium
```

Nếu GPU mạnh:

```text
large-v3
```

Nếu CPU hoặc GPU yếu:

```text
small
```

### Translation

Thiết kế adapter để hỗ trợ nhiều backend:

```text
Translator
 ├── OllamaTranslator
 ├── OpenAITranslator
 └── ManualTranslator (optional)
```

Ưu tiên kinh tế:

1. Ollama + local model nếu máy đủ mạnh.
2. API model rẻ nếu chất lượng local không đạt.

Không nên hard-code translator vào pipeline.

### Vietnamese TTS

MVP:

- `edge-tts`

Ưu điểm:

- setup đơn giản;
- có giọng tiếng Việt;
- không cần dựng model TTS local;
- thích hợp cho POC/MVP.

Sau này có thể thay bằng:

- Azure Speech;
- FPT AI;
- Viettel AI;
- ElevenLabs;
- local Vietnamese TTS.

### Configuration

- YAML hoặc TOML.

Khuyến nghị:

```text
config.yaml
```

---

# 5. Không làm trong MVP

Để project không phình quá nhanh, phiên bản đầu KHÔNG triển khai:

- speaker diarization;
- nhận dạng nhân vật;
- nhiều voice tự động;
- voice cloning;
- lip sync;
- web UI;
- database;
- distributed processing;
- Docker;
- Demucs/source separation;
- tự động upload lại YouTube;
- realtime dubbing.

Các tính năng này chỉ xem xét sau khi một episode hoàn chỉnh hoạt động tốt.

---

# 6. Cấu trúc repository

```text
youtube-vietnamese-dubber/
|
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── config.example.yaml
|
├── src/
│   └── dubber/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── pipeline.py
│       │
│       ├── youtube/
│       │   ├── __init__.py
│       │   ├── metadata.py
│       │   └── downloader.py
│       │
│       ├── media/
│       │   ├── __init__.py
│       │   ├── ffmpeg.py
│       │   └── audio.py
│       │
│       ├── transcription/
│       │   ├── __init__.py
│       │   └── whisper.py
│       │
│       ├── translation/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── ollama.py
│       │   └── openai.py
│       │
│       ├── tts/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── edge.py
│       │
│       ├── alignment/
│       │   ├── __init__.py
│       │   └── timing.py
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   └── segment.py
│       │
│       └── utils/
│           ├── __init__.py
│           ├── files.py
│           └── logging.py
│
├── tests/
│
├── workspace/
│   └── .gitkeep
│
└── scripts/
```

Không commit video/audio hoặc model AI vào Git.

---

# 7. Cấu trúc workspace

Mỗi episode có một thư mục độc lập.

```text
workspace/
└── ep_001/
    ├── metadata.json
    ├── source.mp4
    ├── audio.wav
    ├── transcript.json
    ├── translated.json
    ├── normalized.json
    │
    ├── tts/
    │   ├── 000001.mp3
    │   ├── 000002.mp3
    │   ├── 000003.mp3
    │   └── ...
    │
    ├── voice_track.wav
    ├── mixed_audio.wav
    └── output_vi.mp4
```

Ưu điểm:

- dễ debug;
- resume;
- có thể sửa translation rồi chạy lại TTS;
- không cần xử lý lại Whisper.

---

# 8. Data model quan trọng

File `transcript.json`:

```json
{
  "language": "en",
  "segments": [
    {
      "id": 1,
      "start": 12.42,
      "end": 15.13,
      "text": "Where are you going?"
    }
  ]
}
```

File `translated.json`:

```json
{
  "source_language": "en",
  "target_language": "vi",
  "segments": [
    {
      "id": 1,
      "start": 12.42,
      "end": 15.13,
      "source_text": "Where are you going?",
      "translated_text": "Cậu đi đâu đấy?"
    }
  ]
}
```

File `normalized.json` thêm thông tin timing:

```json
{
  "segments": [
    {
      "id": 1,
      "start": 12.42,
      "end": 15.13,
      "duration": 2.71,
      "source_text": "Where are you going?",
      "translated_text": "Cậu đi đâu đấy?",
      "tts_rate": "+5%"
    }
  ]
}
```

---

# 9. CLI mong muốn

CLI phải là interface chính.

Ví dụ:

```bash
python -m dubber dub VIDEO_URL
```

Hoặc sau khi package:

```bash
dubber dub VIDEO_URL
```

Các command đề xuất:

```bash
dubber info URL

dubber download URL

dubber transcribe EPISODE_DIR

dubber translate EPISODE_DIR

dubber tts EPISODE_DIR

dubber render EPISODE_DIR

dubber dub URL

dubber playlist PLAYLIST_URL
```

Các option:

```bash
--workspace ./workspace
--whisper-model medium
--translator ollama
--tts edge
--source-lang auto
--target-lang vi
--resume
--force
```

MVP chỉ cần một subset trước.

---

# 10. Config

Ví dụ `config.yaml`:

```yaml
workspace: ./workspace

target_language: vi

whisper:
  model: medium
  device: auto
  compute_type: auto

translation:
  provider: ollama
  model: qwen3:8b
  batch_size: 25

tts:
  provider: edge
  voice: vi-VN-HoaiMyNeural
  rate: "+0%"
  volume: "+0%"

mixing:
  original_volume: 0.30
  speech_volume: 1.00

pipeline:
  resume: true
```

Tên model local chỉ là config, không được hard-code trong source code.

---

# 11. Translation strategy

Đây là phần quan trọng nhất về chất lượng nội dung.

Không dịch từng segment độc lập.

Nên gom khoảng:

```text
20–30 segments / request
```

và giữ context một ít từ batch trước.

Prompt dịch nên yêu cầu:

```text
Bạn là biên dịch viên phim hoạt hình.

Hãy dịch các lời thoại sang tiếng Việt tự nhiên để dùng cho thuyết minh.

Quy tắc:
- Giữ nguyên id.
- Không thêm hoặc bỏ segment.
- Không giải thích.
- Không dịch word-by-word.
- Dùng cách nói tự nhiên của hội thoại.
- Giữ cách xưng hô nhất quán giữa các nhân vật.
- Ưu tiên câu ngắn vì bản dịch phải nằm trong thời lượng thoại gốc.
- Không dịch tên riêng nếu không cần thiết.
- Không thêm dấu ngoặc, chú thích hay mô tả âm thanh nếu source không có.
- Output chỉ là JSON hợp lệ.
```

Input:

```json
[
  {
    "id": 101,
    "duration": 2.4,
    "text": "What are you doing here?"
  }
]
```

Output:

```json
[
  {
    "id": 101,
    "text": "Cậu làm gì ở đây vậy?"
  }
]
```

Translator phải validate:

- đủ ID;
- không duplicate ID;
- không mất segment;
- JSON parse được.

Nếu lỗi thì retry batch đó, không retry toàn bộ episode.

---

# 12. Xử lý timing

Đây là phần cần thiết nhưng MVP không cần làm quá phức tạp.

## Quy trình

Mỗi segment có:

```text
available_duration = end - start
```

Sau khi tạo TTS:

```text
tts_duration = duration(audio_tts)
```

Tính:

```text
ratio = tts_duration / available_duration
```

### Case 1

```text
ratio <= 1.05
```

Không cần xử lý.

### Case 2

```text
1.05 < ratio <= 1.25
```

Tăng tốc TTS/audio nhẹ.

Ví dụ FFmpeg `atempo`.

### Case 3

```text
ratio > 1.25
```

Đánh dấu segment là `too_long`.

Có thể gọi translator một lần nữa với prompt:

```text
Rút gọn câu tiếng Việt này nhưng giữ nguyên nghĩa.
Thời lượng mục tiêu: 2.3 giây.
```

Sau đó TTS lại.

MVP không cần cố xử lý hoàn hảo tất cả segment.

---

# 13. TTS strategy

MVP dùng một giọng nữ hoặc nam duy nhất.

Ví dụ:

```text
vi-VN-HoaiMyNeural
```

hoặc lựa chọn giọng khác từ danh sách edge-tts.

Mỗi segment được tạo riêng:

```text
tts/000001.mp3
tts/000002.mp3
...
```

Lợi ích:

- retry riêng từng câu;
- chỉnh timing dễ;
- thay một câu không phải synthesize lại cả tập.

Cần cache theo:

```text
hash(text + voice + rate)
```

Nếu file tương ứng đã có thì không gọi TTS lại.

---

# 14. Xây Vietnamese voice track

Tạo một audio track bằng duration của video.

Ví dụ:

```text
0 -------------------------------------- 1500 sec

       [segment1]
              [segment2]
                         [segment3]
```

Mỗi segment TTS được đặt chính xác tại `start` timestamp.

Có thể dùng:

- FFmpeg filters;
- hoặc pydub cho MVP.

Khuyến nghị dùng FFmpeg cho output cuối để hạn chế dependency và tránh encode nhiều lần.

---

# 15. Mix audio trong MVP

Không cố xóa lời gốc ở phiên bản đầu.

Cách đơn giản:

```text
Original audio volume = 25–35%
Vietnamese TTS        = 100%
```

Sau đó mix hai track.

Mục tiêu là tạo bản xem được trước.

Nếu audio gốc vẫn gây nhiễu mạnh, mới chuyển sang checkpoint source separation.

---

# 16. Source separation — optional

Không đưa vào MVP.

Lý do:

- làm pipeline nặng hơn;
- GPU/RAM cao hơn;
- không đảm bảo tách được dialogue khỏi nhạc/SFX tốt trong mọi cảnh;
- Demucs upstream cũ hiện không còn được maintain tích cực.

Sau MVP có thể thử:

```text
source audio
    |
    v
source separation
    |
    +---- vocals/dialogue
    |
    +---- background
               |
               + Vietnamese TTS
```

Chỉ giữ nếu thử nghiệm thực tế cho playlist này chứng minh chất lượng tốt hơn đáng kể.

---

# 17. Resume / checkpoint mechanism

Đây là yêu cầu bắt buộc vì 26 tập có thể chạy hàng giờ.

Pipeline:

```python
if not source.mp4.exists():
    download()

if not transcript.json.exists():
    transcribe()

if not translated.json.exists():
    translate()

if not voice_track.wav.exists():
    generate_tts()

if not output_vi.mp4.exists():
    render()
```

Có thêm:

```bash
--force transcribe
--force translate
--force tts
--force render
```

hoặc thiết kế đơn giản tương đương.

---

# 18. Logging

Log ví dụ:

```text
[EP01] Download ............. SKIP
[EP01] Extract audio ........ SKIP
[EP01] Transcribe ........... DONE
[EP01] Translate 1/34 ....... DONE
[EP01] Translate 2/34 ....... DONE
[EP01] TTS 1/421 ............ DONE
[EP01] TTS 2/421 ............ DONE
...
[EP01] Render ............... DONE
```

Khi lỗi:

```text
[EP01][TTS][segment=174] ERROR
```

Không được làm mất toàn bộ tiến trình.

---

# 19. Playlist processing

Chỉ implement sau khi single-video pipeline ổn.

Input:

```bash
dubber playlist "PLAYLIST_URL"
```

yt-dlp lấy:

```text
playlist index
video id
video title
video URL
```

Workspace:

```text
workspace/
├── 001_episode-name/
├── 002_episode-name/
├── 003_episode-name/
└── ...
```

Xử lý tuần tự trước:

```text
EP01 -> done
EP02 -> done
EP03 -> done
```

Không parallel ở MVP vì Whisper/TTS/translation đều có thể tranh GPU, RAM hoặc rate limit.

Sau này mới thêm concurrency cho các task nhẹ.

---

# 20. Checkpoint triển khai cho Claude Code

## Checkpoint 0 — Repository skeleton

### Mục tiêu

Tạo project chạy được nhưng chưa xử lý media.

### Công việc

- tạo Python project;
- cấu trúc folder;
- setup `pyproject.toml`;
- CLI cơ bản;
- config loader;
- logging;
- `.gitignore`;
- README cơ bản.

### Acceptance criteria

Chạy được:

```bash
python -m dubber --help
```

và:

```bash
python -m dubber version
```

Không có logic AI ở checkpoint này.

---

# Checkpoint 1 — Download video

### Mục tiêu

Nhận một URL YouTube và tạo workspace episode.

### Công việc

Implement:

```text
youtube/metadata.py
youtube/downloader.py
```

Command:

```bash
dubber download VIDEO_URL
```

Output:

```text
metadata.json
source.mp4
```

### Acceptance criteria

- đọc được video title;
- lấy video ID;
- download thành công;
- filename không chứa ký tự nguy hiểm;
- chạy lại không download nếu file đã tồn tại;
- error message rõ ràng.

---

# Checkpoint 2 — Audio extraction + Whisper

### Mục tiêu

Tạo transcript có timestamp.

### Công việc

Implement:

```text
media/ffmpeg.py
transcription/whisper.py
models/segment.py
```

Output:

```text
audio.wav
transcript.json
```

### Acceptance criteria

Transcript chứa:

```text
id
start
end
text
```

Cho phép chọn Whisper model từ config.

---

# Checkpoint 3 — Translation

### Mục tiêu

Dịch transcript sang tiếng Việt.

### Công việc

Tạo abstraction:

```python
class Translator:
    def translate_segments(...):
        ...
```

Implement provider đầu tiên:

```text
OllamaTranslator
```

Sau đó optional:

```text
OpenAITranslator
```

### Yêu cầu

- batch 20–30 segments;
- JSON structured output;
- validate ID;
- retry batch lỗi;
- lưu incremental progress;
- resume.

### Output

```text
translated.json
```

### Acceptance criteria

Có thể chạy:

```bash
dubber translate workspace/001_xxx
```

mà không cần chạy lại Whisper.

---

# Checkpoint 4 — Edge TTS

### Mục tiêu

Sinh tiếng Việt cho từng segment.

### Công việc

Implement:

```text
tts/base.py
tts/edge.py
```

Output:

```text
tts/000001.mp3
...
```

### Acceptance criteria

- sinh được toàn bộ segment;
- resume;
- retry;
- cache;
- config voice;
- config speaking rate.

---

# Checkpoint 5 — Timing normalization

### Mục tiêu

Giảm tình trạng tiếng Việt đè sang câu sau.

### Công việc

Implement:

```text
alignment/timing.py
```

Logic:

```text
measure duration
compare original slot
time stretch when reasonable
flag too-long segments
```

### Acceptance criteria

Xuất được report:

```text
segments: 421
normal: 355
stretched: 53
too_long: 13
```

---

# Checkpoint 6 — Build voice track + render

### Mục tiêu

Tạo video thuyết minh hoàn chỉnh.

### Công việc

- đặt TTS vào đúng timestamp;
- mix với original audio;
- giữ video stream;
- output MP4.

Output:

```text
voice_track.wav
output_vi.mp4
```

### Acceptance criteria

Một episode hoàn chỉnh có thể xem từ đầu đến cuối.

---

# Checkpoint 7 — End-to-end command

Command:

```bash
dubber dub VIDEO_URL
```

Pipeline tự chạy:

```text
download
 -> transcribe
 -> translate
 -> tts
 -> normalize
 -> render
```

### Acceptance criteria

Một command tạo được output từ URL video.

---

# Checkpoint 8 — Playlist

Command:

```bash
dubber playlist PLAYLIST_URL
```

### Yêu cầu

- lấy playlist metadata;
- episode index;
- sequential processing;
- resume episode;
- skip episode đã hoàn thành;
- summary cuối cùng.

Ví dụ:

```text
26 episodes
23 completed
2 skipped
1 failed
```

---

# Checkpoint 9 — Quality improvements

Chỉ làm sau khi đánh giá output thật.

Có thể thử lần lượt:

1. subtitle-aware transcription;
2. improved translation prompt;
3. glossary tên nhân vật;
4. character relationship / pronoun rules;
5. translation shortening;
6. voice selection;
7. simple speaker diarization;
8. multiple Vietnamese voices;
9. source separation;
10. automatic QC report.

Không implement tất cả cùng lúc.

---

# 21. Glossary và context cho phim

Sau khi test 1 tập, nên tạo:

```text
glossary.yaml
```

Ví dụ:

```yaml
characters:
  Alice: Alice
  Bob: Bob

terms:
  Magic Stone: Đá Ma Thuật

relationships:
  Alice_Bob: "bạn bè, xưng tớ-cậu"
```

Translator đọc glossary trước khi dịch.

Đây thường cải thiện chất lượng hơn việc thay model lớn hơn.

---

# 22. Kiểm soát chi phí

Tổng playlist khoảng 10–11 giờ.

Chi phí nên được giảm bằng cách:

### STT

Chạy `faster-whisper` local.

Chi phí API:

```text
0
```

### Translation

Ưu tiên:

```text
Ollama local
```

Chi phí API:

```text
0
```

Nếu chất lượng không đủ mới dùng API cho translation.

### TTS

MVP:

```text
edge-tts
```

Không cần dùng ElevenLabs cho hàng chục giờ ngay từ đầu.

### Video processing

FFmpeg local.

Do đó phần lớn pipeline có thể chạy mà không cần trả tiền theo phút audio.

---

# 23. Performance

Không tối ưu sớm.

Bottleneck dự kiến:

```text
1. Whisper
2. Translation local LLM
3. TTS request count
```

Video không nên re-encode nếu không cần.

Khi render cuối:

```text
video codec: copy
```

nếu container/codec cho phép.

Chỉ encode audio mới.

Điều này giảm thời gian rất nhiều.

---

# 24. Error handling

Các bước bên ngoài phải có retry hợp lý:

```text
yt-dlp
translation API/local server
TTS
FFmpeg
```

Ví dụ retry:

```text
attempt 1
wait 2s
attempt 2
wait 5s
attempt 3
fail segment
```

Không retry vô hạn.

---

# 25. Testing strategy

Không cần test quá nhiều ở MVP.

Unit test cho:

- config loader;
- segment serialization;
- translation validation;
- timing calculations;
- filename sanitization.

Integration test dùng một clip ngắn khoảng 30–60 giây.

Không đưa video test có bản quyền vào repository.

---

# 26. Git workflow

Các checkpoint nên là các commit riêng.

Ví dụ:

```text
checkpoint-0 repository skeleton
checkpoint-1 youtube download
checkpoint-2 transcription
checkpoint-3 translation
checkpoint-4 tts
checkpoint-5 timing
checkpoint-6 rendering
checkpoint-7 end-to-end
checkpoint-8 playlist
```

Sau mỗi checkpoint:

```bash
git status
git add .
git commit -m "feat: complete checkpoint X ..."
git push
```

Không để Claude Code implement nhiều checkpoint cùng một lần.

---

# 27. Workflow làm việc với Claude Code

Mỗi lần chỉ giao **một checkpoint**.

Claude phải:

1. đọc README và source hiện tại;
2. kiểm tra git status;
3. giải thích ngắn những file sẽ thay đổi;
4. implement đúng checkpoint;
5. chạy test/lint;
6. chạy command demo;
7. báo file đã thay đổi;
8. không tự triển khai checkpoint kế tiếp.

Sau đó người dùng kiểm tra output rồi mới tiếp tục.

---

# 28. Prompt khởi đầu cho Claude Code

```text
Bạn đang đóng vai Senior Python Engineer giúp tôi xây một project cá nhân tên
"YouTube Vietnamese Dubber".

Mục tiêu của project là tạo bản thuyết minh tiếng Việt cho video mà tôi có quyền
xử lý, ưu tiên chạy local và chi phí thấp.

Hãy đọc toàn bộ file kế hoạch `ke-hoach-youtube-vietnamese-dubber.md` trước khi
thực hiện bất kỳ thay đổi nào.

Nguyên tắc làm việc:

1. Chỉ thực hiện checkpoint tôi yêu cầu.
2. Không tự triển khai checkpoint tiếp theo.
3. Giữ solution đơn giản, tránh over-engineering.
4. Python là ngôn ngữ chính.
5. CLI-first, chưa làm Web UI.
6. Không dùng database trong MVP.
7. Mỗi pipeline stage phải tạo artifact trung gian và hỗ trợ resume.
8. Không hard-code model, API key hoặc machine-specific path.
9. Không commit media, model hoặc secret.
10. Ưu tiên code dễ đọc hơn abstraction phức tạp.

Trước khi code:

- đọc repository hiện tại;
- đọc file kế hoạch;
- chạy `git status`;
- kiểm tra cấu trúc project;
- báo ngắn gọn bạn định thay đổi những gì.

Sau khi code:

- chạy test phù hợp;
- chạy command kiểm chứng;
- kiểm tra git diff;
- tóm tắt file đã tạo/sửa;
- ghi rõ những gì chưa làm;
- DỪNG LẠI, không bắt đầu checkpoint kế tiếp.

Nếu có một quyết định kỹ thuật nhỏ chưa được quy định trong kế hoạch, hãy chọn
phương án đơn giản nhất và ghi rõ quyết định đó trong phần tổng kết thay vì mở
rộng scope.
```

---

# 29. Thứ tự thực tế tôi khuyến nghị

Không chạy ngay toàn bộ episode 25 phút.

## Test 1

Dùng clip 30–60 giây.

Kiểm tra:

```text
Whisper -> translation -> TTS -> render
```

## Test 2

Dùng đoạn khoảng 5 phút.

Kiểm tra:

- timing;
- độ tự nhiên của translation;
- âm lượng audio gốc;
- tốc độ TTS.

## Test 3

Chạy một episode hoàn chỉnh.

Chỉ sau khi episode đầu tiên đạt mức chấp nhận được mới triển khai playlist processing.

## Test 4

Chạy 2–3 episode liên tiếp để kiểm tra resume/error handling.

## Production batch

Sau đó mới chạy 26 tập.

---

# 30. Tiêu chí MVP hoàn thành

MVP được coi là thành công khi command:

```bash
dubber dub VIDEO_URL
```

có thể:

1. tải video;
2. transcribe;
3. dịch sang tiếng Việt;
4. sinh TTS;
5. đồng bộ lời nói tương đối với timestamp;
6. mix với audio gốc;
7. tạo MP4;
8. chạy lại có resume;
9. không yêu cầu thao tác thủ công giữa pipeline.

Chưa cần:

```text
perfect voice acting
perfect lip sync
perfect dialogue removal
multiple speakers
```

Nếu MVP đáp ứng các tiêu chí trên, project đã đủ tốt để chuyển sang tối ưu chất lượng.

---

# 31. Quyết định kiến trúc đã chốt

| Hạng mục | Quyết định MVP |
|---|---|
| Language | Python |
| UI | CLI |
| Download | yt-dlp |
| Media | FFmpeg |
| STT | faster-whisper local |
| Translation | Adapter; ưu tiên Ollama local |
| TTS | edge-tts |
| Storage | filesystem / JSON |
| Database | Không |
| Docker | Chưa |
| Speaker detection | Chưa |
| Multi voice | Chưa |
| Source separation | Chưa |
| Playlist | Sau single-video pipeline |
| Resume | Bắt buộc |
| Web UI | Future |

---

# 32. Điểm cần đánh giá sau episode đầu tiên

Sau khi hoàn thành Checkpoint 7 và chạy một episode thật, chỉ cần trả lời 5 câu hỏi:

1. Whisper nhận dạng lời thoại có đủ chính xác không?
2. Bản dịch có tự nhiên không?
3. Tiếng Việt có thường xuyên dài hơn slot gốc không?
4. Giọng gốc còn nghe rõ tới mức khó chịu không?
5. Một voice duy nhất có chấp nhận được không?

Kết quả của 5 câu hỏi này sẽ quyết định checkpoint tối ưu tiếp theo.

Không nên dự đoán trước rồi implement speaker detection, Demucs hay voice cloning khi chưa biết vấn đề thực tế nằm ở đâu.

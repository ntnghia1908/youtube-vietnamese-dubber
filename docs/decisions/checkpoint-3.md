# Checkpoint 3 — Các quyết định nhỏ khi triển khai

Commit: `473ec20 checkpoint-3: translation`.

Plan không quy định các điểm dưới đây nên người triển khai tự chọn. Ghi
lại để review trước khi sang CP4. Mục **[CẦN DUYỆT]** là trade-off nên
chốt lại; mục **[CP4]** là thứ CP4 phải biết khi đọc `translated.json`.

---

## A. Contract với CP4 — đọc kỹ nhất

### A1. Schema `translated.json` có thêm key `translator`, `transcript_sha256`, `failed_ids` [CP4] — cập nhật sau fix(translation) C3/C5/C7

```json
{
  "source_language": "en",
  "target_language": "vi",
  "translator": {"provider": "ollama", "model": "qwen3:8b"},
  "transcript_sha256": "ab12…",
  "failed_ids": [17],
  "segments": [
    {"id": 1, "start": 0.0, "end": 6.0,
     "source_text": "...", "translated_text": "..."},
    {"id": 17, "start": 80.0, "end": 83.5,
     "source_text": "...", "translated_text": ""}
  ]
}
```

- Các field theo plan §8 giữ nguyên, chỉ **thêm** `translator` để biết
  bản dịch do model nào tạo khi so sánh chất lượng.
- `segments` giữ đúng thứ tự và đủ ID như `transcript.json`; `start`/`end`
  copy nguyên từ transcript.
- `transcript_sha256`: sha256 của nội dung `transcript.json` lúc dịch (C7).
  File cũ (trước fix này) không có key -> coi như `None`, không so sánh
  được nên vẫn SKIP như hành vi cũ.
- `failed_ids`: id các segment không dịch được sau khi chia batch tới còn
  1 dòng vẫn lỗi (C3). Segment đó có `translated_text: ""` dù `source_text`
  không rỗng — **khác** với segment gốc rỗng (A2): CP4 phân biệt bằng cách
  tự kiểm tra `source_text` rỗng hay không nếu cần log riêng, còn hành vi
  "bỏ qua TTS khi `translated_text` rỗng" áp dụng chung cho cả hai trường
  hợp nên **không cần CP4 sửa gì thêm**.
- `translated.json` có thể vẫn tồn tại và **được ghi đè** ở lần chạy sau
  ngay cả khi không `--force`, nếu `failed_ids` khác rỗng (chế độ thử lại)
  hoặc hash transcript đổi. CP4/CP8 không nên giả định file này bất biến
  chỉ vì đã "chạy xong" — chỉ bất biến khi `failed_ids == []` và transcript
  không đổi.

### A2. `translated_text` có thể là chuỗi rỗng [CP4]

Segment có `text` gốc rỗng (Whisper thỉnh thoảng sinh ra) thì không gửi
cho model, `translated_text` = `""`. **CP4 phải bỏ qua segment rỗng**,
không gọi TTS với chuỗi rỗng.

Ngược lại, gốc có chữ mà model trả rỗng thì bị coi là lỗi output (thường
do model gộp hai dòng làm một) → retry.

### A3. `Segment` vẫn nằm ở `app/transcription/whisper.py` [CP4]

Plan §6 đặt ở `models/segment.py`, nhưng CP2 đã để trong `whisper.py` và
CP3 không dời đi. `_read_transcript` được đổi thành `read_transcript`
(public) để stage dịch dùng lại. Đọc `translated.json` thì dùng
`app.translation.translate.read_translated()`.

### A4. Config chỉ chấp nhận section đã có code đọc [CP4]

`config.py` từ chối key/section lạ (gõ nhầm `batchsize` sẽ báo lỗi thay
vì lặng lẽ dùng mặc định). Hệ quả: **CP4 phải thêm section `tts` vào
`app/config.py`** trước khi thêm `tts:` vào `config.yaml`, nếu không mọi
lệnh sẽ báo `Section không hợp lệ: tts`.

---

## B. Prompt và gọi model

### B1. Prompt viết bằng tiếng Anh, không riêng cho phim hoạt hình

- Plan §11 viết prompt tiếng Việt, vai "biên dịch viên phim hoạt hình".
- Đã đổi sang tiếng Anh vì model ~8B bám chỉ dẫn tiếng Anh ổn định hơn;
  vai trò là "voice-over dub" chung, vì video test là sách đọc to chứ
  không phải phim hoạt hình.
- Giữ đủ các quy tắc của plan, thêm một quy tắc: *Whisper cắt câu ra
  nhiều dòng, dòng là mảnh câu thì dịch thành mảnh câu* — vì không được
  gộp dòng (ID là contract).
- `duration` gửi cho model làm tròn 1 chữ số thập phân.
- File: `app/translation/prompt.py`.

### B2. Output bọc trong object `{"translations": [...]}`

Plan §11 dùng mảng trần. Structured output của Ollama/OpenAI ổn định hơn
khi gốc là object. Parser vẫn chấp nhận mảng trần.

### B3. Ngữ cảnh: 5 dòng đã dịch ngay trước batch

Gửi cả câu gốc lẫn bản dịch, ghi rõ "không output lại". Cấu hình qua
`translation.context_size` (0 = tắt).

**Đã thấy trong chạy thật:** 5 dòng không đủ giữ tên nhân vật qua ranh
giới batch (batch id 51–58 dịch "Big Nut Brown Hare" khác hẳn hai batch
trước). Glossary (plan §21, CP9) mới là cách xử lý đúng, không phải
tăng context.

### B4. Tắt chế độ suy nghĩ của qwen3 (`think: false`)

- Bật thì chậm hơn nhiều lần, không cải thiện rõ với câu thoại ngắn.
- Đặt `think: null` trong config để **không gửi** field này, dành cho
  model không hỗ trợ thinking. Chưa kiểm chứng model khác có từ chối
  `think: false` hay không (máy chỉ có `qwen3:8b`).

### B5. `num_ctx: 8192`

Context mặc định của Ollama nhỏ hơn và prompt vượt quá sẽ **bị cắt phần
đầu một cách im lặng** — mất luôn system prompt. Đo trên RTX 3050 6GB:
4096 và 8192 cùng tốc độ (~16–18 token/s), nên chọn 8192 cho an toàn.

### B6. Giới hạn độ dài output: `num_predict = 100 + 80 × số dòng`

Không có trần thì model nhỏ đôi khi lặp vô hạn trong structured output,
treo tới hết timeout (300s) rồi retry y hệt. Có trần thì Ollama dừng với
`done_reason: "length"` → coi là lỗi output → batch được chia nhỏ.
80 token/dòng là ước lượng (tiếng Việt tốn token hơn tiếng Anh + JSON),
chưa đo phân bố thật.

### B7. `temperature: 0.3`

Nếu 0 thì retry cùng prompt gần như ra cùng output lỗi → retry vô dụng.

### B8. Gọi HTTP bằng `urllib`, không thêm dependency

Ollama chỉ cần một POST `/api/chat`, không cần `requests`/`httpx`.

### B9. Host Ollama: config → `OLLAMA_HOST` → localhost

- `OLLAMA_HOST` thường là địa chỉ bind của server (`0.0.0.0:11434`),
  client Windows không kết nối được tới `0.0.0.0` → tự đổi thành
  `127.0.0.1`. Thiếu `http://` thì tự thêm.
- `.env` **không** được tự nạp; `.env.example` đã ghi rõ.

---

## C. Retry, lỗi và resume

### C1. Phân loại lỗi quyết định cách xử lý

| Loại | Ví dụ | Xử lý |
|---|---|---|
| Output sai (`TranslatorOutputError`) | JSON hỏng, thiếu/trùng/lạ ID, bản dịch rỗng, output bị cắt | Retry, vẫn lỗi thì chia đôi batch |
| Kết nối (`TranslatorConnectionError`) | Ollama chưa chạy, timeout, HTTP 5xx | Retry, **không** chia batch (batch nhỏ không làm server sống lại) |
| Cấu hình (`TranslationError`) | HTTP 4xx: sai tên model, option không hỗ trợ | Báo ngay, không retry |

Retry: 3 lần, chờ 2s rồi 5s (plan §24). Số lần cấu hình qua
`translation.max_attempts`, thời gian chờ thì cố định trong code.

### C2. Lỗi output kéo dài → chia đôi batch

Model nhỏ hay gộp/bỏ dòng khi batch dài; batch ngắn thường qua được.
Chia đệ quy: 25 → 12+13 → ... → 1. Mỗi nửa xong được lưu ngay, nửa sau
dùng nửa trước làm ngữ cảnh.

Chi phí xấu nhất: một segment "không dịch nổi" trong batch 25 đi qua 6
tầng lỗi (25→13→7→4→2→1), mỗi tầng 3 lần thử, cộng 5 nửa thành công ≈
**23 lần gọi model** (~15 phút với batch lớn) trước khi dừng.

### C3. [ĐÃ IMPLEMENT — fix(translation) 2026-09-18] Một segment lỗi hẳn → không dừng cả stage

Implement đúng như chốt: `run_batch` khi chia đôi tới còn 1 dòng mà vẫn
`TranslatorOutputError` thì log `id N: bỏ qua sau M lần lỗi (...) — sẽ thử
lại ở lần chạy sau.` rồi `return` (không raise), segment đó không vào
`done` nên không lọt vào partial/ngữ cảnh. `TranslatorConnectionError` và
`TranslationError` cấu hình vẫn dừng stage như cũ (server chết thì dịch
tiếp vô ích).

Cuối stage: nếu **không một** segment có chữ nào dịch được (tức mọi id có
`source_text` đều rơi vào diện lỗi) thì raise `TranslationError` — coi là
model/cấu hình hỏng, không ghi `translated.json`. Ngược lại ghi file bình
thường với `failed_ids` = các id còn lỗi.

Chạy lại không `--force` mà `failed_ids` khác rỗng → chế độ thử lại: chỉ
đưa các id trong `failed_ids` vào `pending`, các id khác lấy thẳng bản
dịch cũ (không gọi lại model, không tính vào batch). Key `translator` ghi
vào `translated.json` cuối cùng giữ **model của lần dịch trước** (đa số
dòng do model đó dịch); nếu model hiện tại đang dùng để thử lại khác model
cũ thì log 1 dòng nêu rõ nhưng vẫn ghi `translator` cũ vào file — tránh
lịch sử dịch "trộn" hai giá trị `translator` gây hiểu nhầm khi so sánh
chất lượng ở CP9.

**[ĐÃ CHỐT: giữ nguyên]** Ngưỡng "toàn bộ lỗi" dùng để phân biệt "một câu khó" với
"model hỏng" là: *không segment có chữ nào* dịch thành công trong cả file
(không phải "quá X% lỗi"). Ở chế độ thử lại, điều kiện này gần như không
bao giờ đúng (vì các id không lỗi lần trước đã có sẵn trong `done`), nên
thực chất chỉ áp dụng cho lần dịch đầu tiên của một episode. Nếu muốn phát
hiện "model hỏng" ngay cả khi đang thử lại (vd model đổi sang bản hỏng),
cần thêm ngưỡng riêng — chưa làm vì ngoài phạm vi spec. User duyệt giữ
nguyên: khi thử lại chỉ có vài câu, và chúng vẫn nằm trong `failed_ids`
kèm cảnh báo của CLI, nên không mất thông tin.

### C4. Tiến trình dở lưu ở `translated.partial.json`

- Ghi lại sau **mỗi** batch (kể cả nửa batch khi chia đôi).
- Gắn `transcript_sha256` + `target_language`. Transcript đổi (vd
  `transcribe --force`) hoặc đổi ngôn ngữ đích → bỏ partial, dịch lại từ
  đầu, có in log.
- Partial hỏng (JSON lỗi) → bỏ, dịch lại từ đầu, có in log.
- Xong hết thì ghi `translated.json` và xoá partial.
- Resume chia batch lại trên **các segment còn thiếu**, nên số batch và
  ranh giới batch lần chạy sau có thể khác lần đầu.

### C5. [ĐÃ IMPLEMENT — fix(translation) 2026-09-18] Đổi model giữa chừng không làm mất partial

`_load_partial` nhận thêm `translator_info` (provider+model **hiện tại**,
không phải model output cuối — xem C3). Partial có key `translator` khác
`translator_info` hiện tại → log
`tiến trình dở dịch bằng <provider cũ>/<model cũ>, đang dùng <provider>/<model> — dịch lại từ đầu.`
rồi trả `{}` (bỏ toàn bộ partial). Partial không có key `translator` (sinh
ra trước fix này) → coi như khớp, resume bình thường như chốt ban đầu.

### C6. `--force` xoá `translated.json` ngay từ đầu

**Phát hiện khi chạy thật, test không bắt được:** bản đầu chỉ xoá partial.
Chạy `--force` bị ngắt giữa chừng thì `translated.json` cũ còn nguyên, lần
chạy lại không `--force` sẽ SKIP và lặng lẽ giữ bản dịch cũ. Đã sửa +
có test hồi quy.

Hệ quả: `--force` bị ngắt thì **bản dịch cũ mất luôn** (chỉ còn partial
mới). Chấp nhận vì bạn đã yêu cầu dịch lại.

### C7. [ĐÃ IMPLEMENT — fix(translation) 2026-09-18] Transcribe lại sau khi đã dịch → tự dịch lại

Đầu `translate_transcript`, khi `translated.json` tồn tại và không
`force`: không có `transcript_sha256` (file cũ) hoặc transcript không còn
tồn tại → SKIP như cũ (không có gì để so sánh). Có hash và khác hash hiện
tại của `transcript.json` → log
`transcript đã thay đổi kể từ lần dịch — dịch lại từ đầu.` rồi xử lý y hệt
`force=True` (xoá `translated.json` + partial, dịch lại toàn bộ). Hash
khớp thì xét tiếp `failed_ids` như C3. Đổi model trong config khi
`translated.json` đã xong (hash khớp, `failed_ids` rỗng) thì vẫn SKIP —
đúng như chốt ban đầu, không tự dịch lại chỉ vì đổi model.

Đã kiểm chứng bằng chạy thật (không chỉ unit test): sửa tay một
`source_text` trong `transcript.json` của bản sao rồi chạy lại `translate`
→ đúng in log "transcript đã thay đổi" và dịch lại đủ 58 segment.

### C8. Ghi file atomic

Ghi ra `*.tmp` rồi `os.replace`. Nếu bị kill giữa lúc ghi, một
`translated.json` cụt sẽ bị coi là "đã xong" và SKIP mãi. CP4 nên dùng
cùng cách cho mọi artifact.

### C9. Kiểm tra thêm ở đầu vào/đầu ra

- Transcript có ID trùng → báo lỗi ngay (validate dựa hoàn toàn vào ID).
- Model trả `"id": "1"` (chuỗi) → coi là lỗi output, không tự ép kiểu.
- **Không** kiểm tra được: model trả đúng ID nhưng lệch nội dung sang
  dòng kế bên, hoặc trả nguyên văn tiếng Anh.

---

## D. Config và CLI

### D1. YAML, thêm `pyyaml` vào dependency

Plan §4/§10 khuyến nghị `config.yaml`, `.gitignore` đã có sẵn dòng này.
`pyyaml` vốn đã được cài gián tiếp qua `huggingface_hub`, nay khai báo
rõ trong `pyproject.toml`. (TOML dùng `tomllib` sẵn có thì không cần
dependency, nhưng đi ngược plan.)

### D2. Thứ tự ưu tiên: flag CLI > config > mặc định trong code

- Flag CLI để mặc định `None` để phân biệt "không truyền" với "truyền
  đúng giá trị mặc định".
- `./config.yaml` được tự đọc nếu có; không có thì dùng mặc định (máy mới
  vẫn chạy `download` được). `--config PATH` trỏ tới file không tồn tại
  thì báo lỗi.
- `--config` đặt được **sau** tên subcommand (dùng parent parser):
  `python -m app translate DIR --config x.yaml`.

### D3. `translation.model` không có mặc định trong code

Theo plan §10. Thiếu thì báo lỗi gợi ý `--model`. Riêng
`whisper.model: medium` vẫn có mặc định trong code (có từ CP2, là kích
cỡ model chứ không phải model đặc thù máy).

### D4. `download`/`transcribe` giờ đọc config

`workspace` và `whisper.model/device/compute_type` lấy từ config. Tiêu
chí "chọn Whisper model từ config" của CP2 trước đây chưa đạt.

### D5. Flag của `translate`

`--translator` (chỉ có `ollama`), `--model`, `--batch-size`,
`--target-lang`, `--force`. Các tham số còn lại (`context_size`,
`num_ctx`, `temperature`, ...) chỉ đặt qua config để CLI gọn.

### D6. Log in kèm `flush`

**Phát hiện khi chạy thật:** stdout bị pipe/ghi ra file log thì Python
buffer, không thấy tiến trình cho tới khi lệnh kết thúc (hoặc mất hẳn nếu
bị kill). Log vẫn dùng `print` như CP1/CP2, chưa có module `logging`.

---

## E. Số liệu đo được (RTX 3050 6GB, `qwen3:8b` Q4_K_M)

- Model chỉ vừa một phần VRAM (~4.2GB/6.5GB), phần còn lại chạy CPU.
- Lần gọi đầu nạp model mất ~37s.
- Batch 25 dòng ≈ 53s; batch 10 dòng ≈ 19s.
- Tập 58 segment (4 phút video) ≈ 2 phút.
- Ước lượng tập 25 phút (~400 segment): **~14–15 phút** dịch.

## F. Việc chưa làm

- `OpenAITranslator` (plan để optional).
- Glossary / quy tắc xưng hô (plan §21, CP9).
- Chưa thử video không phải tiếng Anh.
- Chưa thử batch bị chia đôi trong chạy thật (chỉ có unit test) — lần
  chạy thật không batch nào lỗi output.

## G. Quan sát chất lượng (để dành cho CP9, không sửa ở CP3)

- Lỗi gốc từ Whisper: "Hare" (thỏ) nghe thành "Hair" (tóc) → bản dịch
  "sợi tóc nâu lớn". Dịch tốt mấy cũng không cứu được.
- Dịch sát chữ câu dẫn thoại: "Said big nut brown hair." → "Nói sợi tóc
  nâu lớn." (đúng phải là "Thỏ Nâu Lớn nói.").
- Xưng hô "mình–anh" không hợp quan hệ thỏ mẹ/bố–con.

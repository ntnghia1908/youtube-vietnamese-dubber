# fix(translation) — C3, C5, C7

## Mục tiêu

Hiện thực 3 quyết định đã chốt trong `docs/decisions/checkpoint-3.md`
(C3, C5, C7) để stage dịch chạy được playlist qua đêm: một câu lỗi không
làm dừng cả tập, không trộn model trong partial, tự dịch lại khi transcript
đổi.

## File cần sửa

| Path | Việc cần làm |
|---|---|
| `app/translation/translate.py` | Logic chính (chi tiết dưới) |
| `app/cli.py` | `_cmd_translate`: in cảnh báo khi `result.failed_ids` khác rỗng |
| `tests/test_translation.py` | Thêm test (dùng lại fake translator sẵn có trong file) |
| `docs/decisions/checkpoint-3.md` | Cập nhật A1 (schema), đổi tiêu đề C3/C5/C7 thành `[ĐÃ IMPLEMENT]`, ghi thêm quyết định nhỏ phát sinh |

Không đổi `base.py`, `ollama.py`, `prompt.py`, `config.py`.

## Interface

```python
@dataclass(frozen=True)
class TranslationResult:
    translated_path: Path
    source_language: str
    target_language: str
    segments: list[TranslatedSegment]
    skipped: bool
    failed_ids: list[int] = field(default_factory=list)   # MỚI, theo thứ tự transcript
```

`read_translated()` giữ nguyên chữ ký (CP4 dùng). Nếu cần đọc key mới, thêm
helper private, ví dụ `_read_translated_meta(path) -> dict` trả
`transcript_sha256` (hoặc None), `failed_ids` (mặc định `[]`), `translator`.

## Artifact

`translated.json` — schema mới (chỉ **thêm** key, không đổi key cũ):

```json
{
  "source_language": "en",
  "target_language": "vi",
  "translator": {"provider": "ollama", "model": "qwen3:8b"},
  "transcript_sha256": "ab12…",
  "failed_ids": [17],
  "segments": [
    {"id": 17, "start": 80.0, "end": 83.5, "source_text": "...", "translated_text": ""}
  ]
}
```

File cũ thiếu `transcript_sha256`/`failed_ids` vẫn đọc được (coi như `None`/`[]`).

`translated.partial.json`: giữ nguyên schema (đã có `translator`).

## Hành vi bắt buộc

### C7 — transcript đổi thì tự dịch lại
Đầu `translate_transcript`, khi `translated_path` tồn tại và không `force`:
1. Transcript không tồn tại, hoặc file dịch không có `transcript_sha256`
   → SKIP như cũ.
2. Hash khác sha256 hiện tại của `transcript.json` → log
   `[translate] transcript đã thay đổi kể từ lần dịch — dịch lại từ đầu.`
   rồi xử lý **giống `force=True`** (xoá translated.json + partial).
3. Hash khớp và `failed_ids` rỗng → SKIP như cũ.
4. Hash khớp và `failed_ids` khác rỗng → chế độ thử lại (C3 bên dưới).

Ghi `transcript_sha256` vào `translated.json` ở mọi lần ghi.

### C3 — segment lỗi không dừng stage
- `run_batch`: batch 1 segment vẫn `TranslatorOutputError` sau
  `max_attempts` → **không raise**; thêm id vào tập `failed`, log
  `[translate] id N: bỏ qua sau M lần lỗi (<exc>) — sẽ thử lại ở lần chạy sau.`
  rồi return. Segment lỗi **không** vào `done` (nên không làm ngữ cảnh,
  không lưu vào partial).
- `TranslatorConnectionError` và `TranslationError` cấu hình: **giữ nguyên**
  hành vi dừng stage (server chết thì dịch tiếp vô ích).
- Kết thúc: nếu **mọi** segment có chữ đều lỗi (và có ít nhất 1 segment có
  chữ) → raise `TranslationError` (nhiều khả năng model/cấu hình hỏng),
  giữ partial nếu có, không ghi translated.json.
- Ngược lại ghi `translated.json`: segment lỗi có `translated_text: ""`,
  `failed_ids` = các id lỗi theo thứ tự transcript. Xoá partial như cũ.
- Chế độ thử lại (C7 bước 4): `done` = mọi segment trong translated.json
  **trừ** `failed_ids`; pending = các segment trong `failed_ids`. Log
  `[translate] thử lại K segment lỗi lần trước: id a, b, c`. Chia batch như
  thường. Ghi lại translated.json với `failed_ids` mới. Key `translator`
  giữ **model của file cũ** (đa số dòng do model đó dịch); nếu model hiện
  tại khác thì log một dòng nêu rõ — ghi quyết định này vào decisions.
- `TranslationResult.failed_ids` phản ánh kết quả; khi SKIP thì lấy từ file
  (luôn rỗng ở nhánh SKIP theo logic trên).

### C5 — partial gắn với model
`_load_partial` nhận thêm `translator_info: dict[str, str]`. Nếu partial có
key `translator` và (`provider`, `model`) khác hiện tại → log
`[translate] tiến trình dở dịch bằng <provider>/<model cũ>, đang dùng <provider>/<model mới> — dịch lại từ đầu.`
và trả `{}`. Partial không có `translator` → coi như khớp.

### CLI
`_cmd_translate` sau khi in thông tin hiện có: nếu `result.failed_ids` →
in `[translate] CẢNH BÁO: N segment chưa dịch được (id ...) — chạy lại lệnh để thử lại.`
Exit code **0** (playlist phải chạy tiếp được).

## Test (unittest, fake translator có sẵn trong tests/test_translation.py)

- C3: một id luôn trả output lỗi → không raise, translated.json có
  `failed_ids == [id]`, `translated_text == ""` cho id đó, các id khác dịch đủ.
- C3: mọi segment đều lỗi → raise `TranslationError`, không có translated.json.
- C3: chạy lại khi file có `failed_ids` → fake chỉ nhận đúng các id lỗi;
  lần này thành công → `failed_ids == []`, các bản dịch cũ giữ nguyên.
- C3: `TranslatorConnectionError` liên tục vẫn raise như cũ.
- C5: partial có model khác → bỏ partial, dịch lại toàn bộ.
- C5: partial không có key `translator` → resume bình thường.
- C7: translated.json có hash khác → dịch lại toàn bộ (fake được gọi).
- C7: translated.json không có `transcript_sha256` → SKIP (fake không được gọi).
- C7: hash khớp, `failed_ids` rỗng → SKIP.
- CLI (`tests/test_cli.py`): có `failed_ids` → in cảnh báo, exit 0.
- Toàn bộ test cũ phải vẫn xanh.

Lệnh: `.venv/Scripts/python.exe -m unittest discover -s tests`

## Chạy thật (BẮT BUỘC)

Cần Ollama đang chạy với `qwen3:8b` (kiểm tra `curl -s http://localhost:11434/api/tags`).
Episode gốc: `output/zGuIUytF_6U__Guess How Much I Love You Read Aloud _ Kids Books Read Aloud/`
(58 segment, dịch đủ mất ~2 phút). **Không sửa file trong episode gốc** ngoài bước 1–2;
thử nghiệm trên bản sao.

1. `translate <episode gốc>` → phải SKIP (file cũ chưa có hash).
2. `translate <episode gốc> --force` → translated.json có `transcript_sha256`
   đúng bằng sha256 của transcript.json và `failed_ids: []`.
3. Tạo bản sao `output/_fixtest/` chỉ gồm `transcript.json` + `translated.json`
   (vừa sinh ở bước 2). Sửa tay translated.json của bản sao: `failed_ids: [3, 4]`,
   `translated_text: ""` cho id 3 và 4. Chạy `translate output/_fixtest` →
   log "thử lại 2 segment", chỉ gọi model 1 batch, sau đó `failed_ids: []`,
   id 3–4 có bản dịch tiếng Việt, các id khác giống hệt trước.
4. Chạy lại `translate output/_fixtest` → SKIP.
5. Sửa `source_text` của 1 segment trong `output/_fixtest/transcript.json`
   → chạy lại → log "transcript đã thay đổi", dịch lại đủ 58 segment.
6. Xoá `output/_fixtest/` khi xong.

Trong báo cáo: trích các dòng log chứng minh bước 1, 3, 4, 5 và đoạn JSON
đầu file ở bước 3.

## Ngoài phạm vi

- Không đổi prompt, retry delay, chia đôi batch, config.
- Không làm playlist runner (CP8), không đụng CP4.
- Không commit.

## Điểm phải escalate

- Nếu phải đổi chữ ký `read_translated()` hoặc đổi/xoá key cũ của
  `translated.json`.
- Nếu logic C3 mâu thuẫn với test cũ theo cách không sửa test được mà vẫn
  giữ đúng hành vi đã chốt.

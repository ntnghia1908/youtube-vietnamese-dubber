# Checkpoint 6.5 — Glossary + chọn model dịch: quyết định khi triển khai

Spec: `docs/specs/cp-6.5.md`. Chưa commit. Mục **[CẦN DUYỆT]** là chỗ Opus/user
nên xem lại; mục **[CP7]/[CP8]** là thứ checkpoint sau phải biết.

---

## A. Contract với CP7 / CP8 — đọc kỹ nhất

### A1. `translated.json` thêm đúng một key: `glossary_sha256` [CP7]

```json
{ "source_language": "en", "target_language": "vi",
  "translator": {"provider": "ollama", "model": "gemma3:12b"},
  "transcript_sha256": "cd5d…", "glossary_sha256": "165a…" | null,
  "failed_ids": [], "segments": [ … schema cũ … ] }
```
- `null` khi dịch không glossary. Partial (`translated.partial.json`) cũng có key này.
- `read_translated()`, `TranslatedSegment`, `TranslationResult` **không đổi**; tts/normalize/render
  không cần sửa gì.
- File cũ không có key = `None` = "không glossary".

### A2. `dub` (CP7) phải nạp glossary rồi truyền vào `translate_transcript` [CP7]

```python
from app.translation.glossary import load_effective_glossary
glossary, paths = load_effective_glossary(
    episode_dir, Path(cfg.translation.glossary) if cfg.translation.glossary else None)
translate_transcript(..., glossary=glossary)      # glossary=None -> y hệt CP3
```
- `load_effective_glossary` raise `GlossaryError` (là `TranslationError`) khi file dùng chung không
  tồn tại / YAML hỏng / key lạ → `dub` bắt chung với `TranslationError`, in đường dẫn (thông báo đã có).
- Trả `(None, [])` khi không có file hoặc glossary rỗng. `paths` để in log `glossary : p1, p2`.
- **Glossary đổi ⇒ `translate` tự dịch lại từ đầu, không cần `--force`.** `dub` chạy lại một tập sau
  khi người dùng sửa `glossary.yaml` sẽ dịch lại, `tts` chỉ tổng hợp lại các câu có text đổi (cache
  theo text — đã kiểm: dịch lại 28/58 câu → tts `tổng hợp 28, cache 29`), `normalize`/`render` tự khớp.
- Hash tính trên nội dung đã chuẩn hoá: thêm comment/khoảng trắng vào YAML **không** kích hoạt dịch lại
  (đã kiểm thật: thêm một dòng comment → `SKIP`).
- `dub` **không** nên tự chạy `glossary` (model tạo nháp mà người dùng chưa duyệt sẽ bị dịch luôn).
  Gợi ý: nếu chưa có `<ep>/glossary.yaml` thì in một dòng nhắc chạy `python -m app glossary "<ep>"`.
  [CẦN DUYỆT] — chưa làm vì `dub` thuộc CP7.

### A3. Câu bị `skip` → chuỗi rỗng, chảy qua pipeline như "dòng gốc rỗng" [CP7]

`translated_text == ""`, không nằm trong `failed_ids` ⇒ `tts/manifest.json` `status: "empty"` ⇒
`normalized.json` `status: "silent"` ⇒ `render` chèn im lặng. Đã kiểm với id 58 (Patreon):
`summary.silent == 1`, `missing == 0`.

### A4. Interface `Translator` [CP8 nếu thêm provider]

- `translate_batch(..., glossary: Glossary | None = None)`; provider mới **không phải làm gì** ngoài
  `_complete_json` vì prompt build ở `base.py`. `translate_transcript` chỉ truyền `glossary=` khi có glossary
  → translator giả có chữ ký cũ vẫn chạy.
- `Translator.complete_json(messages, *, schema, item_count)` là wrapper công khai của `_complete_json`.

### A5. `glossary.yaml` [CP8]

5 key: `context`, `characters[{name,vi,aliases,note}]`, `address[{speaker,listener,self,other}]`,
`terms{nguồn: vi}`, `skip[]`. Draft **không** bao giờ điền `skip`. CP8 (glossary cả playlist) có thể
dùng `load_glossary`/`merge_glossaries`/`write_glossary` sẵn có; draft chưa biết glossary dùng chung
(mỗi tập draft độc lập).

---

## B. Quyết định nhỏ

- **B1.** YAML để trống (`terms:` / `characters:` → `None`) coi như rỗng chứ không lỗi; kiểu sai (số, list
  thay vì chuỗi…) mới lỗi. Hệ quả: `terms: {a: 1}` **lỗi** (giá trị phải là chuỗi) — phải quote `"1"`.
- **B2.** `terms` khoá/giá trị rỗng → lỗi (mục vô nghĩa). `skip` chuỗi rỗng và `aliases` rỗng thì bị bỏ.
- **B3.** Alias trùng giữa **hai nhân vật khác nhau**: nhân vật khai báo trước thắng (không báo lỗi).
  Spec chỉ nói trùng trong cùng một nhân vật.
- **B4.** `load_effective_glossary` chỉ có một file thì giữ nguyên, không đi qua `merge_glossaries`
  (merge gộp trùng khoá, sẽ làm hash khác `load_glossary(path).sha256()`).
- **B5.** `write_glossary` tự thêm `# ` cho dòng `header` chưa bắt đầu bằng `#` (dòng trống → `#`) để header
  không thể làm hỏng YAML. Header của draft có sẵn đoạn `skip:` mẫu đã comment sẵn.
- **B6.** `draft_glossary_file`: sao lưu `.bak` **sau** khi model trả kết quả hợp lệ (gọi model lỗi thì
  file cũ và `.bak` cũ nguyên vẹn). SKIP không cần `transcript.json`.
- **B7.** Draft chỉ gửi `title` (không gửi `uploader`: tên kênh dễ bị model nhầm thành nhân vật). CLI
  `glossary --force` in thêm dòng `[glossary] backup : <path>` (ngoài các dòng spec liệt kê).
- **B8.** `glossary` SKIP vẫn phải tạo translator ⇒ cần `translation.model` dù không gọi model. [CẦN DUYỆT]
  nhỏ: tạo translator lười cũng dễ, nhưng test/spec không đòi.
- **B9.** `translate` luôn truyền `glossary=` (có thể `None`) cho `translate_transcript`; chỉ
  `translate_batch` mới có luật "chỉ truyền khi có glossary".
- **B10.** `yaml` chỉ import trong `load_glossary`/`write_glossary`; import `app.translation.*` không kéo
  theo `yaml` (đã kiểm). Lưu ý `load_config` vẫn import `yaml` nếu có `config.yaml`.
- **B11.** Ngưỡng cảnh báo khối glossary dài: `_GLOSSARY_WARN_CHARS = 4000` (hằng trong `translate.py`).
- **B12.** Prompt draft chỉnh **một lần** sau khi đo B1 (xem D3): thêm "note bằng ngôn ngữ đích" và
  "mỗi ô xưng hô chọn MỘT đại từ cụ thể, không viết `a/b`".

## C. Câu chữ khối glossary trong prompt (`glossary_prompt_block`)

- Vòng 0 (đúng như spec): gemma3:12b **đạt** (xem D1); qwen3:8b: hare/tóc ổn nhưng đại từ trượt.
- Vòng 1: đổi mục xưng hô thành ánh xạ tường minh `"I" = "con", "you" = "ba"` + "never any other".
  qwen3:8b: vẫn 0 câu ba–con; giờ luôn dùng `Mình yêu con` (chọn nhầm chiều Ba→Con cho mọi câu).
- Vòng 2: thêm chỉ dẫn suy ra người nói từ câu kể `said <name>`, "hai nhân vật nói xen kẽ". qwen3:8b:
  vẫn 0/13, vẫn `Mình yêu con`.
- Kết luận: hai vòng không cải thiện qwen3:8b ⇒ **giữ câu chữ vòng 0** (đơn giản nhất, gemma3 đã đạt
  với nó). Số liệu vòng 1–2 của qwen3 giống hệt vòng 0 ở mọi tiêu chí khác (tóc 1, CJK 0, failed rỗng).

---

## D. Số liệu đo trên máy này

Video 244 s (4,067 phút); playlist ước tính 10,5 giờ = 630 phút. `temperature 0.3`, `batch_size 25`,
`num_ctx 8192`, `context_size 5`. Mỗi model một bản copy config (`temp/cp65/config-<tag>.yaml`),
`timeout_seconds: 900`, `think: false`.

### D0. Phát hiện quan trọng: Ollama đang chạy 100% CPU [CẦN DUYỆT]

`ollama ps` → `PROCESSOR 100% CPU`; `server.log` mỗi lần khởi động từ 2026-09-18 16:13 tới nay:
`inference compute id=cpu … total_vram="0 B"`. Trong khi ngày 2026-09-18 11:01 vẫn nhận được
`CUDA0 NVIDIA GeForce RTX 3050 … 6.0 GiB` (`libdirs=ollama,cuda_v13`). Nguyên nhân khả dĩ nhất: bản cài
Ollama 0.34.2 bị dở dang — `%LOCALAPPDATA%\Programs\Ollama\lib\ollama\` không còn `cuda_v13`, thư mục
`cuda_v12` chỉ có `cublas*/cudart*` + một file `is-UE8LPLC8XG.tmp` 349 MB (rác của installer) và **không có
`ggml-cuda.dll`**; `nvidia-smi` vẫn thấy card và driver 591.86 (CUDA 13.1) bình thường.
⇒ **Mọi số giây dưới đây là tốc độ CPU thuần**, chậm hơn nhiều so với khi GPU hoạt động. Chưa sửa (ngoài
phạm vi, đụng cài đặt máy). Đề xuất user cài lại Ollama (OllamaSetup.exe mới nhất) rồi đo lại tốc độ —
kết luận "chọn model nào theo giờ dịch" có thể đổi, nhất là với `gemma3:12b` (8,1 GB vừa 6 GB VRAM chỉ
khi offload một phần).

**Đã sửa và đo lại (2026-09-19, Opus).** Cài đè `OllamaSetup.exe` 0.34.2 (chữ ký Ollama Inc.):
`cuda_v12`/`cuda_v13` có đủ `ggml-cuda.dll`, `server.log` nhận `CUDA0 RTX 3050 6.0 GiB`. `gemma3:12b`
(8,9 GB) chạy `63%/37% CPU/GPU` ở `num_ctx 8192`. Cùng config, transcript và `glossary-standard.yaml`
(`temp/cp65/ep-gemma3-12b-gpu/`, log `run-gemma3-12b-gpu.log`):

| | CPU | GPU (37% layer) |
|---|---|---|
| Tổng | 381,75 s | **263,0 s** (nhanh 1,45×) |
| Batch 1 / 2 / 3 | 168,1 / 161,9 / 51,5 s | 110,9 / 117,6 / 34,3 s |
| s / phút video | 93,9 | **64,7** |
| Ước tính playlist 630 phút | ~16,4 h | **~11,3 h** |

Chất lượng vẫn đạt: ba–con 14 (CPU 13), tóc 0, CJK 0, `failed_ids` rỗng, id 58 rỗng; 34/58 câu trùng bản
CPU (do `temperature 0.3`). Tăng tốc chỉ vừa phải vì model không vừa 6 GB VRAM.

### D1. Bảng model (vòng 0, đúng câu chữ prompt hiện tại trong code)

| Chỉ số | baseline (không glossary, qwen3:8b) | qwen3:8b + glossary | gemma3:12b + glossary |
|---|---|---|---|
| segment có `tóc` | 16 | **1** (id 5) | **0** |
| `mình yêu anh` | 13 | 0 | 0 |
| `con yêu ba` / `ba yêu con` (cần ≥ 5) | 0 | **0** ✗ | **13** ✓ |
| CJK | 0 | 0 | 0 |
| `failed_ids` | rỗng | rỗng | rỗng |
| id 58 (Patreon) | dịch ra | `""`, không lỗi | `""`, không lỗi |
| log "chia đôi" / "lỗi" | — | 0 / 0 | 0 / 0 |
| thời gian dịch | — | 270 s | 382 s (lần 2 sau khi thêm term: 385 s) |
| giây / phút video | — | 66,4 | 93,9 |
| **ước tính giờ dịch playlist 10,5 h** | — | **11,6 h** | **16,4 h** |
| `source_text` == `transcript.json`, `glossary_sha256` == `load_effective_glossary(...)[0].sha256()` | — | có | có |
| Đạt tiêu chí Pha A? | — | **Không** (đại từ; 2 vòng chỉnh câu chữ không giúp) | **Đạt** |

qwen3:8b dịch "I love you" thành `Mình yêu em/ba/con` — sửa được hare/tóc nhưng không theo xưng hô
ba–con (không suy ra ai đang nói). gemma3:12b làm đúng cả hai chiều (`Ba đoán xem con yêu ba…`,
`Và ba yêu con đến tận mũi chân ba`).

**Đề xuất (chỉ đề xuất, không sửa `config.yaml`/`config.example.yaml`)**: model `gemma3:12b` — model duy nhất
đạt; chậm hơn qwen3:8b ~1,4×. Giá trị chép vào `config.yaml` nếu user chọn:
```yaml
translation:
  model: gemma3:12b
  timeout_seconds: 900   # batch 25 câu mất 158–174 s trên CPU thuần; 300 chỉ dư ~1,7x
  think: false           # Ollama KHÔNG từ chối think:false với gemma3 — giữ nguyên
  batch_size: 25         # không có lần "chia đôi" nào -> không cần hạ xuống 12
```

### D2. 10 câu nguồn → dịch (id 2, 5, 13, 19, 27, 28, 31, 36, 41, 57)

| id | nguồn (Whisper) | baseline (qwen3:8b, không glossary) | qwen3:8b + glossary | gemma3:12b + glossary |
|---|---|---|---|---|
| 2 | Guess how much I love you. | Đoán xem mình yêu anh bao nhiêu. | Đoán xem mình yêu em bao nhiêu. | Ba đoán xem con yêu ba nhiều như thế nào. |
| 5 | held on tight to big nut brown hairs and hair in long ears. | vừa nắm chặt những sợi tóc nâu to và tóc dài ở tai to. | vừa nắm chặt Thỏ Cha và những sợi tóc dài trên tai. | nắm chặt lấy Thỏ Cha và tai dài. |
| 13 | Big nut brown hair had even longer arms. | Sợi tóc nâu to lại có đôi tay dài hơn. | Thỏ Cha lại có tay dài hơn nữa. | Thỏ Cha có cánh tay dài hơn nữa. |
| 19 | I love you as high as I can reach. | Mình yêu anh cao bằng mức mình có thể đạt tới. | Mình yêu em cao bằng mức mình có thể đạt tới. | Con yêu ba cao như con với tay được. |
| 27 | He tumbled upside down and reached up the tree trunk with his feet. | Anh ấy lật ngược xuống và dùng chân với cây tr trunk. | Anh ấy lật ngửa và dùng chân nhảy lên thân cây. | Nó lộn ngược và dùng chân với tới thân cây. |
| 28 | I love you all the way up to my toes. | Mình yêu anh từ đầu ngón chân đến chân. | Mình yêu em toàn bộ từ chân mình lên. | Con yêu ba đến tận mũi chân con. |
| 31 | Said big nut brown hair, swinging him up over his head. | Nói sợi tóc nâu to, đưa anh ấy lên trên đầu. | Nói Thỏ Cha, quay Thỏ Con lên đầu mình. | Ba nói, bồng nó lên cao trên đầu. |
| 36 | Any hot so high that his ears touch the branches above. | Nóng đến mức tai anh chạm vào cành cây phía trên. | Nhiệt độ cao đến mức tai ba chạm vào cành cây phía trên. | Cao đến nỗi tai nó chạm vào cành cây phía trên. |
| 41 | Cryed little nut brown hair. | Cười sợi tóc nâu nhỏ. | Khóc Thỏ Con. | Con khóc. |
| 57 | I love you right up to the moon and back. | Mình yêu anh đến tận mặt trăng và trở lại. | Mình yêu ba toàn bộ đến tận mặt trăng và về lại. | Con yêu ba đến tận mặt trăng và hơn thế nữa. |

Lỗi còn lại của gemma3 (để user đọc): id 5 mất "hair in long ears" (chỉ còn "tai dài"); id 27/36 dịch nguồn
Whisper sai ("Any hot so high" thực ra "he hopped so high") — lỗi STT, glossary không sửa được (ngoài phạm vi,
cần Whisper `initial_prompt`/model lớn hơn). Bản dịch ở D2 sinh ở vòng 0; dịch lại cùng glossary ra khác
28/58 câu (temperature 0.3) nên số câu cụ thể sẽ không lặp lại y hệt.

### D3. Pha B — `glossary` với gemma3:12b (`temp/cp65/config-gemma3-12b.yaml`)

| Bước | Kết quả |
|---|---|
| B1 tạo nháp | 126 s (lần đầu, đã gồm nạp model), exit 0. `glossary.yaml` parse được, header tiếng Việt, 2 character, 2 address, 1 term, `skip: []` |
| B2 chạy lại | `SKIP` trong **0,19 s**; `server.log` không có request `/api/chat` mới |
| B3 `--force` | 105 s; `glossary.yaml.bak` **giống hệt** nháp B1 (`diff` không khác); file mới là nháp mới |
| B4 `translate` (đã dịch) | `SKIP` trong 0,21 s |
| B5 `tts` + `normalize` | 41 s. `tts/manifest.json` id 58 `status: "empty"`; `normalized.json` `summary.silent == 1`, `missing == 0` (stretched 5, too_long 1 = id 8 như CP6) |
| B6 thêm term `hare: thỏ rừng` | log `glossary đã thay đổi kể từ lần dịch — dịch lại từ đầu.`, 385 s, `glossary_sha256` `165a…` → `e2ee…` |

**Chất lượng nháp B1** (chưa chỉnh prompt draft): bắt được `Little Nut Brown Hair` là `hare` (đặt
`name: Little Nut Brown Hare`, alias `Little Nut Brown Hair`) — tốt; nhưng bỏ sót alias `big nut brown hairs`, đặt
`vi: Thỏ Nâu Nhỏ/Lớn` (không phải "Thỏ Con/Cha" như user gọi), `note` bằng tiếng Anh, và xưng hô sai:
`self: Tôi`, `other: Ba/Mẹ` (viết hai lựa chọn trong một ô).
**Sau khi chỉnh prompt draft (B12), nháp B3**: `vi: Thỏ Con Nâu / Thỏ Bố Nâu`, `note` tiếng Việt, xưng hô
`con`/`bố` (đúng cặp, một đại từ mỗi ô), alias vẫn chỉ `Little Nut Brown Hair` / `big nut brown hair`, `terms: {}`,
context ổn. Vẫn cần người sửa: user muốn `ba` (miền Nam) thay `bố`, `Thỏ Con/Thỏ Cha`, thêm alias `…hairs`, thêm `skip`.
Draft không parse hỏng, `characters` không rỗng ⇒ không phải escalate.

Lệnh mở/kiểm artifact: `temp/cp65/ep-draft/glossary.yaml`, `.bak`; `temp/cp65/ep-gemma3-12b/{translated,normalized}.json`.

---

## E. Chưa làm / để user quyết

- ~~Chọn model dịch cuối cùng~~ **ĐÃ CHỐT `gemma3:12b`** (2026-09-19, user): `config.example.yaml` và
  `config.yaml` cục bộ đặt `model: gemma3:12b`, `timeout_seconds: 900`. Lý do: model duy nhất qua tiêu chí
  ba–con (D1); tốc độ GPU ~64,7 s/phút video (~11,3 h/playlist) chấp nhận được khi chạy qua đêm. Chưa đo
  `num_ctx 4096` hay `gemma3:4b` (nhanh hơn nhưng chưa biết chất lượng).
- ~~Sửa Ollama để dùng GPU~~ **XONG** (D0): cài đè OllamaSetup 0.34.2, đã đo lại trên GPU.
- `docs/SETUP.md` (`ollama pull qwen3:8b`) và README còn nhắc `qwen3:8b` — cập nhật ở commit docs riêng.
- Tinh chỉnh `glossary.yaml` chuẩn cho episode thật rồi chạy `translate`/`tts`/`normalize`/`render` để nghe.
- `dub` tự nhắc/tạo glossary (A2) — thuộc CP7.
- Lỗi STT ("Any hot" ≠ "he hopped") — cần Whisper `initial_prompt`/`large-v3` (ngoài phạm vi CP6.5).

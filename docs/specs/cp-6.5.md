# CP6.5 — Glossary + bản mô tả truyện cho bước dịch

## Mục tiêu
Cho bước dịch biết ngữ cảnh mà nó không tự suy ra được: tên nhân vật (và các
cách Whisper nghe sai), quan hệ/xưng hô, thuật ngữ cố định. App **tạo nháp**
`glossary.yaml` bằng model, người dùng **sửa tay**, `translate` đọc file đó.
Plan §21 + CP9 mục 3–4 (kéo lên trước CP7 vì đây là nguyên nhân chính của
bản dịch sai).

Bằng chứng từ episode thật (`Guess How Much I Love You`): Whisper chép
"Little Nutbrown **Hare**" thành `Little Nut Brown Hair` nên bản dịch ra
`sợi tóc nâu to/nhỏ` (id 5, 6, 13, 22, 26…), và mọi câu "I love you" ra
`mình yêu anh` thay vì ba–con (id 2, 14, 19, 28…).

## Quyết định đã chốt (đọc trước khi code)
1. **Hai lớp tác dụng**: (a) *sửa nguồn* — thay các `aliases` (cách nghe sai)
   bằng tên chuẩn `name` trong text **gửi cho model** (không sửa
   `transcript.json`, không sửa `source_text` trong `translated.json`);
   (b) *prompt* — thêm khối ngữ cảnh/nhân vật/xưng hô/thuật ngữ vào system
   prompt. Không thay model dịch, không sửa STT (Whisper `initial_prompt` là
   ngoài phạm vi).
2. **Draft không bao giờ ghi đè công sức của người dùng**: `glossary`
   SKIP nếu `<ep>/glossary.yaml` đã có; `--force` thì lưu bản cũ ra
   `glossary.yaml.bak` rồi mới ghi. Model **không** tự điền mục `skip`
   (bỏ câu = mất thoại, chỉ người dùng được quyết).
3. **Glossary đổi → `translate` tự dịch lại từ đầu** (giống hash transcript
   đổi, C7 của CP3), không cần `--force`: sửa glossary là để dịch lại, bắt
   người dùng nhớ `--force` thì "không thấy gì thay đổi". Hash tính trên nội
   dung đã chuẩn hoá (sửa comment/khoảng trắng YAML không kích hoạt).
   Downstream (`tts` cache theo text, `normalize`, `render`) tự tính lại
   đúng các câu đổi.
4. **Gộp hai tầng**: glossary dùng chung (config `translation.glossary` /
   flag `--glossary`, dành cho cả series/playlist) + `<ep>/glossary.yaml`
   (ghi đè theo từng tập). Không có file nào → hành vi y hệt hiện tại
   (prompt, hash, output không đổi một byte).
5. **Tương thích ngược interface**: `Translator.translate_batch(...)` nhận
   thêm kwarg `glossary` mặc định `None`, và `translate_transcript` **chỉ
   truyền** `glossary=` khi có glossary — các `FakeTranslator` trong test
   hiện có (chữ ký cố định) vẫn chạy nguyên.
6. **Xưng hô giọng miền Nam: ba – con** (user chốt). Tên nhân vật giữ theo cách
   user gọi: `Thỏ Cha`/`Thỏ Con`; đại từ trong `address` là `ba`/`con`. Muốn
   đổi (bố/mẹ, má…) chỉ cần sửa glossary, không đụng code.
7. **Dùng model dịch lớn hơn — chọn bằng đo thực tế trên máy này**, không
   chọn theo lý thuyết. Máy: RTX 3050 **6 GB VRAM**, 31,8 GB RAM; model lớn
   hơn ~5 GB sẽ chạy một phần trên CPU nên **tốc độ** quyết định (playlist
   ~10,5 giờ video). Model là config (`translation.model`), spec này không
   đổi mặc định trong code; chỉ khuyến nghị sau khi đo (xem "Chạy thật", Pha A).
   Không thử model dense 27B/32B: chậm hàng chục lần, không khả thi cho
   playlist; user cũng loại `qwen3:30b` (19 GB) nên chỉ so `gemma3:12b` với
   `qwen3:8b`.

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|
| `app/translation/glossary.py` (mới) | Model dữ liệu, parse/validate YAML, gộp, hash, sửa alias, skip, ghi YAML |
| `app/translation/glossary_draft.py` (mới) | Tạo nháp bằng LLM + ghi file (SKIP/`.bak`) |
| `app/translation/prompt.py` | `build_messages(..., glossary=None)` + `glossary_prompt_block()` |
| `app/translation/base.py` | `translate_batch(..., glossary=None)`; thêm `Translator.complete_json()` công khai |
| `app/translation/translate.py` | Nhận `glossary`; sửa alias, skip, hash vào `translated.json`/partial, rule resume |
| `app/config.py` | `TranslationConfig.glossary`, `.glossary_max_chars` |
| `app/cli.py` | Subcommand `glossary`; `translate --glossary`; cập nhật docstring đầu file |
| `config.example.yaml` | Hai key mới, có comment |
| `tests/test_glossary.py`, `tests/test_glossary_draft.py` (mới), `tests/test_translation.py`, `tests/test_config.py`, `tests/test_cli.py` | Xem mục Test |
| `docs/decisions/checkpoint-6.5.md` | Quyết định + mục A contract cho CP7/CP8 + số liệu đo |

Không sửa `app/tts/*`, `app/synchronization/*`, `app/audio/*`, `README.md`,
`CLAUDE.md`, `docs/SETUP.md` (Opus cập nhật docs sau).

## Interface

### `app/translation/glossary.py`
```python
GLOSSARY_FILENAME = "glossary.yaml"

class GlossaryError(TranslationError): ...      # import TranslationError từ app.translation.base

@dataclass(frozen=True)
class Character:
    name: str                       # tên chuẩn ở ngôn ngữ nguồn
    vi: str                         # tên/cách gọi tiếng Việt (bỏ trống -> = name)
    aliases: tuple[str, ...] = ()   # các cách Whisper nghe sai
    note: str = ""

@dataclass(frozen=True)
class Address:                      # YAML: speaker / listener / self / other
    speaker: str
    listener: str
    self_term: str                  # speaker tự xưng, vd "con"
    other_term: str                 # speaker gọi listener, vd "ba"

@dataclass(frozen=True)
class Glossary:
    context: str = ""
    characters: tuple[Character, ...] = ()
    address: tuple[Address, ...] = ()
    terms: tuple[tuple[str, str], ...] = ()   # (nguồn, tiếng Việt), giữ thứ tự
    skip: tuple[str, ...] = ()

    def is_empty(self) -> bool: ...
    def to_dict(self) -> dict[str, Any]:
        """Đủ 5 key, kể cả rỗng: {"context", "characters": [{"name","vi","aliases","note"}],
        "address": [{"speaker","listener","self","other"}], "terms": {nguồn: vi}, "skip": [...]}"""
    def sha256(self) -> str:
        """sha256 của json.dumps(to_dict(), sort_keys=True, ensure_ascii=False)."""
    def apply_aliases(self, text: str) -> str: ...
    def should_skip(self, text: str) -> bool: ...

def parse_glossary(data: Any, *, source: str = "glossary") -> Glossary
def load_glossary(path: Path) -> Glossary
def merge_glossaries(base: Glossary, override: Glossary) -> Glossary
def load_effective_glossary(
    episode_dir: Path, shared_path: Path | None,
) -> tuple[Glossary | None, list[Path]]
def write_glossary(glossary: Glossary, path: Path, *, header: str) -> None
```
- **Parse/validate (nghiêm như `parse_config`)**: `data` là `None`/rỗng → `Glossary()`;
  không phải mapping → `GlossaryError`. Key cấp cao hợp lệ: `context`
  (str), `characters` (list[mapping]), `address` (list[mapping]), `terms`
  (mapping str→str), `skip` (list[str]). Key lạ ở **mọi** cấp → lỗi nêu key
  hợp lệ. `characters[].name` bắt buộc, không rỗng; `vi` tuỳ chọn (rỗng →
  `name`); `aliases` list[str]; `note` str. `address[]` bắt buộc đủ 4 key
  `speaker/listener/self/other`, đều str không rỗng. Chuỗi được `strip()`;
  `aliases`/`skip` rỗng thì bỏ; `aliases` trùng `name` hoặc trùng nhau
  (không phân biệt hoa thường) thì bỏ. Sai kiểu (số, list thay vì str…) →
  `GlossaryError` có `source` (đường dẫn file) trong thông báo.
- `load_glossary`: `yaml.safe_load` (thiếu `pyyaml` hoặc YAML hỏng →
  `GlossaryError`, như `load_config`); file không tồn tại → `GlossaryError`.
- **`apply_aliases(text)`**: MỘT regex ghép tất cả alias (xếp alias **dài
  trước**), `(?<!\w)(?:a1|a2|…)(?!\w)`, `re.IGNORECASE`, `re.escape` từng
  alias; thay bằng `name` của nhân vật sở hữu alias (tra theo `casefold()`).
  Một lượt `re.sub` duy nhất — không quét lại phần vừa thay. Không có alias
  nào → trả nguyên `text`. Không khớp giữa từ (`Hairy` không bị alias `Hair`
  ăn).
- **`should_skip(text)`**: có ít nhất một chuỗi `skip` nằm trong `text`
  (substring, không phân biệt hoa thường).
- **`merge_glossaries(base, override)`**: `context` — override nếu không
  rỗng, ngược lại base; `characters` — khoá `name.casefold()`, cùng khoá thì
  entry của override thay cả entry (thứ tự: base trước, mục mới của override
  sau); `address` — khoá `(speaker, listener)` casefold, cùng luật; `terms`
  — khoá casefold, override thắng; `skip` — hợp, bỏ trùng, giữ thứ tự.
- **`load_effective_glossary`**: `shared_path` được chỉ định mà không tồn tại
  → `GlossaryError`; `<episode_dir>/glossary.yaml` không tồn tại → bỏ qua
  (không lỗi). Gộp shared rồi tới episode. Trả `(None, [])` nếu không có file
  nào **hoặc** kết quả gộp `is_empty()` (file rỗng không đổi hành vi dịch);
  ngược lại `(glossary, [các Path đã dùng, đúng thứ tự gộp])`.
- **`write_glossary`**: `yaml.safe_dump(g.to_dict(), allow_unicode=True,
  sort_keys=False, default_flow_style=False, width=100)` đứng sau `header`
  (mỗi dòng header bắt đầu `# `); ghi atomic (`.tmp` + `os.replace`, utf-8).
  Ghi rồi `load_glossary` phải ra `Glossary` bằng nhau (round-trip).

### `app/translation/prompt.py`
```python
def glossary_prompt_block(glossary: Glossary, target_language: str) -> str
def build_messages(lines, *, context, source_language, target_language,
                   glossary: Glossary | None = None) -> list[dict[str, str]]
```
- `glossary` là `None` **hoặc** `is_empty()` → `build_messages` trả **đúng như cũ**
  (test hiện có không đổi). Ngược lại system prompt = prompt cũ + `"\n\n"` + khối.
- Import `Glossary` chỉ để type hint (`TYPE_CHECKING`) — tránh vòng import
  vì `glossary.py` import `base.py`, `base.py` import `prompt.py`.
- Khối (tiếng Anh, bỏ hẳn mục nào rỗng; `{tgt}` = `language_name(target)`):
  ```
  Story context (written by the user; follow it over your own guesses):
  <context>

  Characters (the transcript comes from speech-to-text and may misspell names; use these):
  - <name> -> "<vi>" (<note>). Often misheard as: "<alias1>", "<alias2>".

  Forms of address (use exactly these {tgt} pronouns):
  - When <speaker> speaks to <listener>: refers to self as "<self>", calls the listener "<other>".

  Fixed terms (always translate like this):
  - "<nguồn>" -> "<vi>"
  ```
  Câu chữ chi tiết được phép tinh chỉnh để đạt tiêu chí "Chạy thật", nhưng
  giữ cấu trúc 4 mục và bỏ mục rỗng.

### `app/translation/base.py`
```python
def translate_batch(self, lines, *, context, source_language, target_language,
                    glossary: Glossary | None = None) -> dict[int, str]   # chuyển tiếp vào build_messages

def complete_json(self, messages: list[dict[str, str]], *, schema: dict[str, Any],
                  item_count: int) -> str:
    """Wrapper công khai của _complete_json cho các việc không phải dịch (tạo glossary).
    item_count chỉ để provider đặt trần token output (Ollama: 100 + 80*item_count)."""
```

### `app/translation/translate.py`
```python
def translate_transcript(..., glossary: Glossary | None = None, ...)   # thêm kwarg, còn lại giữ nguyên
```
- `glossary_sha256 = glossary.sha256() if glossary else None` (glossary rỗng
  đã bị `load_effective_glossary` đổi thành `None`; hàm này coi `is_empty()`
  như `None` cho chắc).
- **Sửa alias**: `SourceLine.text` và `ContextLine.text` đều đi qua
  `glossary.apply_aliases`. `translated.json`/partial vẫn ghi `source_text`
  gốc từ transcript.
- **Skip**: segment có `glossary.should_skip(seg.text)` được điền bản dịch `""`
  cùng chỗ với luật "dòng gốc rỗng" hiện có (`done.setdefault(seg.id, "")`),
  không gọi model, không nằm trong `failed_ids`. `log` số câu bị bỏ.
- **Ghi `glossary_sha256`** (`str | None`) vào `translated.json` **và** partial.
  `_read_translated_meta` đọc `data.get("glossary_sha256")`.
- **Rule resume** (thêm nhánh, sau nhánh transcript đổi):
  ```
  transcript_sha256 None hoặc không còn transcript -> SKIP (như cũ, không đổi)
  transcript đổi                                    -> dịch lại (như cũ)
  meta["glossary_sha256"] != glossary_sha256        -> log "[translate] glossary đã thay đổi kể từ lần dịch — dịch lại từ đầu."; force = True
  không có failed_ids                               -> SKIP
  có failed_ids                                     -> thử lại đúng các id lỗi (như cũ)
  ```
  File cũ chưa có key `glossary_sha256` + không glossary (`None == None`) →
  SKIP như trước. File cũ + glossary mới xuất hiện → dịch lại.
- **Partial**: `_load_partial(..., glossary_sha256)`; `data.get("glossary_sha256")
  != glossary_sha256` → log "glossary đã thay đổi — bỏ tiến trình dịch dở cũ" và
  trả `{}` (partial cũ không có key + glossary `None` → khớp).
- **Cảnh báo khối quá dài**: `len(glossary_prompt_block(...)) > 4000` → `log`
  cảnh báo "glossary dài, có thể chiếm hết translation.num_ctx", không lỗi.
- Chỉ truyền `glossary=glossary` vào `translator.translate_batch` khi
  `glossary is not None`.

### `app/translation/glossary_draft.py`
```python
GLOSSARY_SCHEMA: dict[str, Any]          # JSON schema cho structured output (xem dưới)
_DRAFT_ITEM_COUNT = 40                   # -> num_predict ~3300 token

@dataclass(frozen=True)
class GlossaryDraftResult:
    glossary_path: Path
    glossary: Glossary
    skipped: bool
    backup_path: Path | None

def build_draft_messages(*, title: str, transcript_text: str,
                         source_language: str, target_language: str) -> list[dict[str, str]]

def generate_glossary_draft(
    transcript_path: Path, translator: Translator, *,
    metadata_path: Path | None, target_language: str,
    max_chars: int = 8000, max_attempts: int = 3,
    log: Callable[[str], None] = print, sleep: Callable[[float], None] = time.sleep,
) -> Glossary

def draft_glossary_file(
    episode_dir: Path, translator: Translator, *,
    target_language: str, max_chars: int = 8000, max_attempts: int = 3,
    force: bool = False, log=print, sleep=time.sleep,
) -> GlossaryDraftResult
```
- Tái sử dụng: `read_transcript` (`app/transcription/whisper.py:98`),
  `TRANSCRIPT_FILENAME`; `METADATA_FILENAME` (`app/youtube/download.py:18`,
  key `title`, `uploader`); `_RETRY_DELAYS`-kiểu backoff 2s/5s như
  `translate.py` (copy hằng, không import private).
- **Văn bản gửi model**: `title` (thiếu/`metadata.json` lỗi → chuỗi rỗng, không
  lỗi) + `"\n".join(seg.text)` của các segment, **cắt ở ranh giới dòng** tới
  `max_chars` ký tự; bị cắt thì `log` cảnh báo "chỉ dùng phần đầu transcript,
  bổ sung glossary bằng tay nếu cần".
- **Prompt draft** (tiếng Anh): nhiệm vụ = soạn "translation brief" cho bản
  lồng tiếng từ {src} sang {tgt}; nhắc **transcript là speech-to-text nên tên
  riêng hay bị nghe sai (vd "hare" thành "hair") — nếu một tên trông như nghe
  sai, ghi các dạng sai vào `aliases` và dạng đúng vào `name`**; không bịa nhân
  vật không có trong transcript; `vi` = tên tiếng Việt dùng khi lồng tiếng;
  `address` = với mỗi cặp nhân vật nói chuyện với nhau, chọn cặp đại từ tiếng
  Việt tự nhiên theo quan hệ (ba/má–con, bạn bè, …); `context` = 1–2 câu về
  thể loại, đối tượng khán giả, giọng kể.
- **`GLOSSARY_SCHEMA`** (object, cả 4 key required): `context` string;
  `characters` array of `{name, vi, aliases: array[string], note}`; `address`
  array of `{speaker, listener, self, other}`; `terms` array of `{source, vi}`
  (dạng list vì JSON schema cho dict khoá tuỳ ý khó ép). **Không có `skip`.**
- Xử lý output: `json.loads` → `terms` list → dict → **làm sạch** (bỏ character
  không có `name`, tối đa 30 character/60 term/30 address) → `parse_glossary`.
  Lỗi JSON/validate (`TranslatorOutputError`, `GlossaryError`) → thử lại tới
  `max_attempts`; `TranslatorConnectionError` → `sleep(2 rồi 5)` rồi thử lại;
  hết lượt → raise `GlossaryError` nêu lỗi cuối.
- **`draft_glossary_file`**: `<ep>/glossary.yaml` đã tồn tại và `not force` →
  `skipped=True`, `glossary=load_glossary(...)` (file hỏng → `GlossaryError`),
  **không** gọi model. `force` và file tồn tại → `shutil.copy2` sang
  `glossary.yaml.bak` (ghi đè bản `.bak` cũ) rồi ghi mới. Ghi bằng
  `write_glossary` với header tiếng Việt nêu ý nghĩa 5 mục (`context`,
  `characters`, `address`, `terms`, `skip`), câu "bản NHÁP do model tạo, hãy sửa
  trước khi chạy `translate`", và ví dụ một mục `skip` (đặt comment). Thiếu
  `transcript.json` → `GlossaryError` gợi ý chạy `transcribe`.

## Artifact
- Vào: `<ep>/transcript.json`, `<ep>/metadata.json` (tuỳ chọn) cho `glossary`;
  thêm `<ep>/glossary.yaml` và/hoặc file dùng chung cho `translate`.
- Ra:
  - `<ep>/glossary.yaml` (sinh bởi `glossary`, người dùng sửa):
    ```yaml
    context: Truyện thiếu nhi đọc to, giọng kể ấm áp, câu ngắn.
    characters:
    - name: Little Nutbrown Hare
      vi: Thỏ Con
      aliases:
      - Little Nut Brown Hair
      note: thỏ con, nhân vật chính
    address:
    - speaker: Little Nutbrown Hare
      listener: Big Nutbrown Hare
      self: con
      other: ba
    terms: {}
    skip: []
    ```
  - `<ep>/glossary.yaml.bak` (chỉ khi `glossary --force` đè file đã có).
  - `<ep>/translated.json`: schema cũ + **một key mới** `"glossary_sha256":
    "<hex>" | null`. `read_translated()` và các stage sau (CP4/5/6) không đổi.

## Config
```yaml
translation:
  # glossary: ./glossary.yaml   # glossary dùng chung (vd cả series), gộp với <episode>/glossary.yaml
  glossary_max_chars: 8000      # ký tự transcript tối đa gửi model khi tạo nháp (video zh/ja: giảm ~ một nửa)
```
- `TranslationConfig.glossary: str | None = None` (`(str, None)` trong
  `_TRANSLATION_TYPES`), `glossary_max_chars: int = 8000` (`(int,)`,
  kiểm `_positive`). Không kiểm file tồn tại lúc parse config (kiểm lúc dùng).
- CLI:
  - `python -m app glossary EPISODE_DIR [--model M] [--max-chars N] [--force]`
    (+ `--config`). Backend/host/… lấy từ `config.translation`;
    `--model`/`--max-chars` ghi đè config (mặc định `None`). Target language
    = `config.target_language`.
  - `python -m app translate EPISODE_DIR [--glossary PATH] …`: `--glossary`
    ghi đè `translation.glossary` (chỉ là tầng dùng chung; `<ep>/glossary.yaml`
    luôn tự nhận nếu có).
- `_cmd_glossary` in:
  ```
  [glossary] glossary   : <ep>/glossary.yaml
  [glossary] characters : 2
  [glossary] address    : 2
  [glossary] terms      : 0
  [glossary] LƯU Ý: đây là bản nháp do model tạo — mở file, sửa tên nhân vật/xưng hô cho đúng rồi chạy `python -m app translate "<ep>"`.
  ```
  SKIP thì in `[glossary] SKIP: glossary.yaml đã tồn tại (dùng --force để tạo
  lại; bản cũ được lưu ở glossary.yaml.bak).` rồi vẫn in bốn dòng đầu.
  `TranslationError`/`GlossaryError` → `[glossary] LỖI: …` ra stderr, exit 1.
- `_cmd_translate`: `load_effective_glossary` chạy **trong** khối `try`
  bắt `TranslationError` (đã bao `GlossaryError`); có glossary thì in thêm
  `[translate] glossary : <path1>, <path2>` (không có thì **không** in gì mới —
  output cũ giữ nguyên).

## Hành vi bắt buộc
- Không glossary (không flag, không config, không `<ep>/glossary.yaml`, hoặc
  file rỗng) → `translate` chạy y hệt CP3: prompt giống hệt, không truyền kwarg
  `glossary`, `translated.json` chỉ thêm `"glossary_sha256": null`.
- Sửa alias không phân biệt hoa thường, theo ranh giới từ; thay bằng `name` đúng
  hoa thường như trong glossary. Không đụng `transcript.json`.
- `glossary` không gọi model khi SKIP; `--force` không bao giờ mất bản cũ.
- Không glossary → không import `yaml` khi `translate` (import cục bộ trong
  `load_glossary`/`write_glossary`) để lệnh cũ không phụ thuộc thêm.
- Mọi hàm có `log`; `translate`/`glossary` CLI truyền `flush=True` như các lệnh khác.

## Test (unittest, mock dịch vụ ngoài)
`tests/test_glossary.py`:
- `parse_glossary`: đủ mục; `None`/`{}` → rỗng; key lạ ở cấp cao/`characters[]`/
  `address[]` → lỗi; sai kiểu; thiếu `name`; `address` thiếu một trong 4 key;
  `vi` rỗng → = `name`; `aliases` trùng `name`/trùng nhau bị bỏ.
- `apply_aliases`: không phân biệt hoa thường; ranh giới từ (`Hairy` không đổi,
  `hair,` đổi); alias dài thắng alias ngắn (`Big Nut Brown Hair` vs `Nut Brown
  Hair`); một lượt (kết quả không bị thay lần hai); không alias → nguyên văn.
- `should_skip`: substring, không phân biệt hoa thường; danh sách rỗng → False.
- `merge_glossaries`: override thay cả entry cùng `name`; thêm mục mới; `context`
  rỗng không đè; `terms`/`skip` gộp; thứ tự ổn định.
- `sha256`: ổn định khi đổi thứ tự key YAML/comment/khoảng trắng; đổi một `vi`
  → hash khác.
- `load_effective_glossary`: không file → `(None, [])`; chỉ episode; chỉ shared;
  cả hai (gộp, đúng thứ tự path); `shared_path` không tồn tại → `GlossaryError`;
  file rỗng → `(None, [])`; YAML hỏng → `GlossaryError` nêu đường dẫn.
- `write_glossary`/`load_glossary` round-trip (có tiếng Việt, alias, address).

`tests/test_glossary_draft.py` (translator giả có `complete_json` trả JSON dựng sẵn):
- Draft hợp lệ → `Glossary` đúng, `terms` list → dict, `skip` luôn rỗng dù model
  trả thêm; làm sạch (character không tên bị bỏ, vượt trần bị cắt).
- JSON hỏng/thiếu key → thử lại đúng `max_attempts` lần rồi `GlossaryError`;
  lần 2 hợp lệ → thành công; `TranslatorConnectionError` → gọi `sleep(2)`, `sleep(5)`.
- Prompt chứa title và text transcript; transcript dài hơn `max_chars` bị cắt ở
  ranh giới dòng + `log` cảnh báo; thiếu `metadata.json` → vẫn chạy.
- `draft_glossary_file`: chưa có file → ghi (header có ý nghĩa 5 mục); có sẵn +
  không `force` → `skipped`, model **không** được gọi; `force` → `.bak` giữ đúng
  nội dung cũ, file mới là draft; thiếu transcript → `GlossaryError`.

`tests/test_translation.py` (thêm case; **không** sửa case cũ):
- `build_messages`: glossary `None`/rỗng → giống hệt output cũ; có glossary →
  system prompt chứa khối, đủ 4 mục; mục rỗng bị bỏ.
- `translate_transcript` với glossary: `SourceLine.text` và `ContextLine.text` đã
  sửa alias; `translated.json` giữ `source_text` gốc và có `glossary_sha256`;
  câu `skip` không tới model, bản dịch `""`, không nằm trong `failed_ids`;
  `translate_batch` nhận `glossary=`; **không** glossary thì không nhận kwarg
  (FakeTranslator cũ chạy được).
- Resume: cùng glossary → SKIP (không gọi model); đổi một `vi` → log "glossary
  đã thay đổi" và dịch lại toàn bộ; file cũ không có key + không glossary → SKIP;
  file cũ không có key + glossary mới → dịch lại; glossary bị xoá (file trước có
  hash) → dịch lại; partial khác `glossary_sha256` bị bỏ.

`tests/test_config.py`: `translation.glossary` mặc định `None`, đọc được str,
sai kiểu → `ConfigError`; `glossary_max_chars` mặc định 8000, ≤ 0 → `ConfigError`.
`tests/test_cli.py`: `glossary --help`; `glossary` in đủ dòng + LƯU Ý (patch
`draft_glossary_file`); SKIP in đúng câu; `GlossaryError` → exit 1 + `[glossary] LỖI`;
`translate --glossary` file không tồn tại → exit 1; `translate` có glossary →
in dòng `[translate] glossary :`; không glossary → output không có dòng đó.

## Chạy thật (BẮT BUỘC)
Cần Ollama đang chạy (`ollama list` hiện chỉ có `qwen3:8b`, 5,2 GB). Làm trên
**bản sao** trong `temp/` (đã gitignore) để không đè `translated.json`/
`output_vi.mp4` của episode gốc. **Không sửa `config.yaml` gốc**; mỗi model
dùng một bản copy config truyền bằng `--config`.
```bash
EP="output/zGuIUytF_6U__Guess How Much I Love You Read Aloud _ Kids Books Read Aloud"
PY=.venv/Scripts/python.exe
```
Khối YAML glossary chuẩn (dùng ở Pha A — xưng hô miền Nam ba – con, đừng đổi):
```yaml
context: >-
  Truyện thiếu nhi (sách đọc to) "Guess How Much I Love You": hai nhân vật chính
  là Thỏ Cha và Thỏ Con (hai con thỏ rừng), giọng kể ấm áp, câu ngắn, dễ nghe cho trẻ nhỏ.
characters:
  - name: Little Nutbrown Hare
    vi: Thỏ Con
    aliases: [Little Nut Brown Hair, little nut brown hare, little nut brown hairs]
    note: thỏ con, nhân vật chính; là con thỏ rừng (hare), không phải "hair" (tóc)
  - name: Big Nutbrown Hare
    vi: Thỏ Cha
    aliases: [Big Nut Brown Hair, big nut brown hairs, big nut brown hare]
    note: thỏ cha (thỏ lớn)
address:
  - {speaker: Little Nutbrown Hare, listener: Big Nutbrown Hare, self: con, other: ba}
  - {speaker: Big Nutbrown Hare, listener: Little Nutbrown Hare, self: ba, other: con}
terms: {}
skip:
  - support Storybook Nanny on Patreon
```

### Pha A — chọn model dịch (user yêu cầu dùng model lớn hơn)
Hai model, cùng transcript + cùng glossary chuẩn:

| tag Ollama | dung lượng tải | vai trò |
|---|---|---|
| `qwen3:8b` | có sẵn | mốc so sánh (nay có glossary) |
| `gemma3:12b` | ~8,1 GB | ứng viên chính: đa ngữ mạnh, vừa sức máy này |

- `ollama pull gemma3:12b` (~8,1 GB, ổ D còn ~108 GB; user duyệt spec = đồng
  ý tải). **Không** tải `qwen3:30b` hay model nào khác (user đã loại). Pull lỗi
  (mạng/đĩa) → escalate, không tự đổi sang model khác.
- Mỗi model một bản copy config: `temp/cp65/config-<tag>.yaml` (`<tag>` bỏ
  dấu `:`, vd `gemma3-12b`) = `config.yaml` với `translation.model` đổi và
  `timeout_seconds: 900` (model chạy một phần trên CPU chậm hơn nhiều).
  `translation.think`: giữ `false`; nếu Ollama từ chối (lỗi nói model "does
  not support thinking") thì đặt `think: null` **trong bản copy đó**. Nếu
  model lớn hay timeout/"chia đôi" liên tục thì hạ `batch_size` xuống 12
  trong bản copy và ghi lại. Cần sửa code mới chạy được → escalate.
- Với mỗi model (`<tag>`):
  ```bash
  T=temp/cp65/ep-<tag>; mkdir -p "$T" && cp "$EP/transcript.json" "$EP/metadata.json" "$T/"
  # ghi khối YAML glossary chuẩn vào "$T/glossary.yaml"
  time $PY -m app translate "$T" --config temp/cp65/config-<tag>.yaml
  ```
  Script tạm trong scratchpad (không thêm vào repo) tính trên `$T/translated.json`
  và trên baseline không-glossary là `$EP/translated.json` cũ:
  - số segment có `tóc` / `sợi tóc`;
  - số segment có `mình yêu anh`; số segment có `con yêu ba` hoặc `ba yêu con`;
  - số segment chứa ký tự CJK `[一-鿿]` (phải bằng 0);
  - `failed_ids`, số lần log "chia đôi"/"lỗi", thời gian chạy (giây);
  - hệ số = giây dịch / phút video (video ≈ 4,06 phút) và **ước tính số giờ dịch cho
    playlist 10,5 giờ video**.
- Bảng cuối vào mục D của decisions: mỗi model một dòng (các số trên) + 10
  dòng nguồn → dịch cho id 2, 5, 13, 19, 27, 28, 31, 36, 41, 57 (cả baseline
  không glossary) để user tự đọc và chọn.
- **Đạt** (từng model): `tóc` ≤ 2, `mình yêu anh` = 0, `con yêu ba`/`ba yêu con`
  ≥ 5, CJK = 0, `failed_ids` rỗng, id 58 (Patreon) có `translated_text == ""`
  và không ở `failed_ids`, `source_text` mọi segment vẫn giống `transcript.json`,
  `glossary_sha256` bằng `load_effective_glossary(...)[0].sha256()`. Model đạt
  mà không đủ số lượng → tự tinh chỉnh câu chữ `glossary_prompt_block` tối đa **2
  vòng** (dịch lại `--force`); cần ít nhất **một** model đạt.
- **Model thắng** (`<W>`) = model đạt có ước tính giờ dịch nhỏ nhất **trong số
  các model không kém rõ về số liệu**; ghi lý do. Quyết định cuối thuộc về user
  (đọc bảng ở trên) — implementer chỉ đề xuất, **không** sửa `config.yaml` gốc
  hay `config.example.yaml` để đổi model.

### Pha B — kiểm chức năng với model thắng `<W>` (`C=temp/cp65/config-<W>.yaml`)
```bash
D=temp/cp65/ep-draft; mkdir -p "$D" && cp "$EP/transcript.json" "$EP/metadata.json" "$D/"
$PY -m app glossary "$D" --config $C            # B1: tạo nháp
$PY -m app glossary "$D" --config $C            # B2: SKIP, không gọi Ollama (< 1s)
$PY -m app glossary "$D" --config $C --force    # B3: tạo lại, có glossary.yaml.bak
W=temp/cp65/ep-<W>                              # thư mục Pha A của model thắng (đã dịch có glossary)
$PY -m app translate "$W" --config $C           # B4: SKIP (< 1s)
$PY -m app tts "$W" --config $C && $PY -m app normalize "$W" --config $C   # B5: downstream (mạng edge-tts, ~40s)
# B6: thêm một term bất kỳ vào "$W/glossary.yaml", rồi:
$PY -m app translate "$W" --config $C           # B6: phải in "glossary đã thay đổi … dịch lại từ đầu"
```
Tiêu chí đạt (mở artifact, không chỉ xem exit code):
- **B1**: `glossary.yaml` parse được bằng `load_glossary`, có header tiếng Việt,
  ≥ 1 character, `skip: []`. Chất lượng nháp (có bắt được `Nut Brown Hair` ≈
  hare không, đại từ có hợp lý không) **ghi vào decisions** cho user đánh giá —
  model có thể sai, đó là lý do có bước người sửa; chỉ coi là hỏng nếu YAML
  không parse được hoặc `characters` rỗng (sau 2 vòng chỉnh prompt draft).
- **B2**: SKIP, không có request tới Ollama. **B3**: `glossary.yaml.bak` có nội
  dung bản trước.
- **B4**: SKIP. **B5**: `tts/manifest.json` id 58 có `status: "empty"`;
  `normalized.json` `summary.silent == 1`, `missing == 0`.
- **B6**: log "glossary đã thay đổi", `glossary_sha256` mới trong `translated.json`.
- Ghi vào mục D của decisions: thời gian B1 và B6; mọi con số Pha A; giá trị
  `timeout_seconds`/`batch_size`/`think` phải dùng cho từng model để user chép
  vào `config.yaml`.

## Ngoài phạm vi
- Draft biết glossary dùng chung (chỉ tạo mục mới cho tập tiếp theo); lệnh tạo
  glossary cả playlist — CP8.
- Whisper `initial_prompt`/hotwords + transcribe lại theo glossary; đổi
  `--whisper-model large-v3`.
- Đổi model mặc định trong code/`config.example.yaml`; tự áp model thắng vào
  `config.yaml` của user (user quyết sau khi đọc bảng).
- Pass "polish" thứ hai sau khi dịch; sửa sau-dịch bằng thay chuỗi trên bản dịch.
- Tự sinh mục `skip`; UI/wizard sửa glossary; glossary đa ngôn ngữ đích (key
  `vi` gắn với tiếng Việt).
- Speaker diarization; nối vào `dub` (CP7).
- Ducking/tách giọng khi render (video có nhạc nền — việc riêng, sau).
- Cập nhật README/CLAUDE.md/SETUP.md.

## Điểm phải escalate
- Ollama không chạy, hoặc `ollama pull` lỗi → báo "CHƯA XONG", đừng tự đổi model.
- Không model nào đạt tiêu chí Pha A sau 2 vòng chỉnh prompt.
- Model cần chỉnh code (không chỉ config) mới chạy được, vd lỗi `think` không
  tránh được bằng `think: null`, hoặc structured output của model không hợp lệ.
- Muốn đổi schema `translated.json` ngoài key `glossary_sha256`, hoặc phải sửa
  chữ ký `translate_batch` khác kwarg tùy chọn `glossary`.
- Test cũ (đặc biệt `FakeTranslator`) vỡ khi thêm tính năng — là dấu hiệu
  không tương thích ngược, đừng sửa test cũ để cho qua.
- Draft của model rác (không parse được / `characters` rỗng) sau 2 vòng chỉnh
  prompt draft.

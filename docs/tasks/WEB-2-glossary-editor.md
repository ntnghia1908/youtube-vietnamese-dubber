# Task: WEB-2 — Web UI: sửa glossary + dịch lại & chạy tiếp

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer
- Authorization mode: boundary
- Authorization source: ADR-001 boundary (HUMAN LEAD 2026-10-17)
- Parallel group: —
- Owned paths: app/web/**, app/cli.py (chỉ `_cmd_web`), tests/test_web_*.py, README.md, docs/decisions/WEB-2.md
- Dependencies: WEB-1 (48cc251); WEB-AUTH (route mới phải nằm sau middleware auth); Ollama có model dịch cho phần chạy thật
- Base commit / branch: 75fa13b / main
- Human Lead approval: inherited from boundary
- Implementation authorized: YES

## Goal

Từ trang episode, người dùng mở **editor `glossary.yaml`** của tập, lưu (YAML được validate bằng đúng parser của pipeline trước khi ghi), thấy ngay **bản dịch hiện tại có còn khớp glossary không** (stale), và bấm **"Dịch lại & chạy tiếp"** → job WEB-1 chạy lại pipeline của tập đó: `translate` dịch lại vì hash glossary đổi, `tts` chỉ tổng hợp câu đổi, `normalize`/`render` tự khớp. Tập chưa có glossary có nút **"Tạo nháp bằng model"** (job `app glossary`).

## Scope

- In scope: module `app/web/glossary.py`; trang `/ep/{key}/glossary`; API đọc/lưu glossary, tạo nháp, dịch lại; job kind mới `glossary`; field `recheck`, `episode_key` trong `JobRequest`; chỉ báo stale + có/không glossary ở trang episode/thư viện; truyền glossary dùng chung (`translation.glossary`) vào `create_app`; test; README.
- Out of scope: sửa **glossary dùng chung** (`translation.glossary` — file ngoài workspace, chỉ hiện read-only đường dẫn); editor có cấu trúc (form từng nhân vật) — dùng textarea YAML; sửa câu dịch (WEB-3); highlight câu bị ảnh hưởng; `glossary --force` từ web (không bao giờ ghi đè glossary người dùng bằng nháp model); mọi thay đổi `app/pipeline/`, `app/translation/`, schema artifact; auth / chính sách bind.

## Authority / key decisions

- `docs/adr/ADR-001-web-ui.md` mục 0 (boundary), 5 (trang Glossary, `PUT /api/episodes/{id}/glossary`, an toàn), 6 (WEB-2).
- `docs/decisions/WEB-1.md` mục A (contract library/job/API; A3: thêm job kind = mở rộng `JOB_KINDS` + `validate_request` + `build_command`).
- `docs/decisions/checkpoint-6.5.md` mục A1, A2, A5: `translated.json["glossary_sha256"]`; glossary đổi ⇒ `translate` tự dịch lại, không cần `--force`; hash trên nội dung chuẩn hoá (comment/khoảng trắng không kích hoạt dịch lại); `dub` không tự tạo nháp.
- Quyết định cục bộ (ORCHESTRATOR):
  - **"Dịch lại" = job `dub`/`playlist` có sẵn, không thêm kind**: tập lẻ → `dub <metadata.original_url>`; tập thuộc playlist → `playlist <playlist.json url> --items <index> --recheck` (chạy `dub` với tập ở đúng thư mục `pl__t/vid__t`; `dub <url>` sẽ tạo thư mục lẻ mới — sai). Không truyền `--source-lang` (transcribe SKIP; truyền mã khác transcript sẽ lỗi — `app/pipeline/dub.py:198`), không `--force`.
  - **Nháp glossary = job kind mới `glossary`** (`app glossary <episode_dir>`, cần Ollama → phải đi qua hàng đợi 1 worker). Chỉ khi chưa có `glossary.yaml`; không bao giờ `--force`.
  - Episode chỉ tham chiếu bằng `episode_key` → server/JobManager tự tra path bằng `library.find_episode`; client **không bao giờ** gửi đường dẫn.
  - Lưu: optimistic concurrency bằng sha256 của **bytes file** (`base_sha256`), lệch → 409. Bản cũ chép ra `glossary.yaml.bak` (cùng hậu tố `BACKUP_SUFFIX` của draft). Giữ nguyên text người dùng (kể cả comment) — **không** đi qua `write_glossary` (hàm đó chuẩn hoá lại và mất comment).

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/web/glossary.py` (mới, stdlib + `yaml` + `app.translation.glossary`, **không** import fastapi) | đọc trạng thái, validate, lưu, dựng request "dịch lại" |
| `app/web/jobs.py` | `JOB_KINDS += "glossary"`; `JobRequest` thêm `recheck`, `episode_key`; `validate_request`, `build_command` theo dưới; `JobManager.submit` resolve `episode_key` |
| `app/web/server.py` | `create_app(..., shared_glossary: Path \| None = None)`; `run(...)` nhận + truyền `shared_glossary`; route mới; link Glossary ở trang episode; cột glossary ở thư viện |
| `app/web/library.py` | `EpisodeSummary` thêm `has_glossary: bool` (`GLOSSARY_FILENAME` tồn tại) |
| `app/cli.py` | `_cmd_web`: truyền `config.translation.glossary` (Path hoặc None) vào `run` — không đổi gì khác |
| `app/web/templates/glossary.html` (mới), `episode.html`, `library.html`, `jobs.html` (hiện job `glossary` + `episode_key`) | |
| `app/web/static/glossary.js` (mới) | load → textarea; Lưu (PUT, hiện lỗi 400/409 inline, không mất text đang gõ); Tạo nháp; Dịch lại → chuyển tới `/jobs/<id>`; cảnh báo `beforeunload` khi có thay đổi chưa lưu |
| `tests/test_web_glossary.py` (mới), `tests/test_web_jobs.py`, `tests/test_web_server.py`, `tests/test_web_library.py` | xem Required verification |
| `README.md` | mục "Web UI (local)": thêm phần Glossary |
| `docs/decisions/WEB-2.md` | log quyết định; mục A = contract cho WEB-3 (API glossary, job kind, `JobRequest`) |

### Interface — `app/web/glossary.py`

```python
from app.translation.glossary import GLOSSARY_FILENAME, GlossaryError, load_effective_glossary, parse_glossary
from app.translation.glossary_draft import BACKUP_SUFFIX

MAX_GLOSSARY_BYTES = 256 * 1024

class GlossaryConflictError(Exception): ...        # file trên đĩa đã đổi so với base_sha256

@dataclass(frozen=True)
class GlossaryState:
    exists: bool
    content: str                     # "" nếu chưa có file
    file_sha256: str | None          # sha256 bytes file; None nếu chưa có
    shared_path: str | None          # glossary dùng chung (read-only), str(path) như config
    effective_sha256: str | None     # Glossary.sha256() của load_effective_glossary; None = không glossary
    translated_sha256: str | None    # translated.json["glossary_sha256"]; None nếu chưa dịch/không có key
    has_translation: bool            # translated.json tồn tại
    stale: bool | None               # None nếu chưa dịch hoặc error; else effective_sha256 != translated_sha256
    has_transcript: bool             # điều kiện cho "Tạo nháp"
    error: str | None                # GlossaryError khi nạp glossary hiệu lực (YAML hỏng trên đĩa, shared thiếu…)

    def to_dict(self) -> dict[str, Any]

def read_glossary_state(episode_dir: Path, shared_path: Path | None) -> GlossaryState
def validate_glossary_text(text: str, *, source: str = GLOSSARY_FILENAME) -> None
    # > MAX_GLOSSARY_BYTES (utf-8) -> GlossaryError; yaml.safe_load lỗi -> GlossaryError (có dòng/cột từ YAMLError);
    # rồi parse_glossary(data, source=source). Text rỗng/chỉ comment = hợp lệ (parse_glossary(None) -> Glossary()).
def save_glossary_text(episode_dir: Path, text: str, *, base_sha256: str | None,
                       shared_path: Path | None) -> GlossaryState
    # 1) validate_glossary_text; 2) sha hiện tại của file (None nếu chưa có) != base_sha256 -> GlossaryConflictError;
    # 3) file cũ có -> copy bytes sang glossary.yaml.bak; 4) ghi glossary.yaml.tmp + os.replace (utf-8, giữ nguyên text,
    #    chuẩn hoá xuống dòng cuối file); 5) trả read_glossary_state(...)
    # Lock module-level (threading.Lock) quanh bước 2–4.
def redub_request(workspace: Path, episode_dir: Path) -> JobRequest
    # Tập lẻ: JobRequest(kind="dub", url=metadata.json["original_url"]).
    # Tập thuộc playlist (episode_dir.parent có playlist.json): tìm entry có episode_dir == tên thư mục tập
    #   -> JobRequest(kind="playlist", url=playlist.json["url"], items=str(entry["index"]), recheck=True).
    # Thiếu url/entry/metadata -> JobValidationError (tiếng Việt).
```

`translated_sha256` đọc bằng `json` trực tiếp (key `glossary_sha256`, file cũ thiếu key = None — đúng ngữ nghĩa CP6.5 A1). `effective_sha256` tính với **glossary dùng chung của server** (cùng giá trị job subprocess dùng vì job nhận `--config` của server).

### Interface — `app/web/jobs.py` (thay đổi)

```python
JOB_KINDS = ("dub", "playlist", "glossary")

@dataclass
class JobRequest:
    kind: str
    url: str = ""                    # glossary: ""
    source_lang: str | None = None
    items: str | None = None
    force: bool = False
    download_only: bool = False
    recheck: bool = False            # mới — chỉ playlist -> --recheck
    episode_key: str | None = None   # mới — bắt buộc với glossary, cấm với dub/playlist
```

- `validate_request`: `glossary` → cần `episode_key`, cấm `url`/`source_lang`/`items`/`force`/`download_only`/`recheck`; bỏ qua kiểm URL. `recheck` chỉ với `playlist`. Các kind cũ không đổi.
- `build_command(req, *, workspace, config_path, python, episode_dir: Path | None = None)`: `glossary` → `[python, "-m", "app", "glossary", str(episode_dir)] + (--config ...)` (`glossary` không có `--workspace` — kiểm `app/cli.py`; nếu `common` có thì giữ như dub). `recheck` → thêm `--recheck`.
- `JobManager.submit`: kind `glossary` → `library.find_episode(self.workspace, key)`; None → `JobValidationError("Không có episode này.")`; chưa có `transcript.json` → lỗi; đã có `glossary.yaml` → lỗi ("đã có glossary, sửa ở editor"). Path resolve **lúc submit** và lưu trong `command` của job JSON (retry dùng lại request → resolve lại).
- Job JSON `request` thêm `recheck`, `episode_key` (job cũ thiếu key → đọc như mặc định). `parse_progress` không đổi (dòng `[glossary] ...` → None).
- `POST /api/jobs` (form/JSON chung) chấp nhận `kind=glossary` + `episode_key` và `recheck` — qua đúng `validate_request`, không có đường tắt.

### Route mới — `app/web/server.py`

| Method + path | Hành vi |
|---|---|
| `GET /ep/{key}/glossary` | trang editor: textarea (nội dung file, hoặc rỗng + gợi ý cấu trúc 5 key trong placeholder), đường dẫn glossary dùng chung (read-only), trạng thái stale, nút Lưu / Tạo nháp (chỉ khi `!exists && has_transcript`) / Dịch lại & chạy tiếp (khi `has_transcript`) |
| `GET /api/episodes/{key}/glossary` | `GlossaryState.to_dict()` |
| `PUT /api/episodes/{key}/glossary` | JSON `{"content": str, "base_sha256": str\|null}` → 200 state; `GlossaryError` → 400 `{"error": ...}`; conflict → 409 `{"error": ..., "state": <state hiện tại>}`; body không phải JSON/thiếu field → 400 |
| `POST /api/episodes/{key}/glossary/draft` | submit `JobRequest(kind="glossary", episode_key=key)` → 201 job; lỗi → 400 |
| `POST /api/episodes/{key}/redub` | `redub_request` + `job_manager.submit` → 201 job; lỗi → 400 |

Mọi route ghi (`PUT`/`POST`) gọi `check_origin` như WEB-1; key tra qua `episode_or_404` (404 key lạ/traversal). Trang episode: link "Glossary" + nhãn (`chưa có glossary` / `bản dịch khớp glossary` / `bản dịch CŨ — cần dịch lại`). Thư viện: thêm cột glossary (✓/–) từ `has_glossary` (không tính stale ở thư viện — tránh nạp YAML mỗi lần quét).

JSON mẫu `GET /api/episodes/{key}/glossary`:

```json
{"exists": true, "content": "terms:\n  quantum mechanics: cơ học lượng tử\n",
 "file_sha256": "9f2c…", "shared_path": null,
 "effective_sha256": "41ab…", "translated_sha256": null, "has_translation": true,
 "stale": true, "has_transcript": true, "error": null}
```

### Config

Không key mới. `_cmd_web` truyền `Path(config.translation.glossary)` nếu khác None.

### Hành vi bắt buộc

- Lưu text không hợp lệ (YAML hỏng, key lạ `alias`, >256 KB) → 400, **file trên đĩa không đổi**, không tạo `.bak`.
- Chỉ đổi comment/khoảng trắng → lưu được, `stale` không đổi (hash chuẩn hoá).
- Hai tab cùng sửa: tab lưu sau nhận 409 kèm state mới; JS giữ text đang gõ và báo người dùng tải lại.
- Lưu khi job đang chạy trên tập đó: cho phép (translate đọc glossary lúc bắt đầu stage) — trang hiện cảnh báo nếu có job `running`/`queued` cùng tập? **Không** bắt buộc; ghi vào Known limitations nếu không làm.
- `glossary.yaml` trên đĩa đang hỏng (sửa tay ngoài web) → trang vẫn mở, hiện nội dung + `error`, lưu bản sửa được.
- Retry job `glossary` khi trong lúc đó đã có `glossary.yaml` → `submit` từ chối (400) chứ không ghi đè.

### Điểm phải escalate

- Cần sửa `app/pipeline/`, `app/translation/` hoặc schema artifact (vd muốn `dub` nhận thư mục episode thay vì URL) → dừng, hỏi.
- `playlist --recheck --items N` không chạy đúng thư mục tập cũ hoặc phải gọi mạng tải lại video → dừng, báo (không vá trong pipeline).
- Bind LAN: WEB-AUTH (làm trước) bắt buộc mật khẩu khi bind ngoài localhost; route WEB-2 phải được middleware auth bảo vệ — có test 401 cho route mới khi `create_app(..., password=...)`.

## Acceptance Criteria

1. `/ep/{key}/glossary` mở được cho tập có và chưa có `glossary.yaml`; hiện nội dung, đường dẫn glossary dùng chung (nếu có), trạng thái stale đúng theo `translated.json["glossary_sha256"]` so với glossary hiệu lực.
2. Lưu YAML hợp lệ → file được ghi đúng text (giữ comment), bản cũ ở `glossary.yaml.bak`, `stale` cập nhật; thêm/sửa chỉ comment → `stale` không đổi.
3. Lưu YAML hỏng / key lạ / quá cỡ → 400 với thông điệp tiếng Việt (có vị trí lỗi YAML), file + `.bak` không đổi.
4. Lưu với `base_sha256` cũ → 409, file không đổi; UI không mất text đang gõ.
5. "Dịch lại & chạy tiếp" tập lẻ → job `dub <original_url>` (không `--force`, không `--source-lang`); tập playlist → job `playlist <url> --items <index> --recheck`. Sau khi glossary đổi, log job có `translate` **xong** (không SKIP) và `tts` có dòng cache; `stale` thành `false` khi job xong. Chạy lại lần 2 → mọi stage SKIP.
6. "Tạo nháp bằng model" (chỉ hiện khi chưa có glossary + có transcript) → job `glossary`, xong thì editor hiện nháp. Submit khi đã có glossary hoặc chưa có transcript → 400, không tạo job.
7. `POST /api/jobs` với `kind=glossary`: thiếu `episode_key`, key lạ, kèm `url`/`force` → 400. `recheck` với `dub` → 400.
8. Key lạ/traversal trên mọi route mới → 404; `PUT`/`POST` với `Origin` lạ → 403; nội dung YAML chứa `</textarea><script>` hiển thị dạng text.
9. Thư viện có cột glossary; job list hiện được job `glossary` (episode thay cho URL).
10. Ngoài `glossary.yaml`, `glossary.yaml.bak`, `glossary.yaml.tmp` (tạm) và `.web/`, web không ghi file nào trong workspace; job cũ (JSON thiếu `recheck`/`episode_key`) vẫn đọc/retry được.

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS (extra `web` đã cài). Case mới:
  - `tests/test_web_glossary.py` (không cần fastapi): `read_glossary_state` (không file; file hợp lệ; file hỏng → `error`; chưa dịch → `stale None`; khớp/lệch hash; có shared glossary, shared thiếu → `error`); `validate_glossary_text` (rỗng, chỉ comment, YAML hỏng, key lạ, quá cỡ); `save_glossary_text` (ghi + `.bak` + giữ comment; conflict; lỗi không đụng file; base None khi chưa có file); `redub_request` (tập lẻ, tập playlist, thiếu entry/url). — AC1–AC5.
  - `tests/test_web_jobs.py`: validate/build_command cho `glossary`, `recheck`; submit resolve key / từ chối khi đã có glossary hoặc thiếu transcript; job JSON cũ thiếu field. — AC5–AC7, AC10.
  - `tests/test_web_server.py`: GET/PUT glossary 200/400/409/404/403; draft + redub 201/400; escape; cột glossary. — AC1–AC9.
  - `tests/test_web_library.py`: `has_glossary`. — AC9.
- **Chạy thật** (bắt buộc). HUMAN LEAD đang chạy server thật trên `output/` (10.8.102.102:8081) → **KHÔNG** mở server thứ hai trên `output/` (hai `JobManager` dùng chung `output/.web/jobs`, recovery của server này sẽ đánh `interrupted` và kill job của server kia). Dùng workspace riêng trong scratchpad, ví dụ `$WS`, chép (`cp -a`) tập Brian Cox và thư mục playlist Ocean Girl chỉ gồm `playlist.json` + thư mục tập index 1; server `$PY -m app web --workspace $WS --port <port trống khác 8081>` bind `127.0.0.1`. Không xoá/sửa gì trong `output/`. Các đường dẫn `output/...` dưới đây hiểu là bản chép trong `$WS`. Tập lẻ dùng thử: `output/fcfQkxwz4Oo__Brian Cox…` (đã `completed`, 82 s, chưa có glossary).
  1. Sao lưu thư mục tập trước (`cp -a` sang scratchpad) để khôi phục nếu cần; ghi rõ.
  2. `GET /api/episodes/<key>/glossary` → `exists:false`, `stale` = `false` (translated không glossary, hiệu lực None) hoặc `None` — ghi giá trị thật và giải thích.
  3. `POST .../glossary/draft` → theo dõi SSE tới `completed`; `glossary.yaml` có nội dung nháp; submit draft lần 2 → 400.
  4. `PUT` với YAML hỏng → 400, `sha256sum glossary.yaml` không đổi; `PUT` với `base_sha256` sai → 409.
  5. `PUT` nháp + một term mới (vd `quantum mechanics: cơ học lượng tử`) → 200, `stale:true`, có `.bak`. Thêm một dòng comment, `PUT` → `stale` vẫn như trước.
  6. `POST .../redub` → job `dub` đúng lệnh; log có `translate … xong` (không SKIP), `tts` có cache > 0; job `completed`; `GET glossary` → `stale:false`; `grep` `translated.json` thấy bản dịch dùng term mới (ghi câu ví dụ). Redub lần 2 → mọi stage SKIP.
  7. Tập playlist: `output/PLllZo…Ocean Girl…` entry index 1 (đã `downloaded`). `POST .../redub` → `GET /api/jobs/<id>` có `command` chứa `playlist <url> --items 1 --recheck`; log có tag `[EP01]` và **không** tải lại video (download SKIP). Được hủy sau khi thấy stage `transcribe` chạy (tập dài) — ghi rõ đã kiểm tới đâu.
  8. `Origin: http://evil.example` trên `PUT` → 403; key `..%2F..` trên `GET /api/episodes/<key>/glossary` → 404.
  9. Mở `/ep/<key>/glossary` bằng trình duyệt hoặc `curl` HTML (textarea, nút, script `glossary.js`); ghi rõ cách đã kiểm.

## Manual test checklist (Tech Lead)

Không chạm database / public API. Chạm security model: thêm route ghi file (`glossary.yaml`) — trong phạm vi ADR-001 mục 5; path chỉ từ key đã quét.

- [ ] Mở trang Glossary của một tập, sửa tên nhân vật / xưng hô, Lưu, thấy nhãn "bản dịch CŨ".
- [ ] Bấm "Dịch lại & chạy tiếp", xem job, rồi ở trang episode nghe câu chứa tên đã sửa.
- [ ] Mở hai tab, lưu ở cả hai → tab sau báo xung đột, không mất text.

## Result

- Main changes: `app/web/glossary.py` (state/stale, validate bằng `parse_glossary`, lưu atomic + `.bak` + 409 theo sha bytes, `redub_request`); `jobs.py` kind `glossary` + `JobRequest.recheck/episode_key`, resolve key lúc submit; `server.py` trang `/ep/{key}/glossary`, `GET/PUT /api/episodes/{key}/glossary`, `POST .../glossary/draft`, `POST .../redub`, `shared_glossary`; `library.has_glossary`; templates + `glossary.js`; `_cmd_web` truyền `translation.glossary`; README; `docs/decisions/WEB-2.md`.
- Tests: 543 OK (508 + 35 mới), ORCHESTRATOR chạy lại độc lập.
- Chạy thật (workspace chép trong scratchpad, 127.0.0.1:8099, `output/` không đụng): Brian Cox — state ban đầu `exists:false, stale:false` (cả hai hash None); draft job completed ~10 s, draft lần 2 → 400; YAML hỏng → 400 có dòng/cột, file không đổi, không `.bak`; base sai → 409; thêm term → `stale:true` + `.bak`, thêm comment → effective hash giữ nguyên; redub → `dub <url>` không `--force`/`--source-lang`, "glossary đã thay đổi — dịch lại", 10/15 câu đổi, tts dùng cache 5, completed, `stale:false`; redub lần 2 → 6 stage SKIP. Ocean Girl index 1 (bản chép) → `playlist <url> --items 1 --recheck`, download SKIP, không tạo thư mục mới, completed; lần 2 SKIP. Origin lạ 403; traversal 404; HTML kiểm bằng curl.
- Review: không blocking. Translate của ca playlist chạy lại ở lần đầu là do tập đó trước đó bị dừng giữa bước dịch (job `20261017-091102-0043e4`) — tiếp tục từ partial, không phải lỗi.
- Important findings / decisions: trang Jobs ẩn kind `glossary` khỏi form nhập URL (decisions B2). `run()` nhận `shared_glossary` theo vị trí.
- Known limitations: không cảnh báo khi lưu glossary trong lúc có job chạy cùng tập; `glossary.js` chưa chạy trong trình duyệt thật (nút, `beforeunload`, 409 hai tab) → Manual test checklist; glossary chỉ theo tập (chưa có glossary chung cho một playlist/series).
- PR: commit thẳng `main` (profile §5).

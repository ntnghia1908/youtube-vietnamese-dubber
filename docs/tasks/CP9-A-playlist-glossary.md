# Task: CP9-A — Glossary dùng chung theo playlist

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17
- Parallel group: P1 (cùng CP9-B)
- Owned paths: `app/translation/glossary.py`, `app/web/glossary.py`, `app/web/server.py`, `app/web/templates/playlist.html`, `app/web/templates/glossary.html`, `app/web/static/glossary.js`, `tests/test_glossary.py`, `tests/test_web_glossary.py`, `tests/test_web_server.py`, `docs/decisions/checkpoint-9.md`, `README.md` (mục glossary nếu có)
- Dependencies: CP8, WEB-2
- Base commit / branch: 16b3b3e / main
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`.

## Goal

Một file `<thư mục playlist>/glossary.yaml` tự động áp dụng cho **mọi tập** của playlist đó (gộp với `glossary.yaml` riêng của từng tập), để không phải chép tay `skip`/nhân vật/xưng hô vào từng tập. Sửa được glossary playlist trên Web UI và bấm một nút để dịch lại các tập đã dịch với glossary cũ.

Thứ tự CP9 do HUMAN LEAD chọn 2026-10-17 (mỗi lần một hạng mục): **CP9-A glossary playlist (task này)** → không lồng tiếng bài hát Guess How Much I Love You (sau CP9-A chủ yếu là dữ liệu glossary playlist) → dịch 2 tập song song → nhiều giọng (ưu tiên cuối).

## Scope

- In scope:
  - Tầng glossary playlist trong `load_effective_glossary` (mọi đường dịch — `translate`, `dub`, `playlist`, web — đều đi qua hàm này nên tự có).
  - Web: trang sửa glossary playlist + API GET/PUT + nút "Dịch lại các tập cũ" (job `playlist --items <các tập stale> --recheck`).
  - Trang glossary của tập hiển thị các tầng đang gộp (đường dẫn file playlist, nếu có).
- Out of scope:
  - Lệnh `glossary` (tạo nháp bằng model) cho playlist; nháp tập vẫn như cũ, không trừ đi phần playlist đã có.
  - Đổi quy tắc gộp (`merge_glossaries`) — giữ nguyên ngữ nghĩa hiện tại.
  - Tự di chuyển nội dung glossary các tập hiện có lên playlist (HUMAN LEAD tự làm qua web).
  - Mọi hạng mục CP9 khác.

## Authority / key decisions

- Plan §Checkpoint 9 mục 3–4 (glossary tên nhân vật, quy tắc xưng hô), §21.
- `docs/decisions/checkpoint-6.5.md` (glossary hai tầng, hash `glossary_sha256` → dịch lại khi đổi).
- `docs/tasks/WEB-2-glossary-editor.md` (editor tập, optimistic concurrency `base_sha256`, `redub_request`).
- Bằng chứng: Ocean Girl Episode 01/02 phải chép tay cùng danh sách `skip` + xưng hô (current-state).

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/translation/glossary.py` | Thêm tầng playlist vào `load_effective_glossary`; thêm `playlist_glossary_path(episode_dir)` |
| `app/web/glossary.py` | Tách phần ghi file có kiểm hash thành hàm dùng chung; thêm `read_playlist_glossary_state`, `save_playlist_glossary_text`, `playlist_redub_request`; `GlossaryState` thêm field `playlist_path` |
| `app/web/server.py` | Route `GET /pl/{key}/glossary`, API `GET/PUT /api/playlists/{key}/glossary`, `POST /api/playlists/{key}/redub` |
| `app/web/templates/playlist.html` | Link "Glossary playlist: sửa/tạo" + số tập stale |
| `app/web/templates/glossary.html`, `app/web/static/glossary.js` | Dùng chung cho cả tập và playlist (tham số hoá base URL API); trang tập hiện dòng "Glossary playlist (gộp, sửa ở đây): <link>" |
| `tests/test_glossary.py`, `tests/test_web_glossary.py`, `tests/test_web_server.py` | Case mới (liệt kê ở Required verification) |
| `docs/decisions/checkpoint-9.md` | Tạo mới, mục A Contract cho CP9-B.. (tầng playlist, thứ tự gộp) |

### Interface

```python
# app/translation/glossary.py
PLAYLIST_STATE_FILENAME = "playlist.json"  # trùng app/pipeline/playlist.py; không import pipeline từ translation (tránh vòng phụ thuộc) — comment lý do

def playlist_glossary_path(episode_dir: Path) -> Path | None:
    """<parent>/glossary.yaml nếu episode_dir.parent có playlist.json, ngược lại None.
    Trả path kể cả khi file glossary chưa tồn tại (web cần biết chỗ để tạo)."""

def load_effective_glossary(episode_dir: Path, shared_path: Path | None) -> tuple[Glossary | None, list[Path]]:
    # Thứ tự tầng (sau thắng trước): shared_path (config/--glossary) → playlist → tập.
    # Tầng playlist tuỳ chọn: file không có thì bỏ qua lặng lẽ (khác shared_path chỉ định rõ).
    # Gộp lần lượt bằng merge_glossaries; một tầng duy nhất thì giữ nguyên, không merge (như hiện tại).
    # paths trả theo đúng thứ tự tầng.
```

```python
# app/web/glossary.py
@dataclass(frozen=True)
class GlossaryState:  # thêm field
    playlist_path: str | None  # path glossary playlist nếu tập thuộc playlist (có thể chưa tồn tại)

@dataclass(frozen=True)
class PlaylistGlossaryState:
    exists: bool
    content: str
    file_sha256: str | None
    shared_path: str | None
    error: str | None              # lỗi parse file playlist (hoặc shared)
    stale_items: list[int]         # index tập có translated.json mà glossary_sha256 != effective hiện tại
    translated_items: list[int]    # index tập có translated.json
    def to_dict(self) -> dict[str, Any]: ...

def read_playlist_glossary_state(playlist_dir: Path, shared_path: Path | None) -> PlaylistGlossaryState
def save_playlist_glossary_text(playlist_dir: Path, text: str, *, base_sha256: str | None, shared_path: Path | None) -> PlaylistGlossaryState
def playlist_redub_request(playlist_dir: Path, shared_path: Path | None) -> JobRequest
    # JobRequest(kind="playlist", url=<playlist.json url>, items="2,3,7", recheck=True)
    # không có tập stale -> JobValidationError("Không có tập nào cần dịch lại.")
```

- Tái sử dụng: `save_glossary_text` → tách lõi `_write_checked(path, text, base_sha256)` (validate + `_save_lock` + `.bak` + `.tmp`/`os.replace`) dùng cho cả tập và playlist; `read_glossary_state` (lấy `stale` từng tập để tính `stale_items`); `redub_request` (cách đọc `playlist.json` entries → index); `library.find_playlist`, `library.make_key`.
- `stale_items`: duyệt `playlist.json["entries"]`, `episode_dir` tương đối với thư mục playlist; chỉ tập có `translated.json`. Tập bị lỗi parse glossary → không tính stale (state error).
- Items gửi job: chuỗi index nối dấu phẩy, sắp tăng dần (cú pháp `parse_item_spec` đã hỗ trợ).

### API

```
GET  /pl/{key}/glossary                 -> trang editor (template glossary.html, chế độ playlist)
GET  /api/playlists/{key}/glossary      -> PlaylistGlossaryState.to_dict()
PUT  /api/playlists/{key}/glossary      body {"content": "...", "base_sha256": "<sha>|null"} -> state | 400 GlossaryError | 409 {error, state}
POST /api/playlists/{key}/redub         -> 201 job | 400 {error}
```

Cùng auth/`check_origin`/404 như API tập (`library.find_playlist` trả None → 404). Giới hạn kích thước như tập (`MAX_GLOSSARY_BYTES`).

### Artifact

- Vào/ra mới: `<workspace>/<playlist_dir>/glossary.yaml` — cùng schema với glossary tập (context/characters/address/terms/skip). Ví dụ:

```yaml
skip:
  - "she'll come away"
characters:
  - {name: Nimon, vi: Nimon, aliases: [Neamon], note: "vua, chú của Neri"}
address:
  - {speaker: Galil, listener: everyone, self: ta, other: ngươi}
terms:
  Princess: công chúa
```

- `translated.json`: không đổi schema; `glossary_sha256` giờ là hash của glossary hiệu lực gồm cả tầng playlist.
- Log `dub`: dòng `[dub] glossary : ` liệt kê cả path playlist (đã có sẵn qua `glossary_paths`).

### Config

Không key mới. Tầng playlist tự nhận theo vị trí file; `translation.glossary`/`--glossary` giữ nguyên vai trò tầng ngoài cùng.

### Hành vi bắt buộc

- **Không làm stale bất ngờ**: playlist chưa có `glossary.yaml` → effective glossary và `glossary_sha256` của mọi tập y hệt trước task (test bắt buộc). Tập lẻ (không thuộc playlist) không bị ảnh hưởng.
- Có glossary playlist → mọi tập đã dịch của playlist thành stale; lần chạy `playlist --recheck`/`dub` kế tiếp dịch lại tập đó (cơ chế CP6.5 có sẵn), các stage khác resume như cũ.
- File glossary playlist hỏng → tập thuộc playlist báo lỗi glossary rõ ràng (stage translate), không lặng lẽ dịch thiếu glossary.
- Gộp: tập thắng playlist thắng shared, theo đúng `merge_glossaries` (khoá không phân biệt hoa thường; `skip` hợp; `context` tầng sau không rỗng thì thay).
- Lưu glossary playlist dùng optimistic concurrency + `.bak` như glossary tập.
- `glossary` của playlist dir không bị library/scan hiểu nhầm thành tập (kiểm `library.scan_workspace` chỉ coi subdir là tập).

### Điểm phải escalate

- Cần đổi ngữ nghĩa `merge_glossaries` (vd muốn nối `context` thay vì thay).
- Cần đổi schema `translated.json`/`playlist.json` hoặc thêm dependency.
- Cách nhận diện playlist bằng `episode_dir.parent/playlist.json` không đúng với cấu trúc thư mục thực tế ở đâu đó.

## Acceptance Criteria

1. Tập thuộc playlist có `<playlist_dir>/glossary.yaml` → `load_effective_glossary` trả glossary gộp shared → playlist → tập, `paths` đúng thứ tự; `skip` của playlist áp dụng cho tập không có glossary riêng.
2. Playlist không có `glossary.yaml` → `glossary_sha256` của tập không đổi so với trước task.
3. Web: mở `/pl/{key}/glossary`, tạo/sửa/lưu glossary playlist (409 khi xung đột, 400 khi YAML sai); trang playlist hiện số tập stale; nút "Dịch lại các tập cũ" tạo đúng job `playlist --items <stale> --recheck`.
4. Trang glossary của tập hiển thị link tới glossary playlist (nếu tập thuộc playlist).
5. Chạy thật: một tập Ocean Girl chưa có glossary riêng được dịch với `skip` lấy từ glossary playlist → lời bài hát intro không được dịch.

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS. Case mới:
  - `tests/test_glossary.py`: ba tầng gộp đúng thứ tự + paths; không có file playlist → kết quả và `sha256()` y hệt hai tầng cũ; parent không có `playlist.json` → bỏ qua `parent/glossary.yaml`; file playlist hỏng → `GlossaryError`.
  - `tests/test_web_glossary.py`: `read_playlist_glossary_state` (stale_items/translated_items), `save_playlist_glossary_text` (tạo mới, 409, `.bak`), `playlist_redub_request` (items đúng, không có stale → lỗi), `GlossaryState.playlist_path`.
  - `tests/test_web_server.py`: GET/PUT `/api/playlists/{key}/glossary`, `POST /api/playlists/{key}/redub`, 404 key lạ, `check_origin` 403, trang `/pl/{key}/glossary` render.
- **Chạy thật** (chứng minh AC1, AC5): playlist Ocean Girl `output/PLllZo-pkRkaEhoPJ6mM1DdIV94fifKPsn__…`.
  1. Tạo `<playlist_dir>/glossary.yaml` chỉ chứa danh sách `skip` hiện có trong glossary Episode 02 (KHÔNG sửa glossary các tập).
  2. `$PY -m app playlist "https://www.youtube.com/playlist?list=PLllZo-pkRkaEhoPJ6mM1DdIV94fifKPsn" --workspace output --items 4` (Episode 03, chưa có glossary riêng; tải + chạy đủ pipeline ~35 phút). Log phải có `[dub] glossary : …/glossary.yaml` trỏ file playlist.
  3. Mở `translated.json` của Episode 03: các segment intro chứa chuỗi `skip` có `translated_text` rỗng; in 5 segment đầu vào báo cáo.
  4. Chạy lại lệnh bước 2 → tập `skipped`/SKIP mọi stage, không dịch lại.
  5. Không cần dịch lại Episode 01/02 (sẽ thành stale — ghi vào Result; HUMAN LEAD tự bấm "Dịch lại các tập cũ").
- Web chạy thật (chứng minh AC3): khởi động server tạm ở cổng khác (không đụng server LAN đang chạy), mở `/pl/{key}/glossary` qua `curl` với cookie, PUT nội dung, GET lại thấy `stale_items` gồm index 2, 3; POST redub **không** cần chạy job tới cuối (TaskStop/hủy job sau khi thấy `command` đúng).

## Manual test checklist (Tech Lead)

- Không chạm database / security model. Public API web thêm 3 endpoint dưới cùng cơ chế auth hiện có.
- [ ] HUMAN LEAD mở `/pl/<Ocean Girl>/glossary` trên điện thoại, chuyển `skip` + nhân vật/xưng hô từ Episode 02 lên playlist, bấm "Dịch lại các tập cũ".
- [ ] HUMAN LEAD nghe intro Episode 03: lời bài hát không bị lồng tiếng.

## Result

- Main changes: `app/translation/glossary.py` — `playlist_glossary_path()`, `load_effective_glossary` gộp shared → playlist → tập. `app/web/glossary.py` — `_write_checked` dùng chung, `PlaylistGlossaryState`, `read_playlist_glossary_state`, `save_playlist_glossary_text`, `playlist_redub_request`, `GlossaryState.playlist_path`. `app/web/server.py` — `GET /pl/{key}/glossary`, `GET/PUT /api/playlists/{key}/glossary`, `POST /api/playlists/{key}/redub`. Template/JS glossary dùng chung hai chế độ; trang playlist có link + số tập stale; README 3 dòng.
- Tests: toàn suite 587 OK (implementer), ORCHESTRATOR chạy lại sau khi gộp CP9-B: OK.
- Chạy thật: tạo `output/PLllZo…/glossary.yaml` (11 chuỗi skip từ Episode 02); `playlist … --items 4 --source-lang en` (Episode 03, không có glossary riêng) exit 0, log `[dub] glossary : output/PLllZo…/glossary.yaml`, "bỏ qua 6 câu khớp mục skip". ORCHESTRATOR mở `translated.json` Episode 03: 264 segment, `failed_ids` [], segment 1–5 và 7 rỗng; `output_vi.mp4` 1542.6s. Chạy lần 2: `skipped 1`. Web trên bản sao workspace: PUT → `stale_items` [2,3]; POST redub → `--items 2,3 --recheck` (job hủy ngay).
- Review: ORCHESTRATOR đọc diff `app/`, không blocking.
- Important findings / decisions: `docs/decisions/checkpoint-9.md` mục CP9-A. Episode 03 còn lọt 2 câu điệp khúc "Ocean, our ocean" (segment 6, 8 → "Biển cả của chúng ta, biển cả.") — thiếu chuỗi skip trong glossary playlist, là dữ liệu, không phải lỗi code.
- Known limitations: Episode 01/02 đang stale (HUMAN LEAD bấm "Dịch lại các tập cũ"). Log dub vẫn gợi ý "Chưa có glossary.yaml" khi tập chỉ có glossary playlist (cảnh báo gây hiểu lầm, ngoài scope).
- PR: — (commit thẳng `main`).

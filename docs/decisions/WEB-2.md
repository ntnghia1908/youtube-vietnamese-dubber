# WEB-2 — Các quyết định nhỏ khi triển khai

Task: `docs/tasks/WEB-2-glossary-editor.md`. Mục **[CẦN DUYỆT]** là chỗ Opus nên xem lại.

---

## A. Contract với WEB-3

### A1. API glossary (`app/web/server.py`; logic ở `app/web/glossary.py`, không import fastapi)

- `GET /api/episodes/{key}/glossary` -> `GlossaryState.to_dict()` (`exists, content, file_sha256, shared_path,
  effective_sha256, translated_sha256, has_translation, stale, has_transcript, error`).
- `PUT /api/episodes/{key}/glossary` body `{"content": str, "base_sha256": str|null}` -> 200 state;
  `GlossaryError` -> 400 `{"error"}`; conflict -> 409 `{"error","state"}`.
- `POST /api/episodes/{key}/glossary/draft` -> 201 job `glossary`; `POST /api/episodes/{key}/redub` -> 201 job.
- Hàm dùng lại được: `read_glossary_state(episode_dir, shared_path)`, `redub_request(workspace, episode_dir)`
  (WEB-3 sửa câu dịch cũng dùng "chạy tiếp" qua đây), `create_app(..., shared_glossary=Path|None)`.

### A2. Job

`JOB_KINDS = ("dub", "playlist", "glossary")`. `JobRequest` thêm `recheck: bool=False`, `episode_key: str|None`;
`url` mặc định `""`. Job JSON `request` có thêm 2 field; job cũ thiếu field vẫn retry được. Job `glossary`:
`[python, -m, app, glossary, <episode_dir>, (--config ...)]` — path resolve lúc submit từ `episode_key`,
không `--workspace`/`--force`. `JobManager.submit` từ chối (400): key lạ, chưa có transcript, đã có glossary.yaml.

### A3. Library

`EpisodeSummary.has_glossary: bool` (mặc định False).

## B. Quyết định nhỏ

- B1. `POST /api/jobs` nhận `kind=glossary` mà không cần `url` (coi như `""`); `episode_key` và `recheck` đi qua
  `validate_request` như mọi field khác.
- B2. Form chọn loại ở trang Jobs chỉ liệt kê `dub`/`playlist` (glossary cần episode, không có URL); job `glossary`
  chỉ tạo từ trang Glossary hoặc API.
- B3. `cmd_web` truyền `shared_glossary` là tham số vị trí thứ 5 của `run(...)` (test hiện có giả `run` bằng `*a`).
- B4. `stale` cho tập dịch không glossary = `false` (cả hai hash `None`); `None` chỉ khi chưa dịch hoặc glossary lỗi.
- B5. Không làm cảnh báo "đang có job chạy cùng tập khi lưu" -> xem Known limitations.
- B6. Đọc file glossary không phải UTF-8 dùng `errors="replace"` để trang vẫn mở; lưu lại sẽ ghi UTF-8 sạch.

## C. Chạy thật (workspace scratchpad, không đụng `output/`)

- Tập Brian Cox (qwen3:14b qua Ollama 11437, rảnh): `stale:false` khi chưa có glossary (hai hash None); draft job
  xong ~10 s; redub tập lẻ translate 11.7 s (đổi 10/15 câu), tts dùng lại 5 câu cache; lần 2 mọi stage SKIP.
- Tập playlist (Ocean Girl EP01): lệnh `playlist <url> --items 1 --recheck`, tag `[EP01]`, download SKIP, không tạo
  thư mục mới; lần đầu translate vẫn chạy lại (log không có dòng "glossary đã thay đổi"; lý do chưa điều tra — nghi translated.json
  của tập này không khớp điều kiện resume khác, ngoài phạm vi WEB-2), lần 2 mọi stage SKIP. Chạy tới hết, không cần hủy.

## D. Known limitations

- Lưu glossary khi có job đang chạy cùng tập: cho phép, không cảnh báo trên trang (translate đọc glossary lúc bắt đầu stage).
- Không sửa glossary dùng chung; không highlight câu bị ảnh hưởng.

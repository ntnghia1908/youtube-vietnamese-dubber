# Task: WEB-DOWNLOAD — Tải video lồng tiếng về máy, đánh dấu tập đã tải

## Status / Approval

- Status: READY
- Type: FEATURE
- Change class: S1
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 — ngoài boundary ADR-001 mục 0 (giống WEB-MOBILE, WEB-POLISH)
- Parallel group: —
- Owned paths: `app/web/server.py`, `app/web/library.py`, `app/web/templates/episode.html`, `app/web/templates/playlist.html`, `app/web/static/episode.js`, `app/web/static/app.css`, `tests/test_web_server.py`, `tests/test_web_library.py`, `docs/decisions/WEB-DOWNLOAD.md`
- Dependencies: CP9-C (cùng sửa `app/web/server.py` — chạy SAU khi CP9-C commit, không song song)
- Base commit / branch: 7798692 / main
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

Lifecycle: `boundary` mode = `DRAFT → IN_PROGRESS → READY`.

## Goal

HUMAN LEAD 2026-10-17: "nên cho phép tải các video đã lồng tiếng, video nào đã tải thì tick đã tải". Từ web (desktop hoặc điện thoại) bấm một nút để tải `output_vi.mp4` của một tập về máy với tên file dễ đọc; server ghi nhận tập đã tải, nên danh sách tập của playlist và trang tập hiện dấu ✓ "đã tải" ở **mọi** máy. Tập render lại sau lần tải (dịch lại) thì mất ✓ để biết cần tải bản mới.

## Scope

- In scope:
  - Endpoint tải file (`Content-Disposition: attachment`) + file đánh dấu trong thư mục tập.
  - API bỏ đánh dấu (và đánh dấu tay).
  - Trang tập: nút "Tải video lồng tiếng" + trạng thái đã tải + nút bỏ đánh dấu.
  - Trang playlist: mỗi tập có `output_vi.mp4` có link tải nhỏ + ✓ đã tải. Đổi tên cột hiện có "Đã tải" (nghĩa: đã tải video **nguồn** từ YouTube, `entry.downloaded`) thành "Nguồn" để khỏi trùng nghĩa.
- Out of scope:
  - Thư viện / tập lẻ ngoài playlist (HUMAN LEAD chỉ chọn trang tập + danh sách tập playlist; tập lẻ vẫn tải được qua trang tập).
  - Tải hàng loạt / zip cả playlist; tải `source.mp4`.
  - Theo dõi theo từng người/thiết bị (một trạng thái chung cho cả server).
  - Đổi pipeline / CLI.

## Authority / key decisions

- HUMAN LEAD 2026-10-17 (AskUserQuestion): trạng thái "đã tải" lưu **trên server**; nút + tick hiện ở **trang tập** và **danh sách tập của playlist**.
- ADR-001: Web UI local, auth bằng `DUBBER_WEB_PASSWORD` khi mở LAN (WEB-AUTH) — endpoint mới nằm sau cùng middleware auth, không thêm ngoại lệ.
- Thư mục tập là artifact pipeline; file đánh dấu mới là dữ liệu riêng của web, pipeline không đọc/ghi nó, `--force` không xoá nó (đã có cơ chế stale bên dưới).

## Implementation approach

### File cần sửa/tạo

| Path | Việc cần làm |
|---|---|
| `app/web/library.py` | Hằng `WEB_DOWNLOAD_FILENAME = "web_download.json"`; `read_download_mark(episode_dir) -> str \| None`, `write_download_mark(episode_dir) -> str`, `clear_download_mark(episode_dir) -> None`; `EpisodeSummary.downloaded_at: str \| None = None` điền trong `_summarize_episode`. |
| `app/web/server.py` | Route tải + API đánh dấu (mục Interface); truyền `downloaded_at` cho template. |
| `app/web/templates/episode.html` | Nút tải (thẻ `<a href=… download>` dạng nút) + dòng trạng thái + nút bỏ đánh dấu, chỉ khi `has_output`. |
| `app/web/templates/playlist.html` | Cột "Nguồn" (đổi tên), cột mới "Video": link ⬇ tải + ✓ nếu `downloaded_at`. Giữ `data-label` cho layout mobile (WEB-MOBILE). |
| `app/web/static/episode.js` | Bấm nút tải → cập nhật trạng thái tại chỗ (không reload); nút bỏ đánh dấu gọi `DELETE`. |
| `app/web/static/app.css` | Chỉ thêm style tối thiểu nếu class sẵn có không đủ (theo style WEB-POLISH, cả sáng/tối). |
| `docs/decisions/WEB-DOWNLOAD.md` | Mục A (contract), B (quyết định nhỏ), C (chạy thật). |

### Interface

```python
# app/web/library.py
WEB_DOWNLOAD_FILENAME = "web_download.json"

def read_download_mark(episode_dir: Path) -> str | None:
    """``downloaded_at`` nếu đã đánh dấu VÀ output_vi.mp4 vẫn là đúng file đã tải
    (cùng size + mtime_ns); thiếu file/JSON hỏng/output đổi -> None."""

def write_download_mark(episode_dir: Path) -> str:
    """Ghi atomic (tmp + os.replace) dấu của output_vi.mp4 hiện tại, trả downloaded_at (ISO, giờ local có offset)."""

def clear_download_mark(episode_dir: Path) -> None:  # không có file -> không lỗi
```

`web_download.json`:

```json
{"downloaded_at": "2026-10-17T21:05:11+07:00", "output_size": 123456789, "output_mtime_ns": 1792230000000000000}
```

Route (server.py), dùng `episode_or_404(key)` như các route hiện có:

| Method / path | Hành vi |
|---|---|
| `GET /download/{key}` | Không có `output_vi.mp4` → 404. Có → `write_download_mark` rồi `FileResponse(path, media_type="video/mp4", filename=<tên tải>)` (Starlette tự đặt `Content-Disposition: attachment`, có `filename*` UTF-8). Request có header `Range` (trình quản lý tải chia khúc / tải tiếp) **không** ghi dấu lại nếu dấu hiện tại còn hợp lệ — chỉ ghi khi chưa có dấu hợp lệ. |
| `POST /api/episodes/{key}/downloaded` | Đánh dấu tay (vd đã copy file bằng cách khác). Không có output → 404. Trả `{"downloaded_at": "..."}`. |
| `DELETE /api/episodes/{key}/downloaded` | Bỏ dấu, trả `{"downloaded_at": null}`. |

Tên tải: `"<title> - lồng tiếng.mp4"` với `title` từ `ep.title` (fallback `video_id`, rồi tên thư mục); bỏ ký tự `\/:*?"<>|` và ký tự điều khiển, gọn khoảng trắng, cắt ≤ 150 ký tự. Tiếng Việt giữ nguyên (đi qua `filename*`).

Không đổi route `/media/{key}/{kind}` (player vẫn stream qua đó; xem video trên web không tính là đã tải).

### Hành vi bắt buộc

- Dấu gắn với **file output cụ thể** (size + mtime_ns): render lại (CP9-B mux lại, "Dịch lại các tập cũ"…) → `read_download_mark` trả None → mất ✓, không cần pipeline biết gì.
- Ghi dấu lúc server bắt đầu trả file (không biết chắc client tải xong) — ghi rõ trong decision log; người dùng bỏ dấu được.
- `episode.js`: click link tải → hiện ngay "✓ Đã tải" (trình duyệt tự tải, trang không đổi); nút "Bỏ đánh dấu" → `DELETE` → ẩn ✓, lỗi thì hiện thông báo như các nút khác trên trang.
- Mọi request đi qua auth middleware hiện có (WEB-AUTH); chưa đăng nhập → bị chặn như `/media`.
- Ghi file trong thư mục tập không được làm hỏng job đang chạy trên tập đó (pipeline không đọc file này; ghi atomic).

### Điểm phải escalate

- Starlette/FastAPI bản đang cài không hỗ trợ `FileResponse(filename=...)` với tên UTF-8 → báo, không tự viết header tay khác contract.
- Cần đổi schema `playlist.json`, job JSON, hoặc API JSON hiện có.

## Acceptance Criteria

1. `GET /download/{key}` trả 200, `Content-Disposition` attachment với tên `<title> - lồng tiếng.mp4` (UTF-8), body đúng bằng `output_vi.mp4`; tập không có output → 404; key lạ → 404.
2. Sau khi tải, `web_download.json` có trong thư mục tập; trang playlist hiện ✓ cho tập đó, trang tập hiện "Đã tải" kèm thời điểm.
3. `DELETE` bỏ ✓; `POST` đánh dấu tay; cả hai 404 khi không có output.
4. Đổi `output_vi.mp4` (size/mtime khác) → ✓ biến mất ở cả hai trang mà không cần sửa `web_download.json`.
5. Request có `Range` không ghi đè dấu hợp lệ.
6. Chưa đăng nhập (server bật mật khẩu) → `/download/...` và API mới bị chặn như `/media`.
7. Trang playlist: cột cũ đổi tên "Nguồn", cột "Video" mới; layout mobile vẫn đọc được (`data-label`).

## Required verification

- `$PY -m unittest discover -s tests` — toàn bộ suite PASS. Case mới:
  - `tests/test_web_library.py`: write/read/clear mark; output đổi mtime → None; JSON hỏng → None; `EpisodeSummary.downloaded_at` (AC2, AC4).
  - `tests/test_web_server.py` (TestClient): tải → header + body + file dấu (AC1, AC2); 404 không output / key lạ (AC1); `Range` không ghi đè dấu (AC5); POST/DELETE (AC3); HTML playlist có ✓ và tiêu đề cột "Nguồn"/"Video" (AC7); auth chặn khi bật mật khẩu (AC6).
- **Chạy thật** (server LAN thật, không có trình duyệt — dùng `curl` với cookie đăng nhập; mật khẩu ở `~/.config/dubber/web.env`, không in ra log/decision):
  1. Restart server bằng kill đúng PID (không `pkill -f`), chỉ khi không có job `queued`/`running`.
  2. `curl -c jar` đăng nhập; `curl -b jar -D - -o /tmp/... "http://10.8.102.102:8081/download/<key Episode 03>"` → xem header `Content-Disposition`, so `cmp` file tải với `output_vi.mp4`.
  3. `cat web_download.json` trong thư mục Episode 03; `curl` trang `/pl/<key Ocean Girl>` → grep thấy ✓ ở dòng Episode 03, không có ở tập chưa tải.
  4. `curl -X DELETE` → trang playlist mất ✓; tải lại → có ✓.
  5. Không có cookie → `/download/...` bị chặn (redirect login / 401 như `/media`).
  6. Ghi lại `web_download.json` của Episode 03 vào decision log mục C rồi để nguyên (HUMAN LEAD tự bỏ dấu nếu muốn).

## Manual test checklist (Tech Lead)

- Không chạm database / security model (dùng lại auth hiện có) / public API của pipeline. Thêm route web nội bộ.
- [ ] HUMAN LEAD bấm "Tải video lồng tiếng" trên điện thoại và desktop: file tải về đúng tên tiếng Việt, mở xem được.
- [ ] Trang playlist hiện ✓ ở tập vừa tải trên máy khác (trạng thái dùng chung).
- [ ] Giao diện sáng/tối, mobile: nút và ✓ dễ nhìn.

## Result

- Main changes: `GET /download/{key}` (attachment, tên `<title> - lồng tiếng.mp4`), `POST|DELETE /api/episodes/{key}/downloaded` (kiểm Origin); dấu `web_download.json` gắn size + mtime_ns của `output_vi.mp4`; trang tập có nút tải + "✓ Đã tải lúc HH:MM dd/mm/yyyy" + bỏ đánh dấu; trang playlist cột "Nguồn" (đổi tên) + cột "Video" (⬇ Tải, ✓ đã tải).
- Tests: 620 PASS (ORCHESTRATOR chạy lại). Case mới ở `tests/test_web_library.py`, `tests/test_web_server.py`.
- Review: ORCHESTRATOR 2026-10-17, 1 vòng sửa — thời điểm hiện ISO UTC thô -> filter `dl_time` (fallback server) + JS đổi sang giờ trình duyệt.
- Important findings / decisions: chạy thật trên server LAN (restart đúng PID, giờ là 1728663): file tải giống `output_vi.mp4` từng byte (141562844 B), `Content-Disposition` UTF-8 đúng; ✓ chỉ ở Episode 03; DELETE bỏ ✓; Range -> 206; không cookie -> 401. Dấu Episode 03 để nguyên.
- Known limitations:
  - Dấu ghi khi server bắt đầu gửi file, không biết client tải xong chưa (bỏ đánh dấu được).
  - Bấm ⬇ ở trang playlist không cập nhật ✓ tại chỗ — tải lại trang mới thấy.
  - Không có JS thì giờ hiện theo múi giờ server (UTC). Phần JS chưa kiểm trong trình duyệt thật.
- PR: — (commit thẳng main)

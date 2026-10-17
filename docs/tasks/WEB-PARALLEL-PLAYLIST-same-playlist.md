# Task: WEB-PARALLEL-PLAYLIST — Hai job khác tập của cùng một playlist được chạy song song

## Status / Approval

- Status: READY
- Type: CHANGE
- Change class: S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer (adapter duy nhất trong project-profile §7)
- Authorization mode: boundary
- Authorization source: APPROVE TASK 2026-10-17 (HUMAN LEAD: "APPROVE TASK WEB-PARALLEL-PLAYLIST") — ngoài boundary ADR-001 mục 0: sửa quyết định ADR-001 mục 10 và đổi contract ghi `playlist.json` của CP8 trong `app/pipeline/playlist.py`)
- Parallel group: —
- Owned paths: `app/pipeline/playlist.py`, `app/web/jobs.py`, `tests/test_pipeline_playlist.py`, `tests/test_web_jobs.py`, `docs/adr/ADR-001-web-ui.md`, `docs/decisions/checkpoint-8.md` (chỉ thêm mục sửa đổi), `docs/decisions/WEB-PARALLEL-PLAYLIST.md`, `README.md` (mục Web UI, nếu nhắc luật xung đột)
- Dependencies: WEB-PARALLEL (`e3c3be7`)
- Base commit / branch: e3c3be7 / main — working tree có WEB-MOBILE chưa commit (`app/web/static/*`, `app/web/templates/*`, docs); không giao owned paths, IMPLEMENTER không đụng
- Human Lead approval: accepted 2026-10-17
- Implementation authorized: YES

## Goal

Hai job playlist (hoặc job glossary/"dịch lại & chạy tiếp") của **cùng một playlist nhưng khác tập** chạy song song trong giới hạn `web.max_jobs`. Hai job đụng **cùng một tập** vẫn phải chờ nhau. `playlist.json` không mất cập nhật của job nào.

Ví dụ thật 2026-10-17: job `003671` (Ocean Girl `--items 3`) đang chạy, còn job `0096b5` (`--items 2 --recheck`, dịch lại sau khi sửa glossary) phải chờ ~35 phút dù hai job ghi vào hai thư mục tập khác nhau.

## Scope

- In scope:
  1. **Pipeline (`playlist.py`): ghi `playlist.json` an toàn khi nhiều tiến trình cùng chạy.**
  2. **Web (`jobs.py`): target theo tập thay cho cả playlist.**
  3. ADR-001: thêm mục 11 sửa đổi mục 10. `checkpoint-8.md`: thêm một mục sửa đổi ở cuối mục A (contract `playlist.json` giờ hỗ trợ nhiều writer). Decision log.
- Out of scope:
  - Song song *bên trong* một job playlist (vẫn xử lý tuần tự, plan §19).
  - Tăng trần `web.max_jobs` > 2.
  - Lock `<episode>/.lock` chống CLI chạy tay song song với web trên cùng tập (ADR-001 mục 7 — vẫn là rủi ro đã biết).
  - Đổi định dạng `playlist.json` (field, thứ tự) hoặc hành vi resume/skip.

## Authority / key decisions

- HUMAN LEAD 2026-10-17 (chat): "Sửa lại WEB-PARALLEL hai video cùng playlist cũng có thể chạy song song".
- ADR-001 mục 10 (WEB-PARALLEL): "cùng playlist … phải chờ". Task này sửa câu đó → S2.
- Lý do kỹ thuật của luật cũ (đã đọc code `e3c3be7`), cả hai đều phải sửa thì mới bỏ được luật:
  - (a) `run_playlist` giữ **toàn bộ** `state` trong RAM và ghi đè cả file sau mỗi tập. Hai tiến trình → lost update: tiến trình ghi sau xoá `status`/`episode_dir` mà tiến trình kia vừa ghi.
  - (b) File tạm cố định `playlist.json.tmp`. Hai tiến trình cùng ghi → `os.replace` của một bên có thể `FileNotFoundError` hoặc thay nhầm nội dung.
- `threading.Lock` hiện có (`entries_lock`) chỉ đồng bộ hai luồng *trong một tiến trình*. Phải giữ nó cho luồng tải ↔ luồng xử lý (checkpoint-8 B1).

## Implementation approach

### 1. `app/pipeline/playlist.py` — read-modify-write dưới file lock liên tiến trình

- Lock file `playlist.json.lock` cạnh `playlist.json`. Dùng stdlib, chạy cả Linux và Windows: POSIX `fcntl.flock(LOCK_EX)`, Windows `msvcrt.locking(LK_LOCK)` (import theo `os.name`). Helper context manager `_state_file_lock(path)`. Không thêm dependency.
- `_write_json_atomic`: tên tmp duy nhất theo tiến trình (vd `playlist.json.<pid>.tmp`).
- Mọi lần ghi state đi qua một hàm duy nhất, ví dụ `_persist_entry(state_path, state, entry)`: giữ lock file → đọc lại `playlist.json` từ đĩa → thay **chỉ entry có cùng `video_id`** bằng entry của tiến trình này (các field `_CARRIED_FIELDS` + `updated_at`) → giữ nguyên entry khác như trên đĩa → ghi atomic. Gọi bên trong `entries_lock` như hiện nay (thứ tự lock: `entries_lock` rồi file lock, không bao giờ ngược lại).
- Lần ghi đầu (sau `_merge_entries`): cũng dưới file lock, đọc lại file **ngay trong lock** rồi merge (không dùng `old_by_id` đọc trước lúc fetch, tránh ghi đè trạng thái job kia vừa cập nhật trong lúc fetch mạng).
- File hỏng vẫn raise `PlaylistError` như cũ, không tự ghi đè.

### 2. `app/web/jobs.py` — target theo tập

Thay set-intersection thô bằng target chi tiết + luật xung đột:

| Job | Targets |
|---|---|
| `dub` URL video X | `{video:X}` |
| `playlist` L, có `items` và map được **mọi** index → video_id qua `<workspace>/<L>__*/playlist.json` | `{video:<id> mỗi tập, in-playlist:L}` |
| `playlist` L, không `items` / chưa có `playlist.json` / có index không map được | `{playlist:L}` (cả playlist) |
| `glossary` tập X trong playlist L | `{video:X, in-playlist:L}` |
| `glossary` video lẻ X | `{video:X}` |

Luật xung đột (hàm thuần `targets_conflict(a, b)`): giao nhau khác rỗng, **hoặc** một bên có `playlist:L` và bên kia có `playlist:L` hay `in-playlist:L`. `_next_queued` dùng hàm này thay cho `targets & busy`.

- Việc đọc `playlist.json` chỉ xảy ra trong `_targets_of` (có workspace), để `job_targets` vẫn test được với dữ liệu inject (tham số map index→video_id hoặc hàm đọc). File không đọc được/hỏng → fallback `{playlist:L}` (bảo thủ).
- Parse `items` bằng `parse_item_spec` của `app/pipeline/playlist.py` (đã có), không viết parser thứ hai.

### Rủi ro đã biết (ghi decision log)

Map index→video_id lấy từ `playlist.json` lúc lập lịch. Nếu playlist trên YouTube bị sắp xếp lại giữa hai lần fetch, hai job có thể cùng chạy một tập. Lúc đó hai writer cùng ghi một thư mục tập: artifact ghi atomic nhưng tốn gấp đôi công. Chấp nhận, vì playlist hiếm khi sắp xếp lại giữa chừng; không thêm `.lock` theo tập (out of scope).

## Acceptance Criteria

1. Hai tiến trình `run_playlist` cùng playlist, khác tập, chạy đồng thời: cuối cùng `playlist.json` có trạng thái đúng của **cả hai** tập (không lost update) và JSON hợp lệ suốt quá trình.
2. Job web `playlist --items 2` và `playlist --items 3` cùng playlist (đã có `playlist.json`) chạy song song khi `max_jobs=2`.
3. Vẫn chờ nhau: `--items 2` vs `--items 1-3`; `--items 2` vs glossary/"dịch lại" của tập index 2; playlist không `items` vs bất kỳ job nào của playlist đó; playlist chưa có `playlist.json` vs job khác cùng playlist.
4. `dub` video lẻ X và tập X trong playlist vẫn chờ nhau (giữ hành vi bảo thủ cũ).
5. Hành vi một tiến trình (resume, skip, `--recheck`, `--force`, `--download-only`, đếm lỗi liên tiếp) không đổi — test cũ `test_pipeline_playlist.py` pass không sửa nghĩa.
6. Không dependency mới; chạy được trên Windows (nhánh `msvcrt` có test với mock hoặc ít nhất được import-guard đúng).

## Required verification

- `.venv/bin/python -m unittest discover -s tests` — toàn bộ PASS.
- Test mới: `targets_conflict` + `job_targets` bảng trên (inject map); `_next_queued` cho 2 job khác tập cùng playlist chạy cùng lúc, cùng tập thì chờ; `_persist_entry` merge đúng khi file trên đĩa đã có cập nhật của "tiến trình khác" (giả lập bằng cách ghi file giữa hai lần persist).
- **Chạy thật (luật bắt buộc 1):** hai lệnh CLI đồng thời trên playlist Ocean Girl `PLllZo-pkRkaEhoPJ6mM1DdIV94fifKPsn`, ví dụ `playlist <url> --items 6 --download-only` và `--items 7 --download-only` chạy nền cùng lúc (rẻ, không gọi Whisper/Ollama). Sau đó đọc `playlist.json`: cả hai entry `downloaded: true`, `episode_dir` đúng, không còn file `*.tmp`. Dán đoạn JSON vào Result.
- Restart server (memory: `kill <pid>`, không `pkill -f`), xác nhận trên `/jobs` hai job khác tập cùng playlist cùng `running`.

## Manual test checklist (Tech Lead)

Không chạm database, security model hay public API contract. Có đổi contract file `playlist.json` (nhiều writer), nên manual test là điểm danh sau automated verification + chạy thật.

- [ ] Trên web: tạo 2 job playlist Ocean Girl khác tập → cả hai `running` cùng lúc; xong cả hai, trang Playlist hiện đúng status từng tập.
- [ ] Tạo job trùng tập → job sau `queued` tới khi job trước xong.

## Result

- Main changes: `app/pipeline/playlist.py` (`_state_file_lock` fcntl/msvcrt, `_persist_entry` đọc lại đĩa và chỉ thay entry cùng `video_id`, tmp theo pid, lần ghi đầu merge trong lock); `app/web/jobs.py` (`job_targets(index_map=)` với nhãn `video:`/`in-playlist:`/`playlist:`, `targets_conflict`, `read_playlist_index_map`, `_next_queued` dùng luật mới). ADR-001 mục 11, `checkpoint-8.md` A5, README, `docs/decisions/WEB-PARALLEL-PLAYLIST.md`.
- Tests: 573 test OK (ORCHESTRATOR chạy lại). Có test mới cho multi-writer `playlist.json`, bảng targets/conflict, và trường hợp 2 job khác tập cùng chạy còn trùng tập thì chờ.
- Chạy thật:
  - IMPLEMENTER: 2 lệnh CLI đồng thời `--items 6` / `--items 7 --download-only` trên workspace tạm (scratchpad, vì job web code cũ đang ghi `output/`). Exit 0/0; `playlist.json` 27 entry, cả 6 và 7 `downloaded: true`, không còn `*.tmp`; `source.mp4` có video+audio (ffprobe).
  - ORCHESTRATOR: restart server (PID 1511004, `kill <pid>`) sau khi hàng đợi trống. Tạo 2 job web `--items 6` / `--items 7 --download-only` trên `output/`: job `20261017-105909-004682` và `-015ac6` cùng `running` lúc 10:59:09, xong 10:59:29 / 10:59:38, exit 0. `playlist.json` sau đó: tập 2, 3 vẫn `completed` (không bị ghi đè), tập 6, 7 `downloaded: true` với `updated_at` riêng; chỉ còn `playlist.json.lock`, không có `*.tmp`.
- Review: diff `app/` khớp contract. Thứ tự khoá `entries_lock` → file lock đúng. File hỏng vẫn raise `PlaylistError`. Fallback bảo thủ `playlist:<L>` khi không có `items`/không map được.
- Important findings / decisions: job glossary tập trong playlist đổi nhãn `playlist:<L>` → `in-playlist:<L>` (cần để không chặn job tập khác). Rủi ro playlist bị sắp xếp lại giữa hai lần fetch: ghi ở decision log.
- Known limitations: nhánh Windows `msvcrt` chưa chạy thật (chỉ import-guard theo `os.name`). Manual test checklist chưa tick: chờ HUMAN LEAD.
- PR: — (commit thẳng `main`).

# AGENTS.md

Entry point cho mọi agent làm việc trong repository này.

| Cần biết | Ở đâu |
|---|---|
| Quy trình S0/S1/S2, decision gate, lifecycle, review, integration | `docs/ai/workflow.md` |
| Vai trò HUMAN LEAD / ORCHESTRATOR / IMPLEMENTER | `docs/ai/execution-profiles.md` |
| Project này là gì, authority, module, policy, luật bắt buộc, setup, test | `docs/ai/project-profile.md` |
| Focus, blocker, open decision, next action | `docs/workflow/current-state.md` |
| Task contract S1/S2 (checkpoint) | `docs/tasks/_template.md` |
| Decision record (ADR) | `docs/adr/` |
| Lịch sử thay đổi framework sau adoption | `docs/ai/framework-history.md` |
| Kiến trúc pipeline, lộ trình checkpoint gốc | `docs/IMPLEMENTATION_PLAN.md` (chỉ đọc mục cần, offset/limit) |
| Dựng môi trường trên máy mới | `docs/SETUP.md` |

## Bootstrap

Đầu mỗi session/task, đọc theo thứ tự:

1. file này;
2. `docs/ai/project-profile.md`;
3. `docs/workflow/current-state.md`;
4. approved task contract, nếu có;
5. `AGENTS.md` gần nhất của subtree sắp sửa;
6. authority, source và tests liên quan.

Không preload toàn bộ tài liệu. Session mới bootstrap từ repository, không dựa vào transcript chat.

## Invariants

- Repository là source of truth; chat/session không thay thế authority, task contract hoặc source/tests.
- Tuân thứ tự authority trong `docs/ai/project-profile.md`.
- File lịch sử không được dùng làm authority hiện hành.
- Không mô tả thành phần mới chỉ được lên kế hoạch như đã implemented.
- Chỉ làm những gì authority và task contract đã duyệt; không âm thầm mở rộng scope.
- Không thay đổi architecture, dependency, security model, public API contract hoặc project-wide policy một cách âm thầm.
- Một normative rule chỉ có một canonical owner; nơi khác chỉ pointer tới rule.
- Không tuyên bố PASS cho verification chưa chạy thành công trong môi trường hiện tại.
- Không sửa test để che lỗi.

## Project boundary

- Implemented: CLI Python chạy local, pipeline download → transcribe → translate → tts → normalize → render, lệnh `dub` (CP7) và `playlist` (CP8).
- Planned, chưa có code: Web UI local WEB-1..2 (`docs/adr/ADR-001-web-ui.md`, ACCEPTED, boundary-authorized) và Checkpoint 9 (quality improvements, cần APPROVE TASK).

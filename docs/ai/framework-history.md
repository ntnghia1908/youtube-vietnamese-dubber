# Framework History

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Scope | Lịch sử thay đổi framework (core, adapter, checker) của project này sau adoption |

File này chỉ ghi lịch sử; rule hiện hành nằm ở canonical owner của nó (`docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, adapter, checker).

## Quy ước

- Mỗi thay đổi framework (core, adapter, checker) thêm một entry mới: ngày, thay đổi, lý do, PR/commit.
- Version tăng khi rule trong Framework Core thay đổi, hoặc khi HUMAN LEAD quyết một đợt thay đổi adapter / project policy đủ lớn để đánh version mới. Thay đổi nhỏ chỉ ở adapter hoặc checker ghi entry dưới version hiện tại, không tăng version.
- Heading version có dạng `## v<Version>`, khớp giá trị `Version` trong metadata của `docs/ai/workflow.md`; `scripts/framework-check.mjs` kiểm tra điều này.

## v4.4

- Ngày: 2026-10-17
- Thay đổi: adopt AI Dev Framework kit v4.4 (`ntnghia1908/ai-dev-framework`, `main` commit `92828b3`, kit chưa có tag). Chi tiết Adopted / Adapted / Not adopted: `FRAMEWORK_ADOPTION.md`.
- Lý do: tách luật dùng chung (workflow, vai trò, task contract, checker) khỏi `CLAUDE.md` để repository là source of truth và có checker cấu trúc; giữ luồng cũ `/spec` → duyệt → `/implement`.
- Decision: HUMAN LEAD yêu cầu adopt, 2026-10-17.
- Commit: `docs: adopt AI Dev Framework v4.4` (xem `git log`).

- Ngày: 2026-10-17 (sau adoption)
- Thay đổi: `governance.taskAuthorization` `task` → `boundary`; boundary đầu tiên: ADR-001 (WEB-1..3). Task ngoài boundary vẫn cần APPROVE TASK (`docs/ai/project-profile.md` §7). Cập nhật `/spec`, `/implement`, `.claude/rules/execution.md` theo.
- Lý do: HUMAN LEAD chọn "duyệt 1 lần" cho đợt Web UI (ADR-001 D6).

- Ngày: 2026-10-17
- Thay đổi: `governance.maxParallelImplementers` `1` → `2`; điều kiện đặc thù (worktree riêng, chạy thật khác thư mục tập, gộp decisions khi merge) ở `docs/ai/project-profile.md` §7; `.claude/rules/execution.md` theo.
- Lý do: HUMAN LEAD muốn chạy song song các task CP9/WEB không giao owned paths (vd CP9-B cùng lúc CP9-A).
- Decision: HUMAN LEAD, 2026-10-17 ("có thể đổi maxParallelImplementers = 2").

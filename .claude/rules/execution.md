# Claude Code — execution adapter

Adapter riêng cho Claude Code. Shared workflow nằm ở `AGENTS.md` và `docs/ai/`.

@../../docs/workflow/current-state.md

## Mapping vai trò

- `dual-agent`: main session (Opus) = ORCHESTRATOR — chỉ viết task contract (`/spec`) và review (`/implement`); `.claude/agents/implementer` (Sonnet) = IMPLEMENTER.
- `single-agent`: main session đóng cả ORCHESTRATOR + IMPLEMENTER; không delegate implementer. Dùng cho fix nhỏ, sửa docs, trả lời câu hỏi.
- Không gọi agent/model/AI CLI ngoài execution profile và field `Implementer` của task.

## Chọn IMPLEMENTER

Task `dual-agent`: ORCHESTRATOR chọn IMPLEMENTER theo Danh sách IMPLEMENTER ở `docs/ai/project-profile.md` §7 lúc viết contract và ghi vào field `Implementer`. Hiện chỉ có subagent `implementer`.

## Delegation

- `/spec N` → task contract `docs/tasks/<ID>-<slug>.md`, `Status: DRAFT`, `Authorization mode: boundary`.
  - Task nằm trọn trong boundary đã duyệt (`docs/ai/project-profile.md` §7): `Authorization source: <boundary>`, `Human Lead approval: inherited from boundary`, `Implementation authorized: YES`.
  - Ngoài boundary: `Implementation authorized: NO`; HUMAN LEAD gõ `APPROVE TASK` → ORCHESTRATOR sửa `Authorization source: APPROVE TASK <ngày>`, `Human Lead approval: accepted <ngày>`, `Implementation authorized: YES`, điền `Base commit`.
- `/implement N` → giao implementer kèm đường dẫn contract, base commit; agent tự đọc contract, không chép nội dung vào prompt.
- Cùng task thì resume đúng agent (`SendMessage`); task mới dùng context mới.

## Session

Bootstrap từ repository. Session mới không dùng transcript chat làm authority. Một agent mỗi checkpoint; tối đa 2 implementer song song theo `docs/ai/project-profile.md` §7 (mỗi cái một worktree, `isolation: "worktree"`).

## Kết thúc session

Rule session scope và handoff: `docs/ai/workflow.md` §9. Trong Claude Code, khi đủ scope thì đề xuất `/clear` và đưa handoff prompt trong một code block để dán vào session mới.

---
description: Opus (ORCHESTRATOR) viết task contract cho một checkpoint ra docs/tasks/CP-N-<slug>.md để giao Sonnet implement
argument-hint: <số checkpoint hoặc mã task>
---

Viết task contract cho **$ARGUMENTS** (số checkpoint `N` → file
`docs/tasks/CP-N-<slug>.md`; mã task như `WEB-1` → `docs/tasks/WEB-1-<slug>.md`).
Bạn chỉ thiết kế — không viết code, không sửa file nào ngoài file contract đó.

Đọc tối thiểu, theo thứ tự:

1. `git status --short` và `git log --oneline -5`. Working tree bẩn thì báo user.
2. `docs/workflow/current-state.md`; nếu task thuộc một ADR thì đọc ADR đó
   (`docs/adr/`) — ADR phải `ACCEPTED`, còn `PROPOSED` thì DỪNG và báo user.
3. `Grep "^# Checkpoint"` trong `docs/IMPLEMENTATION_PLAN.md` để lấy số dòng,
   rồi `Read` **chỉ** mục checkpoint này (offset/limit). Chỉ đọc thêm mục §
   khác (§8 data model, §10 config, §13 TTS, §17 resume…) khi thật cần.
4. Nếu có `docs/decisions/checkpoint-<N-1>.md`: đọc **mục A (Contract)** và
   các mục `[CẦN DUYỆT]`, không đọc cả file.
5. Interface cần tái sử dụng: `Grep "^def |^class "` trong module liên quan.
   Chỉ `Read` một đoạn khi cần chữ ký/schema chính xác.

Phân loại S1/S2 theo `docs/ai/workflow.md` §2. Chạm decision gate (§3:
dependency mới, kiến trúc, security, đổi contract artifact giữa stage…) mà
chưa có quyết định của user → hỏi user (AskUserQuestion) trước khi viết.

Ghi contract theo template sau (header lấy từ `docs/tasks/_template.md`).
Viết cụ thể đến mức Sonnet không phải dò repo: đường dẫn, chữ ký hàm, JSON
mẫu, lệnh chạy. Luật chung (chạy thật, resume, không hard-code, venv, tiếng
Việt) đã nằm trong `docs/ai/project-profile.md` §4 và
`.claude/agents/implementer.md` — **không lặp lại**, chỉ ghi phần đặc thù.

```markdown
# Task: CP<N> — <tên>

## Status / Approval

- Status: DRAFT
- Type: FEATURE | BUG | CHANGE | DOC
- Change class: S1 | S2
- Owner: HUMAN LEAD
- Execution profile: dual-agent
- Implementer: claude-code — subagent implementer
- Authorization mode: boundary
- Authorization source: <boundary trong project-profile §7, hoặc "APPROVE TASK (pending)">
- Parallel group: —
- Owned paths: <app/..., tests/...>
- Dependencies: <CP trước / none>
- Base commit / branch: <SHA hiện tại> / main
- Human Lead approval: <inherited from boundary | pending>
- Implementation authorized: <YES nếu nằm trọn trong boundary đã duyệt, ngược lại NO>

## Goal
<2–3 dòng, outcome quan sát được>

## Scope
- In scope:
- Out of scope:

## Authority / key decisions
- plan §..., ADR-..., docs/decisions/checkpoint-<N-1>.md mục A...

## Implementation approach

### File cần sửa/tạo
| Path | Việc cần làm |
|---|---|

### Interface
- chữ ký hàm/class chính (có type hint); tái sử dụng: <hàm> ở <path>

### Artifact
- Vào: <path> — JSON mẫu
- Ra: <path> — JSON mẫu

### Config
- key mới trong `config.example.yaml` + mặc định + flag CLI tương ứng

### Hành vi bắt buộc
- resume / --force / retry / cache / edge case cụ thể

### Điểm phải escalate

## Acceptance Criteria
1. ... (quan sát được, mỗi AC có verification tương ứng)

## Required verification
- `$PY -m unittest discover -s tests` — toàn bộ suite PASS; case mới: tests/test_xxx.py (liệt kê)
- **Chạy thật**: lệnh cụ thể + episode/video dùng thử (vd thư mục trong `output/` đã có artifact stage trước) + tiêu chí khi mở artifact + chạy lần 2 xác nhận SKIP — chứng minh AC ...

## Manual test checklist (Tech Lead)
- Không chạm database / security model / public API (hoặc ghi rõ nếu có).
- [ ] HUMAN LEAD nghe/xem artifact ... (nếu checkpoint đổi âm thanh/video)

## Result
- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:
```

Xong thì **DỪNG**: in ≤ 5 dòng tóm tắt các quyết định thiết kế chính.
Trong boundary → nhắc user có thể chạy `/implement $ARGUMENTS` (không cần
duyệt riêng). Ngoài boundary → nhắc user duyệt bằng `APPROVE TASK`; khi user
gõ: sửa `Authorization source: APPROVE TASK <ngày>`,
`Human Lead approval: accepted <ngày>`, `Implementation authorized: YES`,
cập nhật `Base commit`.

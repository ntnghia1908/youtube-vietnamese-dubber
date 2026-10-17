# Task: <ID — Title>

<!-- Task contract cho S1/S2. S0 không cần file này. -->

## Status / Approval

- Status: DRAFT
- Type: FEATURE | BUG | CHANGE | DOC
- Change class: S1 | S2
- Owner: <người chịu trách nhiệm — không ghi model/tool>
- Execution profile: dual-agent | single-agent
- Implementer: <chỉ dual-agent: adapter trong Danh sách IMPLEMENTER của docs/ai/project-profile.md §7 — lý do một dòng>
- Human Lead: <nếu khác Owner>
- Authorization mode: task | boundary
- Authorization source: <approved boundary / decision / task approval reference>
- Parallel group: <P0 / P1 / —>
- Owned paths: <disjoint file/subsystem boundary>
- Dependencies: <task IDs / none>
- Base commit / branch: <SHA / branch>
- Human Lead approval: <pending / accepted / inherited from boundary>
- Implementation authorized: NO

Lifecycle: `task` mode = `DRAFT → APPROVED → IN_PROGRESS → READY`; `boundary` mode = `DRAFT → IN_PROGRESS → READY`. DONE suy ra từ Git sau khi merge.

## Goal

<Observable outcome của vertical slice.>

## Scope

- In scope:
- Out of scope:

## Authority / key decisions

- <authority cần thiết; quyết định cục bộ S1 ghi ở đây>

## Implementation approach

- <hướng ngắn; không phải pseudo-code>

## Acceptance Criteria

1. ...

## Required verification

- `<command/test>` — chứng minh AC ...

Tất cả required verification phải chạy và PASS trước READY.

## Manual test checklist (Tech Lead)

Ghi rõ task có chạm database, security model hoặc public API contract hay không. Nếu có, manual test là gate trước integration; nếu không, manual test sau automated verification là điểm danh.

- [ ] ...

## Result

- Main changes:
- Tests:
- Review:
- Important findings / decisions:
- Known limitations:
- PR:

# AI Development Workflow

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Version | 4.4 |
| Accepted by | CP0 framework adoption; v4.1: HUMAN LEAD 2026-09-26 (FW-v4.1); v4.2: HUMAN LEAD 2026-09-29 (FW-implementer-speed); FW-starter-kit: HUMAN LEAD 2026-09-29; v4.3: HUMAN LEAD 2026-10-07 (ADR-001 / TASK-001); v4.4: HUMAN LEAD 2026-10-08 (ADR-002) |

> HUMAN LEAD quyết boundary. Agent tự thực thi bên trong boundary đã duyệt.

## 1. Vai trò

**HUMAN LEAD** quyết scope, architecture, dependency, security model, public API contract, breaking change, significant shared abstraction, project-wide policy/convention, commit/push, PR và merge. HUMAN LEAD cũng quyết **Implementation Authorization Boundary**: một boundary đã được chấp thuận có thể ủy quyền cho ORCHESTRATOR tự lập task graph và tự thực thi mọi task nằm hoàn toàn trong boundary, không cần `APPROVE TASK` từng task.

**ORCHESTRATOR** thảo luận decision mới với HUMAN LEAD, lập task graph và task contract, phân rã trong boundary, điều phối một hoặc nhiều IMPLEMENTER, review diff-first, điều phối fix/retest, cập nhật tài liệu trong boundary và báo READY. ORCHESTRATOR không được mở rộng Implementation Authorization Boundary.

**IMPLEMENTER** là người viết chính: implement, chạy required verification, sửa blocking finding trong boundary và retest. IMPLEMENTER chỉ bắt đầu khi có task contract, base commit, `Implementation authorized: YES` và plan ngắn. `Implementation authorized: YES` có thể đến từ **task approval** hoặc **boundary authorization** được ghi rõ trong task contract; thiếu authorization, contract hoặc base khớp → BLOCKED.

Vai trò được phân cho người/tool/model nào là việc của execution profile; mỗi task chọn một profile.

## 2. Phân loại — S-class

S-class là trục quyết định mức quy trình.

| Class | Điều kiện | Quy trình |
|---|---|---|
| **S0** | Mechanical only: typo, format, broken link, wording không đổi nghĩa/decision, đồng bộ state/pointer theo decision đã accepted. Không có source, test, config, SQL, script, dependency hay behavior change. | `INSPECT → CHANGE → VERIFY → INTEGRATION` |
| **S1** | Có code, test, config, script hoặc behavior nhưng không chạm decision gate và không tạo rule vượt task/feature. | `INSPECT → CLASSIFY → CONTRACT → AUTHORIZATION → EXECUTE → REVIEW → CONVERGE → READY → INTEGRATION` |
| **S2** | Chạm decision gate, thay đổi tài liệu class B, hoặc tạo rule tái sử dụng xuyên feature/module/project. | `DISCUSS → DECIDE → DOCUMENT → CONTRACT → AUTHORIZATION → EXECUTE → REVIEW → CONVERGE → READY → INTEGRATION` |

Class cao nhất thắng. S1 gặp decision gate → nâng S2. Không chắc S0 → tối thiểu S1.

## 3. Decision gates

Cần HUMAN LEAD quyết trước khi làm khi chạm: scope; architecture; dependency; security model; public API contract; breaking change; significant shared abstraction; project-wide policy/convention. Database/schema gate được giữ trong workflow vì framework có thể áp dụng cho project có database.

**Dependency proposal:**

```text
Library:
Purpose:
Why current stack is insufficient:
Alternative:
Impact:
```

Khi cần phá boundary:

```text
Issue → Evidence → Impact → Options → Recommendation → HUMAN LEAD Decision
```

Không dùng cập nhật tài liệu để tạo decision mới.

## 4. Task contract

Task là một lát cắt dọc vừa phải: behavior rõ, test và review độc lập. Một lát cắt có một owner chính. Task S1/S2 bắt buộc có `Type`, `Change class`, `Owner`, `Execution profile`, Goal, Scope in/out, Acceptance Criteria, Required verification và authority/reference khi cần. Task trong **boundary-authorized mode** thêm `Authorization source` và được gán vào một `Parallel group` nếu chạy song song.

Lifecycle phụ thuộc governance mode của project:

- `task-approved`: `DRAFT → APPROVED → IN_PROGRESS → READY`.
- `boundary-authorized`: `DRAFT → IN_PROGRESS → READY`; `APPROVED` không phải gate bắt buộc.

`DONE = READY + integrated into target branch`, suy ra từ Git.

Trong `task-approved`, `APPROVE TASK` duyệt goal, boundary, decisions, approach, AC và verification. Trong `boundary-authorized`, HUMAN LEAD duyệt **Implementation Authorization Boundary** ở cấp requirement/feature/architecture; ORCHESTRATOR kế thừa authorization đó cho task nằm hoàn toàn trong boundary và ghi nguồn authorization vào task contract.

## 5. Authorization và thực thi

Project chọn một trong hai governance mode qua `framework.config.json`:

```json
{
  "governance": {
    "taskAuthorization": "task | boundary",
    "maxParallelImplementers": 1
  }
}
```

- `task`: giữ workflow tương thích ngược, cần `APPROVE TASK` trước thực thi.
- `boundary`: HUMAN LEAD phê duyệt boundary một lần; task contract bên trong boundary không cần approve riêng. `Implementation authorized: YES` phải chỉ ra `Authorization source` cụ thể.

Sau authorization:

```text
TASK GRAPH → IMPLEMENT + REQUIRED VERIFICATION → REVIEW → FIX / RETEST / VERIFY → READY → INTEGRATION
```

### Bounded parallel IMPLEMENTER

ORCHESTRATOR được fan-out nhiều **instance của cùng role IMPLEMENTER** khi task graph chứng minh các task độc lập. Parallel group chỉ hợp lệ khi:

1. dependencies đã thỏa mãn;
2. owned files/subsystems không giao nhau;
3. không có shared decision chưa chốt;
4. mỗi implementer có branch/worktree riêng;
5. mỗi task có verification boundary độc lập;
6. tổng số implementer đồng thời không vượt `maxParallelImplementers`.

`maxParallelImplementers` mặc định `1`; project có thể đặt `2` hoặc `3` (tối đa `3` ở v4.4). Không tạo parallelism giả. Nếu có xung đột ownership hoặc merge risk, serialize.

```text
                 ORCHESTRATOR
                      │
             ┌────────┼────────┐
             ▼        ▼        ▼
           TASK-A   TASK-B   TASK-C
           Impl-1   Impl-2   Impl-3
             │        │        │
             └────────┼────────┘
                      ▼
                  INTEGRATION
```

Một task không được có hai writer đồng thời. Song song là **task-level fan-out**, không phải hai agent cùng sửa một task.

## 6. Dừng và BLOCKED

Dừng khi: chạm decision gate; required verification không chạy hoặc không PASS; base/authority conflict; cùng một blocking issue chưa giải quyết sau hai lần sửa; review mở rộng vượt boundary.

Circuit breaker:

```text
same blocker → fix 1 → review → fix 2 → review → still failing = BLOCKED
```

Finding ngoài scope phải ghi nhận và báo HUMAN LEAD, không tự sửa.

## 7. Verification và review

Required verification phải trực tiếp chứng minh AC và tất cả phải PASS trước READY. Review theo `task contract → diff → AC → verification evidence`; review không phải pha redesign.

Blocking finding: AC fail, bug, regression, security risk thực tế, vi phạm authority/rule hoặc maintainability risk đáng kể. Non-blocking tối đa 3 note có giá trị; không chặn READY.

Single-agent vẫn bắt buộc có pha review riêng trước READY.

## 8. Integration

Mọi thay đổi đi qua integration mechanism của project. `READY` không cần `APPROVE TASK` lần nữa trong boundary-authorized mode, nhưng vẫn dừng tại **integration gate** theo policy của project: push/PR/merge do cơ chế integration quyết định và HUMAN LEAD vẫn là người merge khi project quy định như vậy.

Definition of Done: AC đạt, required verification PASS, blocking finding giải quyết, documentation impact xử lý, review ACCEPTED, thay đổi đã integrate và integration không làm hỏng target branch.

## 9. Session scope và handoff

Mỗi session có một **session scope**: một checkpoint/task hoặc một phần rõ ràng của nó, xác định từ repository và yêu cầu HUMAN LEAD. Agent nêu scope trong phản hồi đầu tiên.

Session kết thúc khi scope đạt READY/DONE, dừng ở gate chờ HUMAN LEAD, hoặc context đã dài tới mức ảnh hưởng chất lượng. Khi scope đã xong, không mở scope mới trong session cũ; đề xuất session mới thay vì kéo dài.

Trước khi đề xuất đóng session, state phải nằm trong repository. Agent đề xuất đóng session và đưa **handoff prompt** ngắn (≤ ~10 dòng) gồm: mục tiêu session sau; bootstrap từ repository, không dựa transcript; trạng thái/gate hiện tại; việc đầu tiên cần làm. Handoff prompt không thay repository làm source of truth.

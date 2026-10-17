# Execution Profiles

| Metadata | Value |
|---|---|
| Status | CURRENT |
| Version | 4.4 |
| Accepted by | CP0 framework adoption; FW-starter-kit: HUMAN LEAD 2026-09-29 |

Profile chỉ **thêm** ràng buộc thực thi, không nới lỏng workflow. Decision gate, task boundary, một writer/branch, required verification, không claim PASS, quyền integrate và điều kiện dừng thuộc workflow. Governance mode (`task` hoặc `boundary`) quyết định task approval có phải gate hay không; execution profile không thể tự cấp authorization.

Mỗi task ghi `Execution profile`. Một branch dùng một profile cho cùng task; đổi profile cần HUMAN LEAD approve.

## `dual-agent`

| Vai trò | Tác nhân |
|---|---|
| HUMAN LEAD | người |
| ORCHESTRATOR | agent A |
| IMPLEMENTER | một hoặc nhiều instance của agent B |

IMPLEMENTER là người viết chính; ORCHESTRATOR review diff. ORCHESTRATOR có thể fan-out **2–3 IMPLEMENTER instances** cho các task độc lập trong cùng task graph khi governance mode và project config cho phép. Mỗi instance có branch/worktree riêng và một ownership boundary không giao nhau. ORCHESTRATOR chỉ micro-fix khi thay đổi cục bộ, hiển nhiên, không đổi behavior/contract/architecture/security/business logic và nằm trong giới hạn nhỏ của task. Lớn hơn thì trả IMPLEMENTER.

## `single-agent`

| Vai trò | Tác nhân |
|---|---|
| HUMAN LEAD | người |
| ORCHESTRATOR | cùng agent |
| IMPLEMENTER | cùng agent |

Không có review độc lập giữa hai agent, nhưng bắt buộc có pha review riêng:

```text
task contract → diff → acceptance criteria → verification evidence → findings/fix → converge
```

Không áp dụng ranh giới micro-fix giữa ORCHESTRATOR và IMPLEMENTER vì là cùng một tác nhân.

## Adapter và vendor

Không hard-code tên vendor/model trong framework core. Tool adapter quyết định cách một tool cụ thể thực hiện profile.

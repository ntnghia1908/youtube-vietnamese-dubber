---
description: Giao subagent Sonnet (IMPLEMENTER) implement task contract docs/tasks/CP-N-*.md, rồi Opus review
argument-hint: <số checkpoint hoặc mã task>
---

Implement **$ARGUMENTS** qua subagent — bạn (Opus, ORCHESTRATOR)
không tự viết code.

1. Tìm `docs/tasks/CP-$ARGUMENTS-*.md` (hoặc `docs/tasks/$ARGUMENTS-*.md` với
   mã như `WEB-1`). Không có → bảo user chạy `/spec $ARGUMENTS` rồi DỪNG. Có
   nhưng `Implementation authorized` khác `YES` → nhắc user duyệt
   (`APPROVE TASK`) rồi DỪNG.
2. Đặt `Status: IN_PROGRESS` trong contract. Gọi `Agent` với
   `subagent_type: "implementer"`, prompt 1–3 dòng:
   `Implement theo <đường dẫn contract>. Base commit <SHA>.` — **không** chép
   nội dung contract vào prompt (agent tự đọc file).
3. Khi nhận báo cáo:
   - `CẦN QUYẾT ĐỊNH` → nếu là quyết định thiết kế / decision gate thì hỏi
     user bằng AskUserQuestion; trả lời agent qua `SendMessage` (cùng agent,
     giữ context).
   - Review diff-first theo `contract → diff → AC → bằng chứng verification`
     (`docs/ai/workflow.md` §7), tiết kiệm token:
     - `git diff --stat`, rồi `git diff` **chỉ các file trong `app/`**.
       File test chỉ xem tên case (`Grep "def test_"`).
     - Tự mở artifact chạy thật (vài dòng đầu, đếm phần tử, `ffprobe` nếu
       là audio/video) — không chỉ tin phần trích trong báo cáo.
     - Decision log của task (`docs/decisions/checkpoint-N.md` hoặc
     `docs/decisions/<ID>.md`): chỉ đọc mục A và `[CẦN DUYỆT]`.
     - Chạy lại toàn bộ suite một lần theo Test policy
       (`docs/ai/project-profile.md` §8), lấy `| tail -3`.
   - Blocking finding → gửi danh sách sửa cụ thể (file:dòng + lý do) qua
     `SendMessage` cho **cùng agent**, không spawn agent mới. Tối đa 2 vòng
     sửa cho cùng một lỗi (circuit breaker); quá thì BLOCKED, báo user.
4. Hết blocking → điền mục Result của contract, đặt `Status: READY`, tóm tắt
   cho user (file đã đổi, kết quả chạy thật, quyết định `[CẦN DUYỆT]`, phần
   chưa làm, manual test checklist cho user), đề xuất commit
   `checkpoint-N: ...` / `web-N: ...` (tiếng Việt, gồm contract và decisions),
   commit luôn (không cần hỏi — `docs/ai/project-profile.md` §5). Cập nhật `docs/workflow/current-state.md` nếu
   focus/next action đổi. Nhắc `/clear` kèm handoff prompt. **DỪNG** —
   không mở checkpoint tiếp theo.

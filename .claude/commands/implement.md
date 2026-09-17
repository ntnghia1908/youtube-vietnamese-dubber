---
description: Giao subagent Sonnet implement docs/specs/cp-N.md, rồi Opus review
argument-hint: <số checkpoint>
---

Implement **Checkpoint $ARGUMENTS** qua subagent — bạn (Opus) không tự viết code.

1. Kiểm tra `docs/specs/cp-$ARGUMENTS.md` tồn tại. Không có → bảo user chạy
   `/spec $ARGUMENTS` rồi DỪNG.
2. Gọi `Agent` với `subagent_type: "implementer"`, prompt 1–3 dòng:
   `Implement theo docs/specs/cp-$ARGUMENTS.md.` — **không** chép nội dung
   spec vào prompt (agent tự đọc file).
3. Khi nhận báo cáo:
   - `CẦN QUYẾT ĐỊNH` → nếu là quyết định thiết kế thì hỏi user bằng
     AskUserQuestion; trả lời agent qua `SendMessage` (cùng agent, giữ context).
   - Review tiết kiệm token:
     - `git diff --stat`, rồi `git diff` **chỉ các file trong `app/`**.
       File test chỉ xem tên case (`Grep "def test_"`).
     - Tự mở artifact chạy thật (vài dòng đầu, đếm phần tử, `ffprobe` nếu
       là audio/video) — không chỉ tin phần trích trong báo cáo.
     - `docs/decisions/checkpoint-$ARGUMENTS.md`: chỉ đọc mục A và `[CẦN DUYỆT]`.
     - Chạy lại test một lần: `.venv/Scripts/python.exe -m unittest discover -s tests 2>&1 | tail -3`.
   - Có lỗi → gửi danh sách sửa cụ thể (file:dòng + lý do) qua `SendMessage`
     cho **cùng agent**, không spawn agent mới. Tối đa 2 vòng sửa; quá thì
     dừng và báo user.
4. Đạt → tóm tắt cho user (file đã đổi, kết quả chạy thật, quyết định
   `[CẦN DUYỆT]`, phần chưa làm), đề xuất commit
   `checkpoint-$ARGUMENTS: ...` (tiếng Việt, gồm cả spec và decisions),
   commit khi user đồng ý. Nhắc `/clear` trước checkpoint kế. **DỪNG** —
   không mở checkpoint tiếp theo.

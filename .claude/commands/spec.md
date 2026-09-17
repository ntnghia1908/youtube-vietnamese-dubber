---
description: Opus viết spec cho một checkpoint ra docs/specs/cp-N.md để giao Sonnet implement
argument-hint: <số checkpoint>
---

Viết spec cho **Checkpoint $ARGUMENTS**. Bạn chỉ thiết kế — không viết code,
không sửa file nào ngoài `docs/specs/cp-$ARGUMENTS.md`.

Đọc tối thiểu, theo thứ tự:

1. `git status --short` và `git log --oneline -5`. Working tree bẩn thì báo user.
2. `Grep "^# Checkpoint"` trong `docs/IMPLEMENTATION_PLAN.md` để lấy số dòng,
   rồi `Read` **chỉ** mục checkpoint này (offset/limit). Chỉ đọc thêm mục §
   khác (§8 data model, §10 config, §13 TTS, §17 resume…) khi thật cần —
   cũng bằng offset/limit.
3. Nếu có `docs/decisions/checkpoint-<N-1>.md`: đọc **mục A (Contract)** và
   các mục `[CẦN DUYỆT]`, không đọc cả file.
4. Interface cần tái sử dụng: `Grep "^def |^class "` trong module liên quan.
   Chỉ `Read` một đoạn khi cần chữ ký/schema chính xác.

Ghi `docs/specs/cp-$ARGUMENTS.md` theo template sau. Viết cụ thể đến mức
Sonnet không phải dò repo: đường dẫn, chữ ký hàm, JSON mẫu, lệnh chạy.
Các luật chung (chạy thật, resume, không hard-code, venv, tiếng Việt) đã
nằm trong `.claude/agents/implementer.md` — **không lặp lại** trong spec,
chỉ ghi phần đặc thù của checkpoint này.

```markdown
# CP<N> — <tên>

## Mục tiêu
<2–3 dòng>

## File cần sửa/tạo
| Path | Việc cần làm |
|---|---|

## Interface
- chữ ký hàm/class chính (có type hint)
- tái sử dụng: <hàm có sẵn> ở <path>

## Artifact
- Vào: <path> — JSON mẫu
- Ra: <path> — JSON mẫu

## Config
- key mới trong `config.example.yaml` + giá trị mặc định + flag CLI tương ứng

## Hành vi bắt buộc
- resume / --force / retry / cache / edge case cụ thể của checkpoint này

## Test (unittest, mock tiến trình/dịch vụ ngoài)
- tests/test_xxx.py: danh sách case

## Chạy thật (BẮT BUỘC)
- lệnh cụ thể + episode dùng để thử (vd thư mục trong `output/` đã có artifact của stage trước)
- tiêu chí đạt khi mở artifact

## Ngoài phạm vi

## Điểm phải escalate
```

Xong thì **DỪNG**: in ≤ 5 dòng tóm tắt các quyết định thiết kế chính và
nhắc user duyệt spec rồi chạy `/implement $ARGUMENTS`.

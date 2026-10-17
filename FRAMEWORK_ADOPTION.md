# Framework Adoption Record

## Reference

- Framework kit: `git@github.com:ntnghia1908/ai-dev-framework.git`, VERSION `4.4`, branch `main` commit `92828b3` (kit chưa gắn tag).
- Adoption date / decision: 2026-10-17 — HUMAN LEAD yêu cầu "tải AI agent framework … và adapt vào project hiện tại".

Thay đổi framework sau adoption ghi ở `docs/ai/framework-history.md`.

## Adopted

- Core nguyên văn: `docs/ai/workflow.md`, `docs/ai/execution-profiles.md`, `docs/ai/agent-adapter-contract.md`, `docs/ai/adapter-descriptor.schema.json`.
- Template task contract `docs/tasks/_template.md`.
- Checker `scripts/framework-check.mjs` (Node ≥ 20).
- Adapter `claude-code`: `adapters/claude-code/adapter.json`, `README.md`, `.claude/rules/execution.md`; `CLAUDE.md` thành bridge `@AGENTS.md`.

## Adapted

- `CLAUDE.md` cũ được tách theo canonical owner: mô tả project, luật bắt buộc, quy ước code, bẫy môi trường, test, cách giao việc → `docs/ai/project-profile.md`; "Việc tiếp theo" + nợ → `docs/workflow/current-state.md`; bảng tra cứu tài liệu → `AGENTS.md`.
- `.claude/agents/implementer.md`: giữ subagent riêng của project (luật đã trả giá, format báo cáo cuối), thêm bước bootstrap của framework (AGENTS.md → project-profile → current-state → task contract); đổi nguồn việc từ `docs/specs/cp-N.md` sang task contract `docs/tasks/CP-N-*.md`. Không chép `implementer.md` generic của kit để tránh hai bản.
- `.claude/commands/spec.md` / `implement.md`: `/spec` sinh task contract theo `_template.md` (header Status/Approval + Goal/Scope/AC/Required verification) cộng các mục spec đặc thù checkpoint (Interface, Artifact, Config, Chạy thật…); `/implement` chỉ chạy khi `Implementation authorized: YES`.
- Governance: adopt với `task`, cùng ngày chuyển `boundary` (ADR-001 D6, xem `docs/ai/framework-history.md`); `maxParallelImplementers: 1` — một agent mỗi checkpoint vì checkpoint sau ăn output checkpoint trước.
- `decisionDir` = `docs/adr` (ADR mới theo format framework). `docs/decisions/checkpoint-N.md` giữ nguyên vai trò log quyết định triển khai + contract giữa checkpoint, không có metadata `Status` nên không đưa vào checker.
- Lệnh Python ghi dạng `$PY` (Windows `.venv/Scripts/python.exe`, Linux `.venv/bin/python`) vì máy dev đã chuyển sang Linux.
- `requiredFiles` / `requiredTokens`: giữ plan, SETUP, hai slash command và ba luật bắt buộc trong project profile.

## Not adopted

- Adapter `chatgpt` + Product Layer (`docs/product/`, `PRODUCT_AGENT.md`, `REQUIREMENT_HANDOFF.md`, `scripts/product-check.mjs`): project một người, chưa dùng ChatGPT làm Product Agent; yêu cầu mới đi qua ADR + task contract. Có thể adopt sau khi có nhu cầu.
- `.github/workflows/requirement-to-task.yml`: phụ thuộc Product Layer và secret `ANTHROPIC_API_KEY` trên CI; project chưa có CI.
- Adapter `copilot`, `codex`: không dùng.
- `docs/specs/cp-*.md` cũ không chuyển sang format task contract — là lịch sử, không phải authority.

## Adoption boundary

Adoption chỉ đổi tài liệu và cấu hình agent; không đổi code `app/` hay `tests/`. Không authorize implement CP9. Web UI WEB-1..2 được authorize riêng bởi ADR-001 (ACCEPTED 2026-10-17), không phải bởi adoption.

## Verification status

- `node scripts/framework-check.mjs`: PASS ngày 2026-10-17 (exit 0).
- Pilot S1 theo luồng mới (`/spec` → APPROVE TASK → `/implement`): CHƯA làm — đề xuất pilot bằng task S1 nhỏ đầu tiên (vd `fix(tts)` backoff).

# Adapter Claude Code

Copy `.claude/` vào root project; `CLAUDE.md` (bridge `@AGENTS.md`) nằm ở `templates/`.

- `.claude/rules/execution.md`: mapping vai trò `dual-agent` / `single-agent`, delegation, kết thúc session. Import `docs/workflow/current-state.md`.
- `.claude/agents/implementer.md`: subagent IMPLEMENTER. `model: sonnet` là mặc định của kit; đổi ở frontmatter nếu project cần model khác. Task cần model khác riêng lẻ thì ghi trong task contract và ORCHESTRATOR truyền override lúc delegate.

Bật trong `framework.config.json`: `"adapters": ["claude-code"]`.

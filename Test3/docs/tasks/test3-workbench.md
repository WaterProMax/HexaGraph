# TASK test3-workbench

- TASK_ID: test3-workbench
- MODE: 2
- SCALE: L
- CONTRACT_PATH: docs/contracts/test3-contract.md
- PHASE_STATUS: Phase 3（M1 可跑；P07–P17 部分落地；E1–E10 与真联调未做）
- COVERAGE_GATE: unset
- INTEGRATION_BRANCH: teamwork-001

## In-Scope

按 ImplementationPlan.md 实现 `Test3/`：P00–P17。M1（P00–P06）必须完整可跑；其后阶段能落地的做完，做不到的写入 `docs/Handoff.md`。

## Non-Goals

- 不使用 LangGraph / AutoGen
- 不复制 Test1 / Test2
- 不提交真实密钥
- 不改 GitHub Issue、不指派、不 force-push
- 不做代码评审循环

## File Whitelist

`Test3/**`（含 `backend/`、`frontend/`、`config/`、`prompts/`、`scripts/`、`examples/`、`docs/`、Makefile、README、`.env.example`、`.gitignore`）以及仓库根目录仅当需要指向 Test3 的说明。

## 验证命令（本轮结果）

1. `cd backend && uv run ruff check app tests` → All checks passed
2. `cd backend && uv run pytest -q -m "not live"` → 55 passed
3. `cd backend && uv run pytest -q tests/unit/test_discussion_rules.py` → 含金标准 13 项，包含在 55 内
4. `cd backend && uv run pytest -q tests/e2e/test_m1_study_room.py` → passed
5. `cd frontend && npm test` → 1 passed
6. HTTP `GET /api/health` + 两次 scripted M1 至关卡 `SPEC基线确认` → 通过
7. `make check-models` / `make test-live` → 未跑（无密钥）

## 验收

见 `docs/Acceptance.md`。完成声明必须绑定本轮实测命令输出；不得把 scripted M1 写成百炼联调。

# Test3 长期规则

Mode：Mode 2（已有仓库，按 teamwork-001 设计在 `Test3/` 从零实现）。
Scale：L（完整多体工作流工作台）。

## 权威真源层级

1. 运行中的代码与测试输出
2. `Design.md`（流程规则、通过条件、上限）
3. `Architecture.md`（模块、数据、接口、目录）
4. `ImplementationPlan.md`（阶段、验收、配置键）
5. 本文件与 `docs/contracts/test3-contract.md`

`CONTRACT_PATH`：`docs/contracts/test3-contract.md`
`TASK_PLAN_PATH`：`docs/tasks/test3-workbench.md`

设计文档已由负责人在 `teamwork-001` 确认。本轮任务按该契约实现，不另起规则。

## 技术栈

- 后端：Python 3.11+，FastAPI，Pydantic v2，SQLAlchemy 2 异步 + aiosqlite，Alembic
- 前端：React 18，TypeScript，Vite，Ant Design 5，TanStack Query，`@xyflow/react`
- 模型：阿里云百炼 OpenAI 兼容接口；测试用 `scripted` / `replay`
- 不使用 LangGraph、AutoGen 或其它 Agent 框架
- 规则必须是确定性纯函数
- SQLite 每个连接执行 `PRAGMA foreign_keys = ON` 与 `WAL`
- 密钥不入库、不进响应、不进日志。默认来自环境变量；Bot 自带的 API Key（创建/更新时只写）加密存于 `<data_dir>/secrets/`（Fernet，`master.key` 权限 0600），仅在调用时读取

## 硬上限（不得擅自改）

- 任务并发 6
- 每任务最多修复 6 轮
- 每点 150 万令牌
- P1 验收通过线 90%

## 分层

`api` → 引擎（stage / discussion / docs / orchestrator / change / listening）→ `agents` / `trace` / `workspace` / `storage` / `events` → `llm` / `tools`

任务状态只能经 `orchestrator.transition.transition()` 修改。

## Git

集成分支是 `teamwork-001`。功能分支提交，禁止直改 `main`，禁止 force-push。

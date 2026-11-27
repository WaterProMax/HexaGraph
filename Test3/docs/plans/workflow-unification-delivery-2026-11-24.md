# HexaGraph 工作流统一交付总结（2026-11-24，本地）

交付 HEAD：`e8f8a53`（代码+本文件；其后仅有一个补充本行 HEAD 记录的文档提交）。
分支：`feat/test3-agent-team-v1`
起点：`63e3608`（与参考 SHA 相同）
交付方式：仅本地提交，未 push、未改线上 PR、未调用付费模型、未清理用户未跟踪文件。

## 1. 变更清单（按卡）

### 卡 1：内部阶段投影与阶段准入

- 新增 `Test3/backend/app/workflow/stages.py`：内部阶段枚举与全部 discussion.status 映射。
- 新增 `Test3/backend/app/workflow/projection.py`：纯查询投影（stage / 旧 status / blocked / 基线哈希 / 项目-会话绑定），跨项目、跨会话 fail-closed；不写库。
- 新增 `Test3/backend/app/workflow/admission.py`：`/plan`、PLAN 门、schedule/execute/accept 的服务端准入。
- `GET /runs/{id}`、`/monitor`、`GET /discussion-sessions/{id}` 附加 `workflow`；`/plan` 409 附加 `workflow`，原 `error_category` 与「需先确认需求规格」文案不变。
- 旧 fixture run（无 PLAN 门）保持兼容；未确认 PLAN 的讨论 run 不放行执行。

### 卡 2：证据分级与缺 key 失效关闭

- 新增 `app/workflow/evidence.py`：独立维度 `model_mode`（scripted/real/not_called）、`execution_mode`（simulated/real/not_run）、`verification_status`（not_run/unknown/passed/failed）与 `level`（not_run/scripted/real_model/real_execution）。
- monitor、run 查询、accept、模块验收/缺陷、execution-profile 响应附加 `evidence`（加法）；scripted 只显示“脚本/模拟验收”。
- `bot_endpoint`：真实 provider 下 Bot 无自身 key 抛 `missing_bot_key`，不再回退工作台默认钥匙；scripted/replay 返回 None 以保持离线测试。讨论 `_call` 将该错误转为 `BotFailed`。
- 相关旧测试改为显式提供测试 key，或断言 fail-closed。

### 卡 3：统一执行授权入口

- 新增 `app/execution/authorization.py::decide_execution`：阶段准入 + profile + 模拟模式 + 总闸的统一决策，不新建 grant 存储。
- `schedule_once`、`_execute_task_locked`、任务 control（retry/takeover/submit-takeover/force-pass）、`accept` 全部调用同一决策。
- legacy + 真实 provider → 403 `profile_not_granted_v1`。**2026-11-24 边界修复更正**：scripted/replay provider 本身不再是模拟例外；只有显式注入的无副作用模拟执行器才允许 legacy 调度（见 `workflow-boundary-fixes-delivery-2026-11-24.md`）。
- 未打开 `execution_safety_ready`，未新增开闸 UI。

### 卡 4：幂等与第一轮出口

- `prepare_run` 复用已持久化 run 前校验 project/session 绑定；重启后返回同一 run_id，不重复生成。
- SPEC/DESIGN/PLAN 门批准记录 `resolved_by` / `resolved_at`，并追加 `artifacts.approvals`（project/run/session/hash 绑定，只增不删）。
- 并发测试：双击 `/plan` 只生成一次；双击 gate resolve 只推进一次；双击 schedule 只派发一次；canonical hash 稳定性。
- 第一轮回归全部通过（见第 2 节）。

### 卡 5：基线失效与重新批准

- 新增 `app/workflow/invalidation.py`：比较已批准 SPEC/DESIGN/PLAN/DecisionPackage 与当前产物哈希；只对存在人工批准记录（`artifacts.approvals`）的 run 生效，避免测试夹具的占位哈希误报。
- 漂移时：run 暂停、`workflow_invalidations` 追加历史、active grant 标 `stale`、投影为 `invalidated`/`baseline_stale`；`schedule`/执行/`accept` 一致拒绝。
- 重新批准生成新哈希；旧 grant 不复活，必须新建覆盖新基线的 grant；历史失效记录保留。**更正**：失效时会自动新建 pending `PLAN基线确认` 门，经既有 `POST /gates/{id}/resolve` 采用新基线；不再需要手工 append 门或改 paused。

### 卡 6：P5 返工适配与崩溃和解

- 重启时 `recover_tasks` 之后，把原本 running/verifying 且无证据的任务标 `needs_reconciliation` 并暂停；调度器不自动重放。
- 新增只读 `POST /api/runs/{id}/reconcile`（任务、状态、证据数、`unknown`）；手动 retry 与显式 schedule 对该类任务返回 409 `needs_reconciliation`。
- 模块验收 `accepted` 复验：旧 open/reopened 缺陷标 `resolved`，记录 `resolved_by_acceptance_id` / `resolved_at`，原缺陷行与证据保留。
- 差距见 `Test3/docs/plans/p5-rework-gaps-2026-11-24.md`。

### 测试/文档

- 新增后端测试：`test_workflow_projection.py`、`test_workflow_admission.py`、`test_discussion_plan_api.py`、`test_workflow_evidence.py`、`test_bot_key_fail_closed.py`、`test_workflow_evidence_api.py`、`test_execution_authorization_policy.py`、`test_execution_entrypoint_authorization.py`、`test_workflow_idempotency.py`、`test_workflow_invalidation.py`、`test_workflow_recovery.py`；扩展 `test_module_acceptance_and_defects.py`。
- 前端：仅修 `e2e/integration/discussion-flow.pw.ts` 的弹窗关闭前置（HEAD 63e3608 的 UI 与旧测试不匹配），未改产品 UI。
- 文档：本文件、开工审计、P5 差距、`docs/API.md` 加法说明、OpenAPI 快照（仅新增 reconcile 路由）。

## 2. 测试命令与实际结果

| 项 | 命令 | 实际结果 |
|---|---|---|
| 改前后端基线 | `cd Test3/backend && uv run pytest -q -m "not live"` | 退出码 0；收集 754 个离线用例（当时未打印计数，以退出码+收集数为准） |
| 第一轮后端回归 | 同上 | 809 passed, 3 skipped, 2 deselected；退出码 0 |
| 最终后端全量 | `uv run pytest -m "not live" -o addopts="" -q` | **817 passed, 3 skipped, 2 deselected, 1 warning, 47.84s；退出码 0** |
| 前端单元测试 | `cd Test3/frontend && npm test` | **51 files / 427 tests passed，22.31s** |
| 前端生产构建 | `npm run build` | 成功（4.24s；仅有既有 chunk >500kB 警告） |
| 讨论 e2e（scripted，最终代码） | `npx playwright test --config playwright.discussion.config.ts` | **1 passed (10.2s, 总 12.6s)；退出码 0** |
| `pytest -m live` | — | **未跑**：需要真实/付费模型，未授权 |
| 真实 sandbox 写入 | — | **未跑**：`execution_safety_ready` 保持 False，按设计不可达 |

3 个 skipped 为本仓库既有 `closeout/live` 相关跳过项，本轮未删改其断言。

## 3. 人工验收记录

- 只读确认：`GET /runs/{id}`、`/monitor`、`GET /discussion-sessions/{id}` 新增 `workflow` 后，前端既有 Vitest 与讨论 e2e 均通过，无白屏或解析失败；旧 testid 未改。
- 只读确认：scripted run 的 monitor/accept 证据为 `scripted`/`simulated`，页面无“真实测试通过”的新文案；前端原本已有“预置测试输出（scripted）/模拟执行”标注。
- 边界确认：真实 provider + legacy 的 schedule/任务 retry/accept 均 403 `profile_not_granted_v1`，任务状态与 revision 不变，未生成验收门（集成测试断言）。
- 总闸确认：产品代码无 `execution_safety_ready = True`；仅既有测试夹具内临时置 True（`test_p1_rev01/...` 等）。
- 未启动长期 dev server；e2e 由 Playwright 临时启动 8766/5174 并在结束后关闭。

## 4. 迁移与回滚

- **无新增 Alembic 迁移**；head 仍为 `0012_discussion_messages`。没有新增表，没有第三套权威。
- 数据：未触碰 `Test3/data`；用户既有 `data.bak-*` 与 `data-removed-runs/` 未清理、未提交。
- 回滚（代码）：`git revert 71ccdc8 6fd25f7 a067f73 e0c1f59 9412483 a01775b 5b9b351 a637348 49423f3`（或按卡单独 revert）。无 schema downgrade。
- 迁移/备份路径如有未来表变更，仍按项目既有 SQLite 备份习惯（先备份 `Test3/data` 再升级）。

## 5. 执行授权边界

| 动作 | 规格批准 | PLAN 确认 | 还需要 |
|---|---|---|---|
| `/plan` 生成计划 | 必须 | 否 | session leader 且为项目 Leader；不授权执行 |
| 确认 PLAN 门 | 规格基线有效 | 本动作 | CAS `expected_revision`；不开总闸、不发 grant |
| 注入的无副作用模拟执行器 schedule/执行 | 必须 | 必须（讨论 run） | 仅 e2e/测试显式注入；证据标 simulated；产品默认无此执行器 |
| 真实模型调用 | 视阶段 | 视阶段 | Bot 自身 key；缺失即 `missing_bot_key`，不回退默认钥匙 |
| 真实写仓库/跑命令 | 必须 | 必须 | `granted_v1` + active grant 覆盖 + 基线一致 + `execution_safety_ready==True`（当前仍 False） |
| 复用已有 grant | — | — | 范围覆盖、基线未过期、状态 active |

## 6. 仍未闭环的事实

1. 真实隔离执行与真实仓库写入仍不可用：`execution_safety_ready` 产品路径保持 False，无开闸 UI。
2. 讨论主线仍以整 run `POST /accept` 验收；模块验收/缺陷尚未接到讨论 e2e（P5 差距文档）。
3. 缺陷不会自动生成返工任务；复验历史靠缺陷 payload + 多次验收行，无独立复验轮次表。
4. `needs_reconciliation` 只有只读报告，没有“人工确认恢复”的写接口；这是有意的安全默认。
5. 未新增“模型失败首败次成、副作用只计一次”的端到端计数测试；现有修复/重试单测不覆盖外部副作用计数（见第 7 节）。
6. 真实模式下 Bot 共享工作台凭据的显式授权扩展点未实现（保留为将来加法）。

## 7. 验收矩阵对照

| 验收行 | 覆盖 |
|---|---|
| 完整 scripted 主线 | `discussion-flow.pw.ts`（最终 1 passed）；`test_discussion_to_baseline.py`；`test_discussion_plan_api.py` |
| 未批准规格/未确认 PLAN 全拒绝 | `test_workflow_admission.py`；`test_discussion_plan_api.py`；`test_execution_entrypoint_authorization.py` |
| 过期/不匹配 baseline | `test_workflow_invalidation.py`；既有 `test_resolve_gate_baseline_hashes.py` |
| 跨项目/跨 run/跨 session | `test_workflow_projection.py`；`test_workflow_admission.py` |
| 执行入口一致 | `test_execution_authorization_policy.py`；`test_execution_entrypoint_authorization.py`；schedule/control/accept 集成断言 |
| 并发幂等 | `test_workflow_idempotency.py` |
| 模型失败重试/副作用不重跑 | 部分：既有修复/重试测试；**未新增端到端副作用计数测试**（明确未覆盖） |
| 崩溃不明执行不自动重放 | `test_workflow_recovery.py` |
| 缺陷→修复→复验可追踪 | `test_module_acceptance_and_defects.py::test_reverification_resolves_defect_without_deleting_history`；差距文档 |
| 变更→失效→重新批准 | `test_workflow_invalidation.py` |
| 旧数据兼容/不伪造真实通过 | 无迁移；`test_workflow_evidence.py`；旧 run 投影可推导 |
| Bot 记忆 UI/退役路由/testid/不开闸 Banner | 前端 427 项 Vitest 全通过（含 `GrantStatusBanner.test.tsx`、`deriveStage.test.ts`、`runMonitor.test.ts`） |
| scripted 离线测试与 e2e | 上述命令均离线通过 |
| 缺 Bot Key 失效关闭 | `test_bot_key_fail_closed.py`；`test_bot_api_key.py`；chat/files 测试显式 key |
| 总闸仍关/无开闸 UI | 产品代码检索 + 上述前端测试 |

## 8. 本地 PR 说明草稿

> 统一讨论→规格→计划→PLAN→执行→验收的阶段准入、状态投影、证据标识与执行授权。新增纯查询 workflow 投影与统一授权决策，服务端禁止未确认 PLAN / 未授权真实执行；真实模式缺 Bot key 失效关闭；scripted 模拟保留并诚实标注；补齐 /plan 幂等、重启恢复和基线失效；崩溃后不明任务暂停等待人工和解。未打开执行总闸，未新增迁移，未推送。

## 9. 未提交/工作区状态

- 工作区仅保留用户原有：`M Test3/config/models.yaml`、四个 `data*` 目录、`docs/screenshots/` 未跟踪。
- 本任务提交不包含上述文件。

## 10. 2026-11-24 边界修复后续

本文件中“scripted/replay 模拟例外”“无真实副作用”“重新批准可继续”等表述已由 `workflow-boundary-fixes-delivery-2026-11-24.md` 修正：scripted 模型不授予执行能力，再批准走新 PLAN 门，崩溃未知执行不再自动重放。

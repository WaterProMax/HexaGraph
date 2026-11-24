# 工作流边界修复交付总结（2026-11-24，本地）

## 1. 仓库状态

| 项 | 值 |
|---|---|
| 分支 | `feat/test3-agent-team-v1` |
| 开工 HEAD | `d4618d1`（与审查锚点相同；功能提交止于 `71ccdc8`） |
| 交付 HEAD | 见本文件提交后的 `git log -1`（提交信息含“边界修复交付”） |
| 推送 | 无；仅本地 commit |

未纳入提交（只登记）：`Test3/config/models.yaml`（未读取/未回显）、`Test3/data-removed-runs/`、`Test3/data.bak-20261123-*`、`Test3/docs/screenshots/`。

## 2. 按卡变更

### 卡 1：授权硬边界（模型模式 ≠ 执行器能力）

- 新增 `app/execution/simulation.py`：`ExecutionPolicy(simulated, local_execution_authorized)` 与 `SimulatedExecutor`（无文件、无 git、无子进程、无网络）。策略只能由 `Workbench(..., execution_policy=...)` 或 `create_app(execution_policy=...)` 显式注入；产品默认 `ExecutionPolicy()`，HTTP/env/请求体均不可达。
- `authorization.is_simulated` 改为判断注入的模拟执行器，不再判断 `ScriptedProvider`；scripted/replay 模型输出不再授予 legacy 执行权。
- `_execute_task_locked` 在授权后路由到 `_execute_simulated_task`，证据 `kind=simulated`；不再 init_repo/create_worktree/跑命令/merge。
- `accept` 的验收在模拟执行器下走 `simulated://` 证据，不执行验收命令。
- 讨论 e2e 服务端显式注入 `ExecutionPolicy(simulated=True)`，e2e 任务证据断言由 `merge` 改为 `simulated`（不是产品放行）。
- 测试：`test_execution_capability_gate.py`（scripted 无执行器拒绝、零 worktree/repo/命令调用；注入模拟执行器无副作用）、更新 `test_execution_authorization_policy.py`。

### 卡 2：CR / 重排后的可达再批准

- `_apply_incremental_docs` 与 `_apply_replan` 改写产物后，`decide_cr` / `_apply_replan` 调用 `_open_reapproval_gate`：
  - 生成 `workflow_candidate`（源门 id、revision、SPEC/DESIGN/PLAN 哈希）；
  - 新增 pending `PLAN基线确认` 门（payload `candidate=true`），不改写已裁决门；
  - 加入 `baseline_reapproval_required` 阻塞并暂停（记录 `baseline_pause_owned`，不清除人工暂停）。
- 既有 `POST /api/gates/{gate_id}/resolve` 批准该门时采用当前产物：重记 SPEC/DESIGN/PLAN 哈希、写 approval、清 `baseline_reapproval_required`、旧 grant 仍 stale；候选移入 `workflow_adopted_candidates` 历史。
- 测试：`test_workflow_invalidation.py` 不再手工 append 门或改 `paused`，改为解析自动生成的 pending 门；旧 grant 保持 stale、新 grant 才可调度。

### 卡 3：防崩溃重放与可审计和解

- `execute_task` 在进入执行器前持久化 attempt（intent/started/baseline/repo），结束后写 `done|failed|unknown` 与当前 HEAD commit；模拟执行器同样记录。
- 重启恢复：`_mark_unknown_executions` 不再以“任意 evidence”跳过；running/verifying 恢复后未 done 的任务一律 `needs_reconciliation=True` + `paused=True`，自动循环不派发。已有合并完成（state=done）不标。
- 新增 `POST /api/runs/{run_id}/reconcile/{task_code}`（`X-Bot-Id` + `expected_revision`）：
  - `continue_reconcile`：保持 blocked；
  - `accept_evidence`：要求 attempt `status=done` 且 commit 与 repo HEAD、当前基线一致，才通过状态机事件置 done；
  - `mark_failed_safe_retry`：写理由后置 failed，后续 retry 仍受卡 1 授权。
- 只读 `POST /runs/{id}/reconcile` 仍只读；文档不再称其为“完整恢复”。
- 测试：`test_workflow_reconciliation_api.py`（隔离 tmp `.git`；有 evidence 仍标记；CAS；HTTP 400/409/200）、`test_workflow_recovery.py`。

### 卡 4：验收与证据维度诚实

- `verification_status_for` 不再把 `run.status=done` 当 passed；`pass=false` + 人工批准记为 `overridden`，标签“人工覆盖（原验收未通过）”。
- `execution_mode` 只依据 attempt/命令/合并/模拟证据；skipped/cancelled/blocked 不再算执行。
- `model_mode` 使用 per-run `artifacts.model_calls` + plan 推断，不使用 gateway 全局 calls；两 run 隔离测试。
- 模块验收/缺陷 201 响应改为对象级 `decision`/`evidence_uris`，run 级聚合改名为 `run_evidence`；列表 GET 同样使用 `run_evidence`。
- 测试：`test_workflow_evidence.py`（人工覆盖、全跳过、双 run 隔离、真实执行）、`test_workflow_evidence_api.py`、`test_module_acceptance_and_defects.py`。

### 卡 5：历史基线漂移检测

- 新增 `baseline_provenance`：`approved`（approval 记录 / 已裁决 SPEC|DESIGN|PLAN 门 / 显式标记）、`fixture`（测试 setter）、`unknown`（有哈希无来源）、`none`。
- `baseline_drift` 只在 `approved` 时比较 SPEC/DESIGN/PLAN/DecisionPackage；`fixture` 不驱动漂移；`unknown` 由 `decide_execution` 返回 409 `baseline_unverifiable`，不盲回填 approval。
- `_assert_plan_authority` 保留未动。
- 测试：`test_workflow_invalidation.py` 新增“存量哈希+已裁决门检出漂移”“仅有哈希无来源拒绝”“pending 门不误伤”。

### 卡 6：收口与可观察性

- 投影使用 `_grant_cache` 的 active grant：覆盖任务集时不再显示 `authorization_pending`，仍不参与准入。
- 统一决策：`_require_execution_safety` 在注入模拟执行器时与 `decide_execution` 一致放行；产品真实路径仍总闸拒绝。
- 执行授权按 `discussion_session_id` 服务端回查会话；会话不存在拒绝 `cross_project_mismatch`，不再依赖请求参数。
- 自动循环对 `GrantRejected`/未知异常发出去重 `schedule.rejected` 事件（同一 run 同一 reason 只发一次）。
- `organize_note` 失败记录 `missing_bot_key` 等 category 警告，仍保留原文、不偷默认钥匙。
- 文档：本文件、`docs/API.md`、旧交付文档已更正“scripted/replay 无真实副作用”“再批准靠手工”等表述。

## 3. 测试命令与结果（均为本轮本机实跑）

| 项 | 命令 | 结果 |
|---|---|---|
| 改前基线 | `cd Test3/backend && uv run pytest -m "not live" -o addopts="" -q` | **817 passed, 3 skipped, 2 deselected；退出码 0** |
| 最终后端 | 同上 | **832 passed, 3 skipped, 2 deselected, 2 warnings, 45.08s；退出码 0** |
| 前端单测 | `cd Test3/frontend && npm test` | **51 files / 427 tests passed, 19.33s** |
| 前端构建 | `npm run build` | 成功（2.62s；仅既有 chunk 警告） |
| 讨论 e2e（模拟执行器） | `npx playwright test --config playwright.discussion.config.ts` | **1 passed (6.1s, 总 8.2s)；退出码 0** |
| `pytest -m live` | — | **未跑**：需真实/付费模型，未授权 |
| 真实 sandbox 写入 | — | **未跑**：产品总闸仍 False |

新增/修改测试文件：`test_execution_capability_gate.py`、`test_workflow_reconciliation_api.py`、`test_workflow_observability.py`，以及 evidence/invalidation/policy/entrypoint/acceptance 相关用例更新。

## 4. 前轮验收矩阵对照

| 验收行 | 本轮状态 |
|---|---|
| 完整 scripted 主线 | 通过（e2e 模拟执行器覆盖执行/验收/导出，无 repo/worktree/release code） |
| 未批准规格/PLAN 拒绝 | 通过（既有 + 更新） |
| 过期/不匹配 baseline | 通过（含存量哈希+门证据） |
| 跨项目/跨 run/跨 session | 通过（投影/准入/计划 + 执行回查会话） |
| 入口一致授权 | 通过 |
| 并发 /plan、门、schedule 幂等 | 通过 |
| 模型失败重试/副作用只一次 | **仍未闭环**：无端到端副作用计数测试 |
| 崩溃不明执行不自动重放 | 通过（F1 扫描 attempt 历史，ready+started 也阻断；二次重启仍阻断） |
| 缺陷→修复→复验 | 通过（模块验收层）；讨论主线仍整 run accept |
| 变更→失效→再批准 | 通过（F2 不可变候选 + 门绑定 + CAS 采用；旧门不能采用 live 产物） |
| 旧数据兼容 | 通过（unknown 显式拒绝，不伪造 approval） |
| 记忆 UI/退役路由/testid/Banner | 通过（前端 427） |
| scripted 离线 | 通过 |
| 缺 Bot key 失效关闭 | 通过（既有） |
| 总闸仍关/无开闸 UI | 通过（产品代码无 True 路径） |

## 5. 执行授权边界

- 模型是否 scripted 只决定 `model_mode`，不授予执行能力。
- 纯模拟执行器：`app/execution/simulation.py::SimulatedExecutor`，只由 `Workbench/create_app` 构造参数注入；产品入口不注入，HTTP/env/请求字段不可注入。
- 合法测试夹具：`ExecutionPolicy(local_execution_authorized=True)` 仅由测试 helper/离线 e2e server 注入；产品默认 `ExecutionPolicy()`。
- 真实写仍需 `granted_v1` + active grant + 基线一致 + `execution_safety_ready=True`；产品常量仍 False。

## 6. 再批准生产步骤

1. 已批准 run 的产物被 CR/重排改写 → `workflow_candidate` + pending `PLAN基线确认` 门，run 暂停（`baseline_reapproval_required`）。
2. 人通过 `POST /api/gates/{gate_id}/resolve` 批准该门（无需手工改 paused / append 门）。
3. 服务端记录新 SPEC/DESIGN/PLAN 哈希与 approval（可信 actor 来自门 resolve），旧 approval/invalidation 保留。
4. 旧 grant 全部 stale；执行需新建覆盖新哈希的 grant（`granted_v1` 且总闸开启）。
5. 候选门 resolve 必须带 `expected_revision`；缺字段 400，同一 revision 至多一次成功。

## 7. 恢复与和解

- 终态证据 = F4 `verify_task_completion`：task/run/attempt 身份、基线、repo 身份、write_set 在 commit 树、commit 在目标分支 ancestry、provenance；仅有 `status=done` 或 HEAD==commit 不算。
- 只读 `POST /reconcile` 只报告；受控决议 `POST /reconcile/{task_code}` 才改变任务，且 `accept_evidence` 校验 commit/基线/CAS。
- 证据不足保持 blocked；`mark_failed_safe_retry` 后重试仍受执行授权。

## 8. 迁移与回滚

- 无 Alembic 迁移；head 仍 `0012`；未触碰 `Test3/data`。候选门/决议字段为内存快照加法。
- 回滚须整组：卡 1 能力门 + e2e 注入；卡 2 candidate/门/adopt；卡 3 attempt/恢复标记/决议；卡 4 证据；卡 5 provenance。禁止只回滚门禁留下“scripted 即放行”。

## 9. 仍未闭环（诚实列出）

1. 产品总闸仍关：真实隔离执行/真实仓库写入不可用。
2. P5 讨论主线仍以整 run `accept` 为主；缺陷不自动生成返工任务。
3. 模型失败重试的“副作用只计一次”无端到端计数器测试。
4. CR/重排的完整模型链路（生成改写内容）未单独集成测试；再批准门/adopt 路径已通过 drift 场景与单元覆盖。
5. `accept_evidence` 的 actor 目前只要求 `X-Bot-Id` 并写入审计，未接入更强的用户身份系统。
6. 自动循环事件去重只在进程内；重启后会重新发第一条。

## 10. 2026-11-24 四项边界闭环更正

F1/F2/F3/F4 已由 `four-boundary-fixes-delivery-2026-11-24.md` 实施：恢复扫描 attempt 历史、不可变候选原子采用、模拟覆盖 accept/takeover/submit/release、accept_evidence 任务成果校验。

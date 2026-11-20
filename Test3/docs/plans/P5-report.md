# P5 阶段报告（T01–T05）

本报告覆盖 P5 执行 DAG、连续执行、缺陷回流与模块人验收（T01–T05）。所有测试命令均带 `-o addopts=''`；迁移统一经 `upgrade_database` 执行，不使用 `create_all`；隔离测试使用不可变镜像 Id，未做 `docker tag`、未 pull/build。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | `d2d0425844905280141bde90c37c3292e53c001f` | `feat(test3): P5-T01 schedule decision hash and dag order` |
| T02 | `3db2ebd7961148763710307cc114c11bf66212f3` | `feat(test3): P5-T02 add run write lock and generation guard` |
| T03 | `89ae78804bc5c01aa7b5235383fbb674d67b8e90` | `feat(test3): P5-T03 add module acceptance and defect flow` |
| T04 | `3a6e4eec0927270cadc221965845f006e61b041c` | `test(test3): P5-T04 consume decommission target state` |
| T05 | 本报告所在提交 | `docs(test3): P5-T05 exit report and OpenAPI snapshot` |

T05 的完整 SHA 由本文件内容决定，无法在提交前写入自身；最终 SHA 见交付汇报或 `git log -1 --format=%H`，未使用 amend。

## T01 · 调度消费 Decision+PLAN hash，并遵守 DAG 顺序

- 时间：2026-11-20 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -v tests/unit/test_dag_order.py tests/integration/test_schedule_requires_decision_hash.py tests/integration/test_schedule_grant_http.py`
- 退出码：0
- 计数：20 passed（DAG 单测 8 / 新集成 6 / 既有 grant HTTP 6）
- 实现：`app/execution/dag.py` 提供纯函数 `ready_tasks` / `dag_blocked_tasks` / `edges_from_tasks`；`Workbench.schedule_once` 只在 `granted_v1` 且显式请求 `task_codes` 时检查前置是否成功，未成功返回 `GrantRejected("dag_blocked", 409)`。legacy 分支不变，`task_codes=None` 仍由 `select_tasks` 按依赖挑选。
- hash 校验：复用既有 `grant_stale_reason`，grant 签了哪个 key 就校验哪个。签了 `DecisionPackage` 的 grant 在 run 缺 key 或值变化时返回 `409 baseline_stale`；只签 `PLAN` 的 P1 夹具不被追加新条件。
- 状态映射：`done` 视为成功，`succeeded` 作为契约别名同样视为成功；`failed` / `running` / `pending` 均视为前置未成功。

## T02 · 授权范围内连续执行与 per-run 写锁

- 时间：2026-11-20 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -v tests/unit/test_run_lock_and_late_reply.py tests/unit/test_dag_order.py`
- 退出码：0
- 计数：15 passed（锁/生成 7 / DAG 8）
- 回归：`TEST3_ISOLATION_IMAGE=sha256:af6493938f5d... .venv/bin/python -m pytest -o addopts='' -q tests/unit/test_isolated_execute_task.py tests/e2e/test_granted_v1_sandbox_write.py tests/unit/test_p1_rev01_execution_boundary.py tests/integration/test_schedule_grant_http.py tests/unit/test_schedule_grant_guard.py` → 40 passed，退出码 0
- 写锁：`app/execution/run_lock.py` 的 `RunLockRegistry` 每 run 一把 `asyncio.Lock`；`schedule_once` 与 `execute_task` 都走同一个 `write_scope`。`write_scope` 用 ContextVar 标记已持有者，`asyncio.gather` 派生的子任务可重入而不死锁；外部写入者仍互斥。`_schedule_lock_for` 保留为同一把锁的薄封装。
- 连续执行：`schedule_once` 原本就在同一把锁的 `while` 循环里按 `grant.task_codes` 连续 `execute_task`；本卡只把锁统一，未新增逐任务审批门，未对每个 task 重新 POST `/execution-grants`。
- 生成守卫：`app/execution/generation.py` 的 `GenerationGuard`；`pause` / `terminate` 时 `bump`，`_execute_granted_task` 在隔离执行返回后、写证据与状态前检查 `is_current`，过时回包只发 `task.late_result_ignored` 事件并原样返回，不改状态、不写证据。
- 范围：范围外 `T-99` 仍 `409 scope_mismatch`，无 grant 仍 `403 grant_required`（单测已断言）。

## T03 · 测试证据、缺陷回流、模块人验收

- 时间：2026-11-20 CST
- 命令：`cd Test3/backend && TEST3_ISOLATION_IMAGE=sha256:af6493938f5d... .venv/bin/python -m pytest -o addopts='' -v tests/integration/test_module_acceptance_and_defects.py tests/unit/test_isolated_execute_task.py`
- 退出码：0
- 计数：20 passed（验收/缺陷 11 / 隔离执行 9）
- 迁移：`alembic/versions/0010_acceptances_defects.py`，`revision="0010"`，`down_revision="0009"`，只建 `module_acceptances` 与 `defects`；`tests/integration/test_alembic.py`、`test_p1_rev05_alembic_handoff.py`、`test_events_and_db.py`、`tests/unit/test_core_tables.py`、`test_p1_rev01_execution_boundary.py`、`test_p1_rev08_production_enable_path.py` 合计 44 passed，退出码 0。
- 服务：`app/execution/acceptance.py`。`accepted` / `rejected` 必须有非空 `evidence_uris` 且 URI 必须已存在于对应任务的证据；`accepted` 还要求任务处于成功状态。`rejected` 为每个 task_code 建一条 open 缺陷，并把任务经 `defect_found` 转到 `failed`（既有 `failed + retry` 可修复）。
- 路由：`app/api/routes_acceptance.py`，`create_app()` 以 `prefix="/api"` 挂载；`POST /runs/{run_id}/module-acceptances` 与 `POST /runs/{run_id}/defects`。`X-Bot-Id` 必填；`reviewer` 与 actor 不一致返回 403 forbidden；`model_self_review=true` 一律 400。
- 状态机：新增 `("done","defect_found")->"failed"`、`("verifying","defect_found")->"failed"`、`("failed","defect_found")->"failed"`；不新增 force-pass 边。任务状态映射沿用契约：`done` 即成功，缺陷回流用 `failed`。
- 并发：同一 task 两个缺陷同时写入，两行都在，详情不丢失。
- 既有权衡：未复用、未放宽 `Workbench.accept()`；granted_v1 的 `granted_acceptance_disabled` / `granted_force_pass_disabled` 仍由 `test_p1_rev01_execution_boundary.py` 与 `test_p1_rev08_production_enable_path.py` 覆盖。
- OpenAPI：`UPDATE_OPENAPI_SNAPSHOT=1 ... tests/integration/test_api_contract.py` → 28 passed；快照 20 insertions / 0 deletions（仅新增 P5 两条路由）。`Test3/docs/API.md` 已补 P5 章节。

## T04 · 只消费下线目标态的契约测试

- 时间：2026-11-20 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -v tests/contract/test_decommission_consumption.py`
- 退出码：0
- 计数：5 passed
- 数据源：只读 `Test3/docs/plans/decommission-target-state.json`（原有未跟踪文件，本卡未 `git add`）。当前 `source=p0_index_not_implemented`，测试断言该字面值，不预言路由消失、不要求本阶段补守卫。文件缺失时使用测试内最小夹具（同样 `source=p0_index_not_implemented`）。
- 对照表：

| 断言 | P0 目标态字段 | 当前结果 |
|---|---|---|
| 索引仍是草稿 | `source=p0_index_not_implemented` | PASSED |
| 无专用外呼存活 | `decommission_index[].outbound_active=false` | PASSED |
| 不阻塞 P1/P5 | `blocks_all_p1=false`、`target_acceptance_for_other_task` 非空 | PASSED |
| 保留能力含“禁止品牌黑名单” | `retained_capabilities` | PASSED |
| 通用 provider 不被品牌拒绝 | `app/llm/gateway.py` / `app/execution/tool_policy.py` | PASSED（无 `model_forbidden`；`deepseek.*(forbid/reject/block)` 不匹配） |

- 本卡提交文件：`tests/contract/__init__.py`、`tests/contract/test_decommission_consumption.py`、本报告。不含 `frontend/src/App.tsx`，不含 runtime 下线守卫生产 diff。
- `git diff --name-only`（本卡提交前）：仅上述测试与报告；原有 5 个未跟踪文件未纳入。

## 新增与修改文件总表

新增：

- `app/execution/dag.py`
- `app/execution/run_lock.py`
- `app/execution/generation.py`
- `app/execution/acceptance.py`
- `app/api/routes_acceptance.py`
- `alembic/versions/0010_acceptances_defects.py`
- `tests/unit/test_dag_order.py`
- `tests/integration/test_schedule_requires_decision_hash.py`
- `tests/unit/test_run_lock_and_late_reply.py`
- `tests/integration/test_module_acceptance_and_defects.py`
- `tests/contract/__init__.py`
- `tests/contract/test_decommission_consumption.py`

修改：

- `app/services/runtime.py`（DAG 检查、per-run 锁接入、generation 守卫、验收/缺陷写入口）
- `app/storage/models.py`（`module_acceptances` / `defects` ORM）
- `app/orchestrator/states.py`（`defect_found` → `failed` 边，未新增 force-pass）
- `app/main.py`（挂载 acceptance router，`prefix="/api"`）
- `tests/integration/snapshots/openapi_structure.json`（仅新增 2 条 P5 路由）
- `Test3/docs/API.md`（P5 章节）
- `Test3/docs/plans/P5-report.md`

## 与既有能力的衔接

- `schedule_once` / `_schedule_once_locked`：保留原 while 循环与 `select_tasks`；仅追加 granted_v1 + 显式请求时的 DAG 检查，并把 `_schedule_lock_for` 指向同一把 `RunLockRegistry` 锁。
- `grant_stale_reason`：未改动。它对 grant 里每个已签 key 逐一比较，因此签了 `DecisionPackage` 的 grant 已自动获得 stale 校验。
- `select_tasks`：未改动；依赖挑选继续由它负责，DAG 检查只处理“显式请求被挡住的后继”。
- F-05 拒绝路径：`_require_execution_safety`、`accept()` 的 `granted_acceptance_disabled`、force-pass / `_run_regression` / takeover 的 `granted_force_pass_disabled` 全部零改动。
- P4 `DecisionPackage`：P5 只读取 `approved_baseline_hashes["DecisionPackage"]`，不重算、不改会话状态机。
- 任务状态映射：契约的 `succeeded` 在真实枚举里是 `done`；`SUCCESS_STATES={done, succeeded}`。缺陷回流统一用 `failed`，经既有 `("failed","retry")->"running"` 修复；新增边仅 `done/verifying/failed + defect_found -> failed`。
- `dag_blocked`：登记为 C.12 补丁错误类别（409），只在 granted_v1 + 显式请求的后继上产生。

## 出口 A · 全部 P5 测试

- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -v tests/unit/test_dag_order.py tests/integration/test_schedule_requires_decision_hash.py tests/unit/test_run_lock_and_late_reply.py tests/integration/test_module_acceptance_and_defects.py tests/contract/test_decommission_consumption.py tests/integration/test_schedule_grant_http.py`
- 退出码：0
- 计数：43 passed（DAG 8 / 新调度集成 6 / 锁与生成 7 / 验收缺陷 11 / 下线契约 5 / 既有 grant HTTP 6）
- 四条关键断言仍绿：签了 `DecisionPackage` 的 grant 在缺 key/值变时 409 baseline_stale；同一 grant 前置成功后连续执行不再申请新 grant；`test_decommission_consumption.py` 5 passed；本出口无新增 `App.tsx` 生产 diff。

## 出口 B · P4 / P3 / P2 / P1 / OpenAPI / 全量非 live

隔离镜像：`TEST3_ISOLATION_IMAGE=sha256:af6493938f5df1f06ca97f63bac9e0eebd9119185183dbc25cc4cc7143ef72cd`（不可变 Id，未 `docker tag`，未 pull/build）。

| 组 | 命令摘要 | 退出码 | 计数 |
|---|---|---|---|
| P4 七文件 | `test_discussion_steward … test_discussion_to_baseline` | 0 | 60 passed |
| P3 六文件 | `test_memory_store … test_memory_api` | 0 | 42 passed |
| P2 七文件 | `test_skill_registry … test_bot_pin_snapshot` | 0 | 50 passed |
| P1 八文件 | `-m 'not live'` 隔离/证据/F-08/边界/e2e | 0 | 70 passed, 1 skipped |
| OpenAPI | `-v tests/integration/test_api_contract.py` | 0 | 28 passed |
| 全量非 live | `-m 'not live'` | 0 | 605 passed, 1 skipped, 2 deselected, 0 failed |

- 全量 skip 仍是 `test_worker_fails_closed_without_backend`（有后端时按设计跳过）；2 deselected 为 `live` 标记。
- 既有 `tests/unit/test_discussion_rules.py` 含在全量里，通过。
- 警告为既有 `0005` 表达式索引 SAWarning 与 aiosqlite 线程告警，均非失败。

## 出口 C · 默认镜像仍 fail-closed

- 命令：`cd Test3/backend && env -u TEST3_ISOLATION_IMAGE .venv/bin/python -m pytest -o addopts='' -m 'not live' -rs tests/unit/test_p1_rev03_isolation_preflight.py`
- 退出码：0
- 计数：8 passed, 1 skipped
- skip 原因：`isolation image is not present locally: python:3.11-slim (no pull attempted)`
- 跑后 `docker image inspect python:3.11-slim` 仍返回非 0（未拉取、未创建）。

## 契约核对

- DecisionPackage + PLAN hash：grant 签了哪个 key 就校验哪个；缺失或值变 → 409 baseline_stale；未签 DecisionPackage 的旧 P1 grant 不被追加新条件。
- DAG：前置未成功（非 done）时显式请求后继 → 409 dag_blocked，零执行；legacy 与 `task_codes` 省略路径不变。
- 连续执行：同一 grant 内前置成功后继续后继，`execution_grants` 仍只有一条 active；超范围 409 scope_mismatch、无 grant 403 grant_required 未变。
- 写锁与迟到回包：同一 run 写路径共用一把锁（峰值 holders=1）；pause/terminate bump generation，过时回包不改状态、不写证据。
- 缺陷回流：必须带已存在的证据；`rejected` 自动建 open 缺陷并把任务置 `failed`；`model_self_review=true` 一律 400；缺陷不自动 resolved。
- 未开闸：`execution_safety_ready` 在 `app/` 中仍只有一处赋值 `False`（`app/services/runtime.py`，P5 后行号 230；因新增 import 自 218 下移 12 行，语义未变）。
- F-05 旧入口仍拒绝：`test_p1_rev01_execution_boundary.py` 与 `test_p1_rev08_production_enable_path.py` 通过；`accept()` / force-pass / takeover 零改动。
- T04 无 `App.tsx` 生产 diff：`git diff --name-only 7c8e6be...HEAD -- Test3/frontend` 为空。
- OpenAPI：路径 63 → 65，新增 `POST /api/runs/{run_id}/module-acceptances`、`POST /api/runs/{run_id}/defects`，删除 0；`GET /api/runs/{run_id}/discussion` 与全部讨论/记忆/Bot/成员路径保留。
- 零真实付费 API：P5 测试全部 scripted / 本地夹具 / 打桩；未启用 `model_live`。
- 原 5 个未跟踪文件未纳入：`P1-review.md`、`Test3/docs/plans/P0-report.md`、`baseline-lock.json`、`decommission-target-state.json`、`p0-t01-cmd.log` 仍为 `??`。

## 声明

- 未进入 P6 / P7；未改前端、未做讨论/Grant UI、未做真实 PR 闭环。
- `execution_safety_ready` 仍只在 `app/services/runtime.py` 赋 `False`，生产路径未开闸。
- `Test3/docs/plans/p1-pr-record.json` 无 diff，仍 `status=BLOCKED`、`github_pr_url=null`。
- 未 `git push`、未创建远程分支、未开 PR。
- 未安装/启动 Docker、未 `docker pull`、未 `docker build`、未 `docker tag`；隔离测试使用不可变镜像 Id。
- 恰好 5 个普通本地 commit，parent 链从 `7c8e6be02cc9ab51275e93e35745edd0f00b0f51` 起连续；无 amend/reset/force。
- 人工验收提醒：P5 只新增验收/缺陷路由，未改动 `POST /api/runs/{run_id}/accept`；如需复核，可在验收环境点一次目标路由与 `GET /api/runs/{run_id}/execution-profile`（`execution_safety_ready` 应为 `false`）。

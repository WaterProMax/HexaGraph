# P5 阶段报告（T01–T05）

本报告覆盖 P5 执行 DAG、连续执行、缺陷回流与模块人验收（T01–T05）。所有测试命令均带 `-o addopts=''`；迁移统一经 `upgrade_database` 执行，不使用 `create_all`；隔离测试使用不可变镜像 Id，未做 `docker tag`、未 pull/build。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | 待 T05 汇总 | `feat(test3): P5-T01 schedule decision hash and dag order` |
| T02 | 待 T05 汇总 | `feat(test3): P5-T02 add run write lock and generation guard` |
| T03 | 待 T05 汇总 | `feat(test3): P5-T03 add module acceptance and defect flow` |
| T04 | 待 T05 汇总 | `test(test3): P5-T04 consume decommission target state` |
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

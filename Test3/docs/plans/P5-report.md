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

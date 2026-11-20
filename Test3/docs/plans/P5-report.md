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
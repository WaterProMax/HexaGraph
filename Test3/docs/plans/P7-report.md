# P7 阶段报告（T01–T03，持久化对账、Alembic 副本演练与全书关闭准备）

本报告覆盖 P7 三张卡。结论先行：**关闭失败**。真实 `p1-pr-record.json` 仍是 `status=BLOCKED`、`github_pr_url=null`，本轮没有 C.7 `github_write` 授权，也没有 push / `gh pr create` / merge / deploy。关闭校验按设计对真实记录失败，等待整期独立验收通过且用户授权后由父代理执行真实推送与开 PR。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | `935b9a08aab1afb32fff986334001a724286757b` | `feat(test3): P7-T01 persistence ADR, reconcile, restart grant cache` |
| T02 | `372baf7a6581cf2977c86ae2468210e4ab52f520` | `test(test3): P7-T02 alembic copy upgrade/downgrade and SSE dedup` |
| T03 | 本报告所在提交 | `docs(test3): P7-T03 close-out report, PR draft, pr-record assertions` |

T03 的完整 SHA 由本文件内容决定，无法在提交前写入自身；最终 SHA 见 `git log -1 --format=%H`，未使用 amend。基线 `0252dbcbdb55b4e5651399dafacb3bf4b4fdacb7`，父链连续。

## P7-T01 · 持久化边界 ADR、JSONL 不动、杀进程对账

- ADR：`Test3/docs/adr/0001-persistence-boundary.md`（写权威、legacy 例外、禁止双写、重启恢复步骤）。
- 对账：`app/ops/reconcile.py`，`ReconcileReport(grants_active, memory_orphans_fixed, notes)` 与 `async def reconcile(db_session, *, run_id=None)`。只统计 active grant、只把 `memory_records.status` 索引列与 payload 的 status 对齐；不改 payload/body、不删行、不把 `published` 降级。
- 修复的真实缺口：`_grant_cache` 杀进程后为空。
  - `app/execution/grant_repo.py` 新增 `read_grants_for_run(db_path, run_id)`，只读 sqlite3 连接，供 `restore_runs()` 在 async 引擎建立前回填缓存。
  - `Workbench._ensure_db()` 在引擎就绪后按 SQLite 再整体回填一次。
  - `_refresh_grant_statuses()` 刷新状态后重新从库载入缓存，缓存与库不再分叉。
  - 重启后 `_attach_granted_specs()` 重绑的 `grant_id` / `tool_refs` / `feature_branch` 与库中 grant 一致；不产生重复 grant、重复 pin 快照。
- 测试：`tests/integration/test_reconcile.py`（4 passed）
  - 重启后 Bot、成员、pin 快照、记忆（published）、讨论 session、缺陷仍在；active grant 可解析；重绑 spec 的 `grant_id` 与库一致且只有一份。
  - 未提交的 grant 在新实例不可见；`reconcile` 成功；数据库可继续提交新 grant。
  - `published` 记忆在 reconcile 后仍为 published、version 行数不变；列漂移修复计 1，第二次 reconcile 计 0。
  - 两个 reconcile 并发：合计只修 1 次，行数不变，再跑为 0。
- 测试：`tests/unit/test_no_new_domain_jsonl_write.py`（2 passed）
  - 创建 Bot / Skill / 成员 / Grant / 记忆 / 讨论后，隔离目录全部 JSONL 行数不变，且任何行不含 bot_id / `bot.created`。
  - 对 legacy run 追加一条 `task.note` 事件后，该 run 的 `events.jsonl` 行数 +1。
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -v tests/integration/test_reconcile.py tests/unit/test_no_new_domain_jsonl_write.py` → 退出码 0，6 passed。
- ruff：`app/ops`、`app/execution/grant_repo.py`、`app/services/runtime.py`、两个测试文件 → 全过。
- 边界：所有测试库在 pytest `tmp_path`；未读取或清空 `Test3/data/runs/`。

## P7-T02 · Alembic 副本升级/降级与 SSE 去重

- 迁移链（当前唯一 head `0010`）：

```text
0001 → 0002_execution_grants → 0003_run_execution_state → 0004_skill_definitions
     → 0005_bots_and_pins → 0006_project_memberships → 0007_run_bot_pin_snapshots
     → 0008_memory_records → 0009_discussion → 0010_acceptances_defects
```

- 测试：`tests/integration/test_alembic_upgrade_downgrade_copy.py`（1 passed）
  - 先建一个只到 P0 head `0001` 的库，再 `shutil.copy2` 到 `tmp_path/tmp-copy-under-test.db`；断言副本路径在 `tmp_path` 下且不等于 `get_settings().data_dir()/test3.db`。
  - 副本 upgrade 到 head：`alembic_version == "0010"`；断言 `bots`、`skill_definitions`、`project_memberships`、`execution_grants`、`memory_records`、`discussion_sessions` 及 `bot_pin_revisions`、`run_bot_pin_snapshots`、`discussion_proposals`、`discussion_reviews`、`module_acceptances`、`defects`、`run_execution_state` 均存在；抽查 memory/grants/discussion 列。
  - 副本 downgrade 回 `0001`：版本回到 `0001`，上述 C.6 表全部消失。
  - 副本再 upgrade 到 head：再次 `0010`，表齐全，`alembic_version` 未损坏。
  - 全程只操作副本；未对用户 `Test3/data/test3.db` 做任何 upgrade/downgrade。
- SSE：复用既有覆盖 `tests/integration/test_api_contract.py::test_sse_last_event_id_resume_no_duplicates_in_order`（重放同一游标后不重复、保序），并连带跑同文件的丢失窗口、心跳、断连用例。命令：`.venv/bin/python -m pytest -o addopts='' -v tests/integration/test_api_contract.py -k sse` → 5 passed / 23 deselected，退出码 0。未写 `sse=not_applicable`，未新增与 seq / Last-Event-ID 冲突的协议。
- 命令：`.venv/bin/python -m pytest -o addopts='' -v tests/integration/test_alembic_upgrade_downgrade_copy.py` → 1 passed，退出码 0；ruff 通过。

## P7-T03 · 全书关闭准备

- 关闭校验：`tests/unit/test_pr_record_not_blocked_as_done.py` 的 `assert_pr_record_complete(record|path)`。
  - 夹具失败形状：`status=BLOCKED` → 断言错误含 `BLOCKED`；`status=BLOCKED` 且 `accepted=true` → 同样失败。
  - 夹具失败形状：`status=PR_OPEN` 且 `url=""` → 断言错误含 `github_pr_url`。
  - 夹具成功形状：合法 `https://` URL、`merged=false`、`deployed=false` → 通过。
  - 真实记录门槛：`test_real_p1_pr_record_is_complete`，标记 `@pytest.mark.closeout`（`pyproject.toml` 已登记），对真实 `Test3/docs/plans/p1-pr-record.json` 运行。
- 命令与退出码（如实）：

| 命令 | 退出码 | 计数 |
|---|---|---|
| `.venv/bin/python -m pytest -o addopts='' tests/unit/test_pr_record_not_blocked_as_done.py -k "not real" -v` | 0 | 4 passed, 1 deselected |
| `.venv/bin/python -m pytest -o addopts='' tests/unit/test_pr_record_not_blocked_as_done.py tests/unit/test_live_git_idempotent.py -v` | **1** | 13 passed, **1 failed**（真实关闭门槛，预期） |

- 失败原因（预期）：`AssertionError: p1 PR record is BLOCKED: no C.7 github_write authorization, no real PR`。未用 skip / xfail 伪装，未改真实记录冒充完成。
- `test_live_git_idempotent.py` 复跑通过：关闭流程 / `live_git` 模块仍不存在 merge/deploy 命令。
- `p1-pr-record.json` 仅补充核验字段：`feature_branch=feat/test3-agent-team-v1`、`base_branch=teamwork-001`、`merged=false`、`deployed=false`、`closeout_checked_at`、`closeout_detail`；`status` 仍 `BLOCKED`、`github_pr_url` 仍 `null`、无 `accepted`。
- `Test3/docs/Acceptance.md` 仅新增第 9 节「首版关闭条件（P7）」短指针，未改历史验收主体。

## P1–P6 出口矩阵

| 阶段 | 报告 | 结论 |
|---|---|---|
| P1 | `docs/plans/P1-report.md` | 本地可执行部分完成；真实 GitHub 写操作标记 BLOCKED（本报告 P7 关闭节延续该状态） |
| P2 | `docs/plans/P2-report.md` | 通过（Skills/Bots/成员与 pin 冻结） |
| P3 | `docs/plans/P3-report.md` | 通过（记忆与注入、撤成员隔离） |
| P4 | `docs/plans/P4-report.md` | 通过；报告如实记录 Docker Desktop 陈旧标签导致的一次本地 `docker tag` 重挂（同一镜像 ID，未 pull/build），本报告不改写为无条件通过 |
| P5 | `docs/plans/P5-report.md` | 通过（DAG、连续执行、验收/缺陷） |
| P6 | `docs/plans/P6-report.md` | 通过（前端工作台、UI-A1 八步、截图索引） |

## 出口命令汇总

| 命令 | 退出码 | 计数 |
|---|---|---|
| `git rev-parse HEAD` / `git branch --show-current` / `git status --porcelain` | 0 | 分支 `feat/test3-agent-team-v1`；仅 5 个既有未跟踪文件 |
| `.venv/bin/alembic heads` | 0 | `0010 (head)` |
| P7 卡片测试（reconcile/jsonl/alembic/SSE 选择器） | 0 | 12 passed, 23 deselected |
| `ruff check`（P7 新增/修改 Python） | 0 | All checks passed |
| `TEST3_ISOLATION_IMAGE=sha256:af6493938f5d… .venv/bin/python -m pytest -o addopts='' -q -m 'not live and not closeout'` | 0 | **620 passed, 1 skipped, 3 deselected, 0 failed** |
| `env -u TEST3_ISOLATION_IMAGE … tests/unit/test_p1_rev03_isolation_preflight.py -q` | 0 | 8 passed, 1 skipped（skip 含 `python:3.11-slim` 本地不存在且 no pull attempted；跑后镜像仍不存在） |
| `tests/integration/test_api_contract.py` | 0 | 28 passed（OpenAPI 70 条路径，未删减） |
| `cd Test3/frontend && npx tsc --noEmit` | 0 | 通过 |
| `cd Test3/frontend && npm test` | 0 | 27 files / 209 passed |
| `cd Test3/frontend && npm run build` | 0 | 构建成功（既有 chunk 体积告警） |

## 关闭节：诚实失败

**关闭失败。** 原因：缺少 C.7 `github_write`；没有真实、可打开的 PR。

- 真实 `Test3/docs/plans/p1-pr-record.json`：`status=BLOCKED`、`github_pr_url=null`、`authorization_present=false`。
- 本轮未 push、未创建远程分支、未 `gh pr create`、未 merge、未 deploy；未写任何伪造 URL。
- `MV-04` 仍为 `not_completed`；`BLOCKED` 不算首版完成。
- 关闭门槛命令按设计非零（见上表）。
- 后续（父代理，需用户明确授权）：在 `feat/test3-agent-team-v1` 上幂等 push（禁止 push `teamwork-001`），幂等 `gh pr create`（base=`teamwork-001`），把真实 `https://github.com/<owner>/<repo>/pull/<n>` 写入记录并置 `status=PR_OPEN`、`merged=false`、`deployed=false`，再重跑 `tests/unit/test_pr_record_not_blocked_as_done.py` 直到绿。禁止 merge / deploy。

## PR 正文草案（不执行）

**标题**：Test3 多体工作流工作台：从设计规格到授权执行的离线首版

**base**：`teamwork-001`　**feature**：`feat/test3-agent-team-v1`

**范围摘要**

- P1：执行授权、F-05/F-06/F-08 边界、隔离执行与证据安全；真实 PR 写操作未执行（缺 github_write）。
- P2：Skill 版本注册、Bot 与 pin 冻结、项目成员与唯一 leader。
- P3：记忆版本追加、可见性隔离、人工晋升与注入槽。
- P4：讨论会话状态机、盲首轮、禁止自评、硬门槛收敛、DecisionPackage 与人工规格门。
- P5：DAG 调度、per-run 写锁与 generation 守卫、模块验收与缺陷回流。
- P6：前端工作台（AppShell、Bot、项目工作台、Grant/互评/缺陷）、UI-A1 八步走查与截图。
- P7：持久化边界 ADR、reconcile、Alembic 副本升级/降级、关闭门槛与本文档。

**测试与隔离**

- 后端全量非 live：620 passed / 1 skipped / 3 deselected（隔离测试使用不可变镜像 ID `sha256:af6493938f5d…`，未 pull/build/tag）。
- 前端：`tsc --noEmit`、27 files / 209 tests、`npm run build` 全绿。
- 零真实付费模型调用（scripted / replay / 本地夹具）；未启用 `model_live`。

**安全与总闸**

- `execution_safety_ready` 仍为 `False`，唯一赋值点 `Test3/backend/app/services/runtime.py:230`；无开闸 API/UI。
- OpenAPI 70 条路径，未删除既有路径；无新增写接口。

**已知限制**

- 关闭门槛尚未满足：无真实 PR，`p1-pr-record.json` 仍 `BLOCKED`。
- 真实模型能力与真实 GitHub 写闭环未在本轮验收。

## 声明

- 未进入下一阶段；未 push、未 `gh pr create`、未 merge、未 deploy、未向 `teamwork-001` 推送。
- `execution_safety_ready` 仍只在 `Test3/backend/app/services/runtime.py:230` 赋 `False`。
- 未调用真实付费模型 API；无 `model_live` 授权。
- 未安装/启动 Docker、未 pull/build/tag；隔离测试使用不可变镜像 ID。
- 未读取或修改 `.env`、密钥、`Test3/data`；未删除 `Test3/data/runs/`。
- 恰好 3 个普通本地 commit，父链从 `0252dbc` 起连续；无 amend/reset/force。
- 原 5 个未跟踪文件未纳入任何提交。
- 本报告不是关闭完成声明；MV-04 未完成。
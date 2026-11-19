# P1 审查修复 · F-01 逐项验证记录

- 日期：2026-11-19（Asia/Singapore）
- 工作区：`/Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1`
- `git rev-parse HEAD`：`520b15c102ee3f4674f61977cd766c14b84f6fd3`（与审查 HEAD 一致）
- 分支：`feat/test3-agent-team-v1`
- 验证开始时 dirty（只读记录）：`P1-review.md`、`Test3/docs/plans/P0-report.md`、`baseline-lock.json`、`decommission-target-state.json`、`p0-t01-cmd.log` 均为未跟踪文件；无已跟踪文件改动。
- 本任务未修改生产代码，未 push，未创建 PR，未调用真实模型或真实网络，未写入 `Test3/data/`。所有复现均使用 `tmp_path`、scripted provider、sentinel 或假 runner。

## 1. 结论

在审查 HEAD 上逐项复现 P1-REV-01…09。除明确标注的对照用例外，新增断言在修复前失败：

```text
18 failed, 7 passed
```

通过项是设计上的对照/已确认有效路径：既有 Grant 纯策略子集用例（`test_grant_policy.py` 10 passed）、
legacy 恢复不动 JSONL、PR “远端已创建但响应丢失”场景、空/缺字段授权拒绝、普通 run 不产生
`granted_execution`。P1-REV-01/02/03/04/05/06/07/08/09 均有修复前失败断言。

## 2. 逐项记录

### P1-REV-01 · Grant 未位于真实执行边界

- 测试：`tests/unit/test_p1_rev01_execution_boundary.py`
- 用例 A：`granted_v1`、无 Grant、无 `granted_execution`，sentinel 替换 `app.services.runtime.run_tool_agent`，调用生产 `execute_task()`。
- 用例 B：Grant 仅 `T-01`，`T-02` 置 `failed`，调用生产 `control_task(..., "T-02", "retry", ...)`。
- 结果：两条均 `Failed: DID NOT RAISE GrantRejected`；sentinel 被到达。与报告案例 A/B 一致。
- 判定：**已复现**。

### P1-REV-02 · push main / 无授权 commit

- 测试：`tests/unit/test_p1_rev02_live_git_binding.py`
- 用例：`feature_branch="main"`、`base_branch="teamwork-001"` 调生产 `push_once()`；以及无授权调生产 `commit_all()`。
- 结果：`push_once` 未拒绝并记录 `git push origin HEAD:refs/heads/main`；`commit_all` 未拒绝且先执行 `git add -A`。与报告 `push_main_accepted=True` 一致。
- 判定：**已复现**。

### P1-REV-03 · 白名单测试进程 / evidence 符号链接逃逸

- 测试：`tests/unit/test_p1_rev03_isolation_escape.py`
- 用例 1：预置 `wt-evidence -> 外部临时目录`，调生产 `execute_task_granted()`；外部目录出现 `.log`/`.json`。
- 用例 2：白名单内 `python -m pytest tests/test_escape.py` 用绝对路径写外部临时文件；命令成功且外部文件存在。
- 结果：两条均在修复前失败（外部文件存在）。与报告 `outside_files`、`command_whitelisted=True, result_ok=True, outside_file_exists=True` 一致。
- 判定：**已复现**。
- 说明：直接 `WriteSpec` 的绝对路径、`../`、既有符号链接拒绝仍由既有 `test_tools_llm_agents.py::test_path_safety` 覆盖，本任务未改该实现。

### P1-REV-04 · 重启 / 损坏 snapshot 降为 legacy

- 测试：`tests/unit/test_p1_rev04_profile_recovery.py`
- 用例：设置 `granted_v1` + hashes + Grant 后重建 `Workbench`；先生成正确 granted snapshot 再写坏 JSON 走 events-only；缺 profile 的 run。
- 结果：正常重启恢复为 `legacy`（期望 `granted_v1`）；损坏 snapshot 恢复为 `legacy`；缺 profile 仍被解释为 `legacy`（期望 `unspecified`）。与报告 `valid_restart_profile: legacy` / `corrupt_snapshot_recovery_profile: legacy` 一致。
- 对照：既有 legacy run 恢复后仍为 `legacy`，`events.jsonl` 字节未变。
- 判定：**已复现**。

### P1-REV-05 · Workbench `create_all()` 与 Alembic 双建表

- 测试：`tests/integration/test_p1_rev05_alembic_handoff.py`（临时文件 DB）
- 路径 A：`alembic upgrade 0001` → 旧 Workbench `create_all()` 写入 Grant → `upgrade head`。
  结果：`(sqlite3.OperationalError) table execution_grants already exists`。
- 路径 B：修复前运行时 `_ensure_db()` 先 `create_all()` → 首次 `alembic upgrade head`。
  结果：`(sqlite3.OperationalError) table project already exists`。
- 判定：**已复现**，未触碰用户主库，未执行 `alembic stamp`。

### P1-REV-06 · PR list 未知仍 create

- 测试：`tests/unit/test_p1_rev06_pr_list_unknown.py`
- 用例：`gh pr list` 返回非零 / 坏 JSON；调生产 `create_pr_idempotent()`。
- 结果：未拒绝，`create_calls=1`；与报告 `create_attempted_after_unknown_list=True` 一致。
- 对照：第一次 create 远端成功但响应失败，第二次 list 找回同一 URL，`create_calls=1`，修复前即通过，保留为回归。
- 判定：**已复现**（未知 list 分支）。

### P1-REV-07 · 否定语义授权被接受

- 测试：`tests/unit/test_p1_rev07_github_auth_negation.py`
- 用例：报告原文 `do not authorize github_write owner=expected repo=repo ...`。
- 结果：parser 返回完整 `GitHubWriteAuth`（`negated_authorization_accepted=True` 等价）。另断言结构化 JSON 记录当前不能按精确字段解析（修复前失败），作为 F-09 的正向目标。
- 判定：**已复现**。

### P1-REV-08 · granted 无生产启用/物化来源

- 测试：`tests/integration/test_p1_rev08_production_enable_path.py`
- 用例：只走生产创建/启用/物化服务与 HTTP；不使用 internal setter，不手工注入 `granted_execution`。
- 结果：`POST /api/runs/{run_id}/execution-profile` 为 404；无生产启用路径。物化任务没有 `granted_execution`。
- 对照：普通 `create_run()` 物化不带假 granted spec；legacy run POST Grant 仍 403；客户端降级 body 在修复前因路由不存在也是 4xx，但“路由存在且明确拒绝 legacy”留待 F-04 断言。
- 判定：**已复现**。

### P1-REV-09 · revision 恒真断言

- 测试：`tests/unit/test_p1_rev09_revision_assertion.py`
- 用例：扫描 `test_grant_policy.py`、`test_grant_refresh.py`，禁止 `run_revision = 5` / `assert run_revision ==` 恒真模式。
- 结果：两文件仍含该模式，测试失败。
- 判定：**已复现**（测试质量问题，非生产代码回归）。

## 3. 命令与结果

```text
cd Test3/backend && .venv/bin/python -m pytest \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/unit/test_p1_rev02_live_git_binding.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_p1_rev04_profile_recovery.py \
  tests/integration/test_p1_rev05_alembic_handoff.py \
  tests/unit/test_p1_rev06_pr_list_unknown.py \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  tests/integration/test_p1_rev08_production_enable_path.py \
  tests/unit/test_p1_rev09_revision_assertion.py \
  -v
# exit 1：18 failed, 7 passed
```

对照：

```text
cd Test3/backend && .venv/bin/python -m pytest tests/unit/test_grant_policy.py -q
# 10 passed
```

## 4. 边界与后续

- 本任务只留失败测试与记录，不修复；F-02 起逐项转绿。
- 未使用 `xfail` 隐藏严重项。
- 未改生产代码；未 push；未调用真实模型/网络；未读写用户业务库；Git 复现只用 argv 记录。
- 真实 PR 记录仍为 BLOCKED；F-01 不改变该结论。
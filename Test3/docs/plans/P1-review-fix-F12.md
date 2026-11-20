# P1 审查修复 · F-12 恒真 revision 断言修正与整套回归

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`9fbbd2074e2d6f0a9d73e812ff9662a8a397a0ff`
- 起点：`03c9547070870c16cad0cd9cd41f9265035673ac`（F-11 记录），核对无差异。
- 范围：只做 F-12；未进入 P2，未处理 F-06 隔离遗留，未打开生产总闸。
- 结论：两处“局部 `run_revision = 5` 再断言等于 5”已删除，替换为真实 `run.revision`
  变化后调用生产授权守卫的测试；REV-09 守门测试转绿。

> 说明：本轮要求的修复任务书 `Test3/docs/plans/P1-review-fix-F12.md` 在起点不存在
> （目录只有 F-01～F-11），本记录依据本轮提示词执行；未虚构已读文件。

## 1. 修复前的失败原因

```text
tests/unit/test_p1_rev09_revision_assertion.py::test_revision_tests_do_not_contain_tautologies
AssertionError: test_grant_policy.py still contains a local revision tautology
```

`test_grant_policy.py` 与 `test_grant_refresh.py` 各有：

```python
run_revision = 5
assert ... is None
assert run_revision == 5
```

这个 5 只存在于测试局部，没有传入被测函数，也没有改变真实 run；断言恒真，
不能证明“普通 revision 变化不会让 Grant 失效”。

## 2. 替换方式

### 2.1 `test_grant_policy.py`

- 删除 `test_revision_is_not_an_input()`（局部恒真断言）；
- 保留 `test_signature_has_no_revision_parameter()`：`grant_stale_reason` 的参数集合仍是
  `{"grant", "approved_baseline_hashes", "requested_task_codes"}`，且不含 revision。

### 2.2 `test_grant_refresh.py`

- 删除原局部恒真 `test_revision_is_not_an_input()`，保留
  `test_refresh_signature_has_no_revision_parameter()`；
- 新增真实 run 的两个测试，使用 F-04 已落地的生产启用路径：
  `install_plan` → `_record_approved_baseline("PLAN")` → `enable_granted_execution` →
  `add_grant(active, matching hashes, explicit tool refs)`。

`test_real_run_revision_bump_does_not_stale_active_grant`：

1. 记录真实 `run.revision` 与任务 `revision`；
2. `run.revision += 5`、`task["revision"] += 3`；
3. 调用生产守卫 `Workbench._authorize_granted_execution(run, "T-01")`；
4. 断言返回的 Grant 仍 `active`、物化 spec 的 `approved_baseline_hashes["PLAN"]` 等于批准值、
   `refresh_grant_status` 仍为 `active`；
5. 断言 `run.revision` 与任务 revision 确实变成了新值（真实对象，不是局部变量）。

`test_real_run_revision_bump_does_not_hide_a_changed_baseline`：

- 同样先 bump 真实 revision；
- 修改 `run.artifacts["plan"]` 后调用同一生产守卫；
- 断言仍抛 `GrantRejected(category="baseline_stale")`，证明上一条不是“守卫永远通过”。

没有使用假函数或局部变量冒充生产路径；F-04 的启用/物化/绑定代码全部真实执行，
SQLite 与 PLAN 权威校验也参与其中。

## 3. 保留项

- `test_p1_rev09_revision_assertion.py` 原样保留（继续扫描两个文件，禁止局部 revision
  恒真断言），未删除、未弱化；
- F-01～F-11 的负路径测试全部保留：授权边界、工具三层交集、隔离预检、evidence 安全、
  Git 绑定、PR unknown 禁止 create；
- legacy / 退休运行回归保留，并在本轮重新运行。

## 4. 测试命令与结果

定向：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_grant_policy.py \
  tests/unit/test_grant_refresh.py \
  tests/unit/test_p1_rev09_revision_assertion.py \
  -o addopts='' -m 'not live'
# 17 passed
```

加 REV-01 授权边界：

```text
.venv/bin/python -m pytest \
  tests/unit/test_grant_policy.py \
  tests/unit/test_grant_refresh.py \
  tests/unit/test_p1_rev09_revision_assertion.py \
  tests/unit/test_p1_rev01_execution_boundary.py \
  -o addopts='' -m 'not live'
# 38 passed
```

F-05～F-11 授权/隔离/evidence/Git/PR 回归：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev02_live_git_binding.py \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  tests/unit/test_p1_f08_tool_authorization.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_p1_rev03_evidence_safety.py \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  tests/unit/test_isolated_execute_task.py \
  tests/unit/test_p1_rev06_pr_list_unknown.py \
  tests/unit/test_live_git_idempotent.py \
  -o addopts='' -m 'not live'
# 1 failed, 120 passed, 2 skipped
```

唯一失败仍是
`test_p1_rev03_isolation_escape.py::test_whitelisted_pytest_cannot_write_absolute_outside_path`：
本机 Docker daemon 不可达，worker 在写 evidence 前抛 `IsolationUnavailable`，逃逸复现无法执行。
该用例未删除、未 skip、未弱化，按环境限制记录。

e2e 回归：

```text
.venv/bin/python -m pytest \
  tests/e2e/test_deepseek_retired.py \
  tests/e2e/test_m1_study_room.py \
  tests/e2e/test_schedule_dependencies.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  -o addopts='' -m 'not live'
# 17 passed
```

全量非 live：

```text
.venv/bin/python -m pytest -o addopts='' -m 'not live'
# 1 failed, 404 passed, 2 skipped, 2 deselected in 21.57s
```

相对 F-11（`2 failed, 402 passed, 2 skipped, 2 deselected`）：

- REV-09 转绿，失败 2 → 1；
- 选中用例 406 → 407（refresh 文件 1 条恒真测试替换为 3 条真实测试，净 +1；policy 文件 −1）；
- 通过数 402 → 404（新增 1 条 + 原 REV-09 转绿）；
- 2 条跳过仍是无后端时的隔离成功路径。

全量仍有既有的 aiosqlite `Event loop is closed` 线程警告（来自
`test_execution_grant_api.py`），不影响结果，与本轮改动无关。

`ruff check`（本轮两个测试文件）：通过。

## 5. 结论边界

- `execution_safety_not_ready` 只证明生产总闸关闭，不证明真实隔离执行；
- 授权/工具交集/Git 绑定测试通过，不等于真实隔离执行或真实 PR 已验收；
- F-06 未关闭项不变：真实后端执行、镜像 pytest/依赖、宿主 PATH、成功路径断言、
  整树 rw 挂载的 scope 限制；
- F-12 完成不等于 P1 全通。

## 6. 生产总闸、PR 记录与隔离遗留

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 保持唯一赋值，
  `grep "execution_safety_ready = True" app/` 无结果；
- `tests/e2e/test_granted_v1_sandbox_write.py` 通过：生产 granted 入口先返回
  `execution_safety_not_ready`；
- `Test3/docs/plans/p1-pr-record.json` 未改动，仍为
  `"status": "BLOCKED"`、`"github_pr_url": null`、`push_attempted/pr_attempted: false`；
- 未安装/启动 Docker、未拉镜像、未启动服务、未迁移数据库、未调用真实或付费 API、
  未读取令牌/密钥/`.env`、未动 `Test3/data` 或实际业务库；
- 未 push、未创建 PR、未 merge/deploy。

## 7. 修改文件与工作区

| 文件 | 变更 |
|---|---|
| `Test3/backend/tests/unit/test_grant_policy.py` | 删除局部 revision 恒真断言，保留签名守卫 |
| `Test3/backend/tests/unit/test_grant_refresh.py` | 删除恒真断言；新增 2 条真实 run revision + 生产守卫测试 |
| `Test3/docs/plans/P1-review-fix-F12.md` | 本记录 |

- 测试提交：`9fbbd2074e2d6f0a9d73e812ff9662a8a397a0ff`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前后 tracked 工作区均干净；未跟踪项仅原有 `P1-review.md` 与 4 个 P0 文件，未纳入提交。

## 8. 停止点

F-12 完成，等待验收。**不进入 P2，不处理 F-06 隔离遗留，不打开 `execution_safety_ready`，
不向其他终端投递提示词。**
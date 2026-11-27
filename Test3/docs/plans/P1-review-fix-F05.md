# P1 审查修复 · F-05 真实执行边界统一校验

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`ed9fa47aa14593afb08f2cd439e26edcbc348758`
- 范围：只做 F-05；未进入 F-06 或 P2。
- 结论：`execute`、`retry`、缺陷递归、takeover submit 统一走同一授权入口；granted_v1 不再因缺少
  Grant 或 `granted_execution` 落入 legacy agent/commit/merge。生产执行总闸仍为关闭。

## 1. 入口与公共校验的对应关系

公共校验：`Workbench._authorize_granted_execution(run, code)`，返回已验证的 `(grant, spec)`。
它固定按以下顺序失败关闭：profile → task/run 绑定 → Grant 存在且 active → 任务在 `task_codes` 内 →
Grant baseline → `granted_execution` 绑定 → PLAN 四方一致 → SQLite 权威。

| 真实入口 | 调用点 | 校验时机 |
|---|---|---|
| 调度/自动循环 `schedule_once` | `_granted_scope()` 预筛 + `execute_task()` | 预筛只判断 Grant/scope；真正执行前再走公共校验 |
| 直接 `execute_task` | `_authorize_granted_execution()` | revision bump、状态迁移、worktree、命令之前 |
| HTTP retry / `control_task("retry")` | `control_task()` 内先公共校验，再由 `execute_task` 复核 | `task["revision"]`、状态、事件之前 |
| 缺陷修复递归 `_finish_failure("代码缺陷")` | `_finish_failure()` 顶部公共校验，递归 `execute_task` 复核 | `signatures`、`repair_rounds`、状态迁移之前 |
| takeover submit | `control_task()` 与 `_submit_takeover()` 显式拒绝 | `takeover_submit` 标记、revision、worktree、merge 之前 |
| legacy review/merge `_accept_review_merge` | 显式拒绝 | 验收命令、commit、merge 之前 |
| granted worker `_execute_granted_task` | 只接收已校验的 `grant/spec` | 不再自行查询 Grant，也不做“最新任意状态”回退 |

调度预筛 `_granted_scope()` 已移除 `active[-1] if active else grants[-1]` 回退；无 active Grant 时按
`grant_revoked` / `grant_consumed` / `baseline_stale` / `grant_not_active` 拒绝。授权子集按
`requested ⊆ grant.task_codes` 选择 active Grant。

## 2. 拒绝原因与零副作用证据

| 触发条件 | `error_category` | HTTP | 零副作用断言 |
|---|---|---:|---|
| granted_v1 无任何 Grant | `grant_required` | 403 | sentinel 未调用；无 `wt/T-01`、`wt/granted-T-01` |
| 任务不在授权范围（T-01 Grant，retry T-02） | `scope_mismatch` | 409 | 状态仍 `failed`，revision 仍 1，evidence 为空，sentinel 未调用 |
| Grant 为 revoked / consumed | `grant_revoked` / `grant_consumed` | 409 | 任务未 done；未创建 granted worktree |
| Grant 为 stale | `baseline_stale` | 409 | 同上 |
| 非 active 且无其他 active Grant | `grant_not_active` / 对应状态原因 | 409 | 不回退到最新 Grant |
| 缺少 `granted_execution` | `granted_spec_missing` | 409 | sentinel 未调用；未进入 legacy agent/worktree |
| spec 类型损坏 / profile 不是 granted_v1 | `granted_spec_invalid` | 409 | 同上 |
| spec 的 `task_code` / `task_codes` 与任务不符 | `grant_binding_mismatch` | 409 | 同上 |
| spec 绑定到其他 Grant | `grant_binding_mismatch` | 409 | 同上 |
| Grant 属于其他 run（本 run 查不到） | `grant_required` | 403 | 任务未 done |
| PLAN artifact 在批准后被修改 | `baseline_stale` | 409 | 任务未 done |
| 物化 spec 的 `approved_plan_hash` 不符 | `baseline_stale` | 409 | 同上 |
| SQLite `approved_plan_hash` 与当前 PLAN 不符 | `baseline_stale` | 409 | 证明不只信内存/spec/客户端 |
| granted_v1 走 takeover submit 或 legacy merge | `granted_manual_merge_disabled` | 409 | 状态/revision 不变，`takeover_submit` 未置位，sentinel 未调用 |

PLAN 一致性同时比较：当前 PLAN artifact、`approved_baseline_hashes["PLAN"]`、
`run.artifacts["plan_materialized"]`、`granted_execution.approved_plan_hash`、
`granted_execution.approved_baseline_hashes["PLAN"]`、SQLite `run_execution_state.approved_plan_hash`
与 hashes。`_materialize_tasks()` 的物化摘要改为与 `hash_artifact()` 相同，避免两套摘要永远不相等。

授权子集连续执行测试：同一 Grant 覆盖 T-01/T-02，先 bump `run.revision` 与 T-01 revision，再 bump
run/T-02 revision，两次真实 `execute_task` 均执行成功（worker 由测试替身返回离线结果），说明普通
revision/任务进度不会使 Grant 失效，也没有逐任务审批。

## 3. 测试命令与结果

新增/替换的定向测试：

```text
cd Test3/backend
.venv/bin/python -m pytest tests/unit/test_p1_rev01_execution_boundary.py -q -o addopts=''
# 17 passed
```

修复前同文件：`14 failed, 3 passed`（失败项为上述无 Grant、越权 retry、revoked/consumed/stale、
spec 缺失/损坏/错绑、PLAN 变更、SQLite plan hash、缺陷递归、takeover submit）。

相关 Grant / enable / 调度回归：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  tests/integration/test_p1_rev08_production_enable_path.py \
  tests/unit/test_schedule_grant_guard.py \
  tests/integration/test_schedule_grant_http.py \
  tests/integration/test_execution_grant_api.py \
  tests/unit/test_grant_policy.py \
  tests/unit/test_grant_refresh.py \
  tests/unit/test_grant_repo.py \
  -q -o addopts='' -m 'not live'
# 69 passed
```

全量非 live：

```text
.venv/bin/python -m pytest -m 'not live' -q -o addopts=''
# 9 failed, 293 passed, 2 deselected in 22.48s
```

相对 F-04 收尾（`9 failed, 278 passed, 2 deselected`）新增 15 条通过，失败数不变。剩余 9 条均为
后续批次仍未修复的 F-01 红灯，不属于 F-05：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-02 push main / 无授权 commit | 2 | F-09、F-10 |
| REV-03 evidence symlink / 子进程逃逸 | 2 | F-06、F-07 |
| REV-06 list 未知仍 create | 2 | F-11 |
| REV-07 否定授权 / 结构化记录 | 2 | F-09 |
| REV-09 revision 恒真断言 | 1 | F-12 |

`ruff check app/services/runtime.py tests/unit/test_p1_rev01_execution_boundary.py`：通过。

## 4. 执行总闸仍关闭的证据

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动；生产代码没有任何赋值为
  `True` 的路径。
- F-04 的 `tests/e2e/test_granted_v1_sandbox_write.py` 仍通过：granted 任务在生产路径返回
  `GrantRejected("execution_safety_not_ready")`，不会创建 worktree。
- F-05 新测试只在进程内临时置 `bench.execution_safety_ready = True`，用于验证总闸之后的边界逻辑；
  测试结束即销毁，未改变生产默认值。
- 未启动/停止服务，未迁移用户数据库；所有 SQLite 写入都在 `tmp_path`。
- 未调用真实或付费 API；未 push、未创建 PR、未 merge/deploy。

## 5. 修改文件

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/services/runtime.py` | 统一授权入口；retry/递归/takeover/merge 守卫；移除 Grant 状态回退；PLAN 四方一致性；物化摘要统一 |
| `Test3/backend/tests/unit/test_p1_rev01_execution_boundary.py` | F-05 边界失败测试替换/扩展（17 条） |
| `Test3/docs/plans/P1-review-fix-F05.md` | 本记录 |

## 6. 停止点

F-05 完成，等待审查。**不进入 F-06 或 P2。** F-05 通过不等于整个 P1 或真实 PR 验收通过；
真实 PR 仍为 `BLOCKED`。
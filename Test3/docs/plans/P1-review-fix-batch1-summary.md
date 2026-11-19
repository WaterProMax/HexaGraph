# P1 审查修复 · 第一批小结（F-01 ~ F-04）

- 日期：2026-11-19（Asia/Singapore）
- 分支：`feat/test3-agent-team-v1`
- 基线/审查 HEAD：`520b15c102ee3f4674f61977cd766c14b84f6fd3`
- 范围：只做 F-01、F-02、F-03、F-04；**未开始 F-05，未进入 P2**。
- 停止点：第一批完成，等待人审。

## 1. 提交

| 提交 | 内容 |
|---|---|
| `5310d5a` | F-01 九项失败回归测试 + 验证记录 |
| `a8d149c` | F-02 SQLite 权威 profile/hashes + fail-closed 恢复 |
| `9d1aa4d` | F-03 Alembic 单一 schema 权威 |
| `652379e` | F-04 服务端启用端点 + 生产 granted 物化 |
| `3b3d9f6` | F-04 收尾：conflict 持久、hashes 同步、regression 安全门 |

## 2. 各任务结果

### F-01 · 验证

- 在审查 HEAD 上逐项复现 REV-01…09；修复前 `18 failed, 7 passed`。
- 每项均有独立测试文件/用例；未使用 `xfail` 隐藏严重项。
- 记录：`Test3/docs/plans/P1-review-fix-F01.md`。

### F-02 · 持久化恢复

- 新增 `run_execution_state` 表（SQLite）与 `RunExecutionStateRepo`。
- 恢复先读 SQLite；损坏 snapshot / events-only 不再把 granted 降为 legacy。
- 缺 profile → `unspecified`，调度/执行 fail closed；SQLite 与残余 JSON 冲突 → `conflict`。
- 既有 legacy run 保持 legacy，JSONL 不改写。
- 人批更新 baseline hashes 时同步 SQLite；conflict 标记跨重启保留。
- 记录：`Test3/docs/plans/P1-review-fix-F02.md`。

### F-03 · 迁移单一权威

- 运行时启动只执行 Alembic `upgrade head`，生产路径不再 `create_all()`。
- 0001/0002/0003 均为 schema-aware：识别旧 Workbench 已建表并核对列，缺列报 drift；未使用 `stamp`。
- 两条历史冲突路径（0001 后 Workbench 建 grants；runtime 先建表再 Alembic）均通过。
- 记录：`Test3/docs/plans/P1-review-fix-F03.md`。

### F-04 · 生产启用与物化

- 新端点 `POST/GET /api/runs/{run_id}/execution-profile`；body 只允许 `granted_v1`，legacy 降级 4xx。
- `enable_granted_execution()` 校验 hashes / plan hash 后写 SQLite；启用后重启仍为 granted。
- `_materialize_tasks()` 为范围内任务生成 `granted_execution`（plan hash、scope、write_set、command、
  tool refs、grant_id、source）。
- `execution_safety_ready` 服务端属性保持 `False`；`execute_task`、review/merge、takeover submit、
  regression 均抛 `GrantRejected("execution_safety_not_ready")`，不接通旧 legacy/auto-merge 链。
- e2e `test_granted_v1_sandbox_write.py` 已改为生产 enable/materialize + 拒绝断言，不再手工注入。
- 记录：`Test3/docs/plans/P1-review-fix-F04.md`。

## 3. 测试结果

本批新增/更新的定向测试：

```text
tests/unit/test_p1_rev01_execution_boundary.py            2 passed
tests/unit/test_p1_rev04_profile_recovery.py               8 passed
tests/integration/test_p1_rev08_production_enable_path.py  6 passed
tests/integration/test_execution_grant_api.py              7 passed
tests/e2e/test_granted_v1_sandbox_write.py                 2 passed
tests/integration/test_p1_rev05_alembic_handoff.py         3 passed
tests/integration/test_alembic_execution_grants.py         1 passed
tests/unit/test_grant_repo.py                              4 passed
```

全量非 live（`-o addopts='' -m 'not live'`）：

```text
9 failed, 273 passed, 2 deselected in 21.97s
```

剩余 9 条是**故意保留给后续批次**的 F-01 红灯：

| 失败项 | 对应后续任务 |
|---|---|
| REV-02 push main / 无授权 commit（2） | F-09、F-10 |
| REV-03 evidence symlink / 子进程逃逸（2） | F-06、F-07 |
| REV-06 list 未知仍 create（2） | F-11 |
| REV-07 否定授权 / 结构化记录（2） | F-09 |
| REV-09 revision 恒真断言（1） | F-12 |

REV-01、REV-04、REV-05、REV-08 已在本批转绿。全量套件当前为红是预期状态，不是本批遗漏。

## 4. 安全与边界

- 未启动服务；未调用真实模型、真实网络、真实 GitHub；未 push、未创建 PR。
- 未对 `Test3/data/` 或任何用户实际业务库执行迁移/写入；迁移演练只在 `tmp_path`。
- 未读写密钥；Git 只用 argv/假 runner。
- 新 granted 执行入口在第一批保持拒绝，`execution_safety_ready=False`；F-05/F-06 通过前不得置真。
- HTTP retry / accept 对 granted 未就绪返回受控 409，而不是 500；retry 在改状态前就被拒绝。
- 真实 PR 记录仍为 `BLOCKED`（`docs/plans/p1-pr-record.json`，`github_pr_url=null`）。
- 无 P2 改动，未改前端退休页面/下线守卫。

## 5. 人审门与下一步

1. 人审 F-01 复现与 F-02/F-03/F-04 实现，特别是 SQLite 恢复语义与迁移 schema-aware 分支。
2. 确认是否进入第二批 F-05：把 Grant 检查放到 execute/retry/递归/takeover/review/merge 真实边界，
   并用 `execution_safety_ready` 之前的临时总闸替换为逐入口检查。
3. F-05 之后才做 F-06–F-08 隔离/证据/工具交集；F-09 先于 F-10/F-11；F-12 最后。
4. 真实 PR 仍 BLOCKED；修复测试全绿不等于首版真实 PR 达标。
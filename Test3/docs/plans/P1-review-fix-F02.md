# P1 审查修复 · F-02 SQLite 权威持久化与 fail-closed 恢复

- 日期：2026-11-19（Asia/Singapore）
- 前置：F-01 已提交（`5310d5a`），REV-04 失败测试存在。
- 本任务未启动服务，未访问真实网络/模型，未触碰用户实际业务库（只用 `tmp_path`）。

## 1. 实现

### 1.1 SQLite 新表（新域权威）

`app/storage/models.py` 新增 `run_execution_state`：

| 列 | 说明 |
|---|---|
| `run_id` | 主键 |
| `execution_profile` | 仅 `legacy` / `granted_v1` |
| `approved_baseline_hashes` | JSON object |
| `approved_plan_hash` | 批准计划 hash |
| `allowed_tool_refs` | JSON array |
| `updated_at` | 时间戳 |

`alembic/versions/0003_run_execution_state.py` 增加对应迁移；若旧 Workbench 的
`create_all()` 已建表，先核对列集合，缺列即报 schema drift，不做 stamp。

### 1.2 读取与恢复

新增 `app/execution/run_state_store.py`：

- `read_run_execution_state(db_path, run_id)`：恢复阶段用只读 sqlite3 连接读取，不建库、不迁移。
- `RunExecutionStateRepo`：异步 upsert。
- 状态区分：`legacy` / `granted_v1` / `unspecified` / `conflict`。

`run_profile.py` 语义改为：

- `run.execution_profile` 显式为先；缺失时快照键只能证明 `legacy` / `granted_v1`；
- 全无证据 → `unspecified`，**不再默认 legacy**；
- 未知值 → `conflict`。

`Workbench.restore_runs()` 在反序列化后调用 `_restore_execution_profile()`：

1. SQLite 有行：以 SQLite 为准，恢复 profile 与 hashes；
2. 快照/SQLite 互相矛盾（granted vs legacy、hashes 不同）→ `conflict`；
3. SQLite 无行但残余 JSON 声称 granted → `conflict`（残余 JSON 不能单独授权）；
4. SQLite 无行、快照明确 legacy → legacy；
5. 全部缺失 → `unspecified`。

损坏 snapshot 走 events-only 时，`artifacts` 为空也不再丢 granted：SQLite 行仍在即恢复；
若 SQLite 也无行则 `unspecified`，不会降成 legacy。

### 1.3 新 run 与 legacy 兼容

- `create_run()` 在发出首个事件前显式写 `execution_profile = legacy`（服务端默认，不是“缺 key 当 legacy”）。
- `create_design_run()` 同样显式 legacy。
- 已存在且证据为 legacy 的 run 恢复后仍 legacy，`events.jsonl` 不被本任务改写。
- `schedule_once()` / `execute_task()` 对 `unspecified` / `conflict` 抛 `GrantRejected`
  （`profile_unspecified` / `profile_conflict`，409），不会进入 legacy 分支。
- `_granted_scope()` 只对显式 `legacy` 放行；`granted_v1` 仍走 Grant 校验。

### 1.4 持久化 API

`Workbench.persist_run_execution_state(run_id, profile, hashes, *, approved_plan_hash, allowed_tool_refs)`
写 SQLite、更新内存、发 `execution_profile.changed` 事件并落快照。该方法是 F-04 生产启用端点的底层；
`set_run_execution_profile()` 仍保留为 internal/test fixture，不作为生产启用来源。

## 2. 测试与结果

`tests/unit/test_p1_rev04_profile_recovery.py` 覆盖：

- 正常重启后仍为 `granted_v1`（只依赖持久化）；
- 正确 granted snapshot 被写坏后走 events-only，仍为 `granted_v1`，hashes 恢复，Grant 仍约束；
- 缺 profile → `unspecified`，调度抛 `profile_unspecified`；
- SQLite 与残余 JSON 冲突 → `conflict`，调度抛 `profile_conflict`；
- 既有 legacy run 恢复后仍 legacy，`events.jsonl` 字节不变。

命令：

```text
cd Test3/backend && .venv/bin/python -m pytest \
  tests/unit/test_p1_rev04_profile_recovery.py tests/unit/test_grant_policy.py -v
# 16 passed
```

全量非 live 回归（其余失败均为 F-05…F-12 尚未修复项）：

```text
cd Test3/backend && .venv/bin/python -m pytest -m 'not live' -q
# 仅剩 REV-01/02/03/05/06/07/08/09 的 F-01 红灯
```

## 3. 边界与后续

- 未改用户实际业务库；迁移只在 `tmp_path` / 测试库演练。
- 生产启用端点与 `granted_execution` 物化在 F-04 接入；本任务仅提供持久化底层。
- F-05 才统一 execute/retry/递归/takeover 的 Grant 副作用边界；当前 granted 执行尚未放开。
- 真实 PR 记录仍为 BLOCKED。
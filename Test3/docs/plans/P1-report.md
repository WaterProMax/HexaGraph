# P1 执行授权、隔离执行与真实 PR · 阶段报告

- 基线：`552923d9992a38eb806ff760833bb71ac4b759cf`（`feat/test3-agent-team-v1`）
- 隔离树：`/Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1`
- 运行方式：本地 `uv run pytest` + scripted/假适配器；未 push、未创建 PR、未调用真实/付费模型、未启动或操作现有服务。
- 本报告只登记 P1 本地可执行部分；真实 GitHub 写操作标记 BLOCKED。

## P1-T01 · grant_stale_reason 纯函数

新增：

- `Test3/backend/app/execution/__init__.py`
- `Test3/backend/app/execution/grant_policy.py`
- `Test3/backend/tests/unit/test_grant_policy.py`

实现严格按 contracts.md C.3.2：撤销/消费优先，空请求 → `empty_request`，超集 → `scope_mismatch`，逐 key 比较基线 → `baseline_changed:<key>`；函数不接收也不读取 `run.revision` / `task.revision`。子集合法，不因“只执行授权子集”判 stale。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_grant_policy.py -v
collected 10 items
tests/unit/test_grant_policy.py ..........  [100%]
10 passed in 0.01s
```

签名核验（测试内 `inspect.signature` 断言）：

```text
grant, approved_baseline_hashes, requested_task_codes
```

并发：纯函数无共享可变状态，按任务卡不写并发用例。权限：纯函数无调用者身份，超集用例覆盖范围越权。无网络访问。
## P1-T02 · ExecutionGrant 模式、表与仓库

新增：

- `Test3/backend/app/schemas/execution_grant.py`
- `Test3/backend/app/execution/grant_repo.py`
- `Test3/backend/app/storage/models.py`（仅追加 `ExecutionGrantRow`）
- `Test3/backend/alembic/versions/0002_execution_grants.py`（P0 `next_alembic_hint=0002`）
- `Test3/backend/tests/unit/test_execution_grant_schema.py`
- `Test3/backend/tests/unit/test_grant_repo.py`
- `Test3/backend/tests/integration/test_alembic_execution_grants.py`

要点：

- `ExecutionGrantCreate.task_codes` 使用 `Field(min_length=1)`；空列表在模型层 `ValidationError`，`loc` 含 `task_codes`。
- `execution_profile` 为 `Literal["granted_v1"]`；传 `"legacy"` 校验失败。
- `execution_grants` 表含 `grant_id` PK、`run_id` 索引 `ix_execution_grants_run`、`status`、`payload`；升级/降级在独立临时 SQLite 上验证。
- `GrantRepo.add` 使用调用方 session，调用方 rollback 后新 session 查询为空；`list_for_run` 只返回该 run；重复 PK 第二次插入抛 `IntegrityError` 且库中仅一行。
- 数据库路径：P0 未发现 `TEST3_DB`；仓库既有 `Settings.test3_data_dir()` / `Test3/data`。本卡不改既有默认路径，测试一律用 `tmp_path`；P1-T03 起由 Workbench 在 `data_dir/test3.db` 惰性建库（见 §P1-T03）。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_execution_grant_schema.py tests/unit/test_grant_repo.py tests/integration/test_alembic_execution_grants.py tests/unit/test_grant_policy.py -v
collected 19 items
... 19 passed in 0.31s
```

并发：`test_two_sessions_duplicate_pk_only_one_row` 覆盖同一 PK 双写；SQLite 仅保留一行。无真实网络/模型调用。

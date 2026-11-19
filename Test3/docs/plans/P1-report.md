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

## P1-T03 · ExecutionGrant HTTP 与 execution_profile 服务端所有

修改/新增：

- `[MODIFY] Test3/backend/app/api/routes.py`：新增 `POST/GET /api/runs/{run_id}/execution-grants`；新错误体为顶层 `{"error_category", "detail"}`；未新增任何 profile 降级路由。
- `[MODIFY] Test3/backend/app/services/runtime.py`：仅追加 ExecutionGrant 域方法（惰性 SQLite 引擎、`db_session`、`set_run_execution_profile`、`set_run_approved_baseline_hashes`、`add_grant`、`grants_for_run`、`close`），未改既有调度/退休/legacy 分支。
- `[MODIFY] Test3/backend/app/errors.py`：追加 `GrantRejected`、`GitHubWriteDenied`。
- `[MODIFY] Test3/backend/app/main.py`：lifespan 关闭时 `await workbench.close()`。
- `[MODIFY] Test3/backend/app/storage/models.py`：沿用 P1-T02 的 `ExecutionGrantRow`。
- `[NEW] Test3/backend/app/execution/run_profile.py`：profile / `approved_baseline_hashes` 的读写 helper（存 `run.artifacts`，P0 未发现对应 SQLite 列）。
- `[MODIFY] Test3/backend/tests/integration/snapshots/openapi_structure.json`：新增两条路由后按既有测试说明用 `UPDATE_OPENAPI_SNAPSHOT=1` 重生成。
- `[NEW] Test3/backend/tests/integration/test_execution_grant_api.py`

数据库路径：`Workbench.data_dir / "test3.db"`，首次使用 grant 域时惰性 `create_all`；测试全部用 `tmp_path`，未触碰 `Test3/data/`。C.6 的 `execution_grants` 仍是该域唯一写权威。

行为：

- 201 返回 `status=active`、回显 `task_codes`、含 `grant_id`；GET 返回 `{items: [...]}`。
- run 不存在 → 404 `run_not_found`；legacy run → 403 `profile_not_granted_v1`；hashes 与 run 当前基线不一致 → 409 `baseline_stale`；`task_codes` 空 → 400 `validation_error`（进入仓库前失败）。
- `PATCH /api/runs/{id}` 与 `POST /api/runs/{id}` 均非路由（405/404），profile 仍是 `granted_v1`。
- 并发双 POST 由 `Workbench._grant_write_lock` 串行化，两条 grant 均 201 且无半截行；允许同一 run 保留多条历史 grant，调度取最新一条（P1-T04）。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/integration/test_execution_grant_api.py -v
collected 7 items
tests/integration/test_execution_grant_api.py .......  [100%]
7 passed in 0.82s

$ cd Test3/backend && uv run pytest tests/unit/test_grant_policy.py tests/unit/test_execution_grant_schema.py tests/unit/test_grant_repo.py tests/integration/test_alembic_execution_grants.py tests/integration/test_execution_grant_api.py tests/integration/test_api_contract.py -q
54 passed
```

人工验收 curl（本轮未启动 uvicorn，按任务卡允许以 pytest 断言为准；以下为等价请求体）：

```bash
curl -sS -D - -X POST http://127.0.0.1:<port>/api/runs/<granted-run>/execution-grants \
  -H 'Content-Type: application/json' \
  -d '{"execution_profile":"granted_v1","task_codes":["T-01"],"approved_baseline_hashes":{"PLAN":"aaa"},"repo_remote":"origin","repo_owner":"WaterProMax","repo_name":"HexaGraph","base_branch":"teamwork-001","feature_branch":"feat-p1-demo","allowed_tool_refs":[]}'
# 期望 201 + "status":"active"
```

## P1-T04 · schedule 守卫：子集连续执行与 legacy 零回归

修改/新增：

- `[MODIFY] Test3/backend/app/services/runtime.py`：`schedule_once(run, *, task_codes=None)` 在进入既有调度锁前调用 `_granted_scope`；`_schedule_once_locked(..., allowed=...)` 只派发授权集合内任务；新增常量 `_GRANT_COMPLETED_STATES`。未改退休守卫与 legacy 调度算法。
- `[MODIFY] Test3/backend/app/api/routes.py`：schedule 接受可选 `{task_codes}`；`GrantRejected` 映射为顶层 ErrorBody；无 body / 无 `task_codes` 表示“grant 范围内尚未完成的任务”。
- `[MODIFY] Test3/backend/tests/integration/snapshots/openapi_structure.json`：schedule 请求体后按既有测试重生成。
- `[NEW] Test3/backend/tests/unit/test_schedule_grant_guard.py`
- `[NEW] Test3/backend/tests/integration/test_schedule_grant_http.py`

行为：

- `legacy`：`_granted_scope` 立即返回 `None`，不查 grant、不新增 403/409；既有 legacy 调度测试保持通过。
- `granted_v1` 无 grant → 403 `grant_required`；超集 → 409 `scope_mismatch`；空请求 → 409 `empty_request`；`status=stale` → 409 `baseline_stale`；`revoked/consumed` → 409 `grant_revoked` / `grant_consumed`。
- 子集可连续执行；`run.revision` 变化不影响（守卫只读 hashes 与 scope）。
- 同一 run 的并发 schedule 由既有 `_schedule_lock_for` 串行化；本卡测试断言同一时刻只有一个 in-flight。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_schedule_grant_guard.py tests/integration/test_schedule_grant_http.py -v
collected 13 items
tests/unit/test_schedule_grant_guard.py .......  [53%]
tests/integration/test_schedule_grant_http.py ......  [100%]
13 passed in 0.93s

$ cd Test3/backend && uv run pytest tests/e2e/test_m1_study_room.py tests/e2e/test_schedule_dependencies.py tests/e2e/test_must_fixes.py tests/integration/test_api_contract.py -q
44 passed

$ cd Test3/backend && uv run pytest <T01–T04 测试 + api_contract> -q
67 passed
```

人工验收 curl（未起 uvicorn，以 pytest 断言为准）：

```bash
# 期望 403 grant_required
curl -sS -D - -X POST http://127.0.0.1:<port>/api/runs/<granted-without-grant>/schedule -H 'Content-Type: application/json' -d '{"task_codes":["T-01"]}'
# 已有 grant 且范围含 T-01 时期望 200
curl -sS -D - -X POST http://127.0.0.1:<port>/api/runs/<granted-ok>/schedule -H 'Content-Type: application/json' -d '{"task_codes":["T-01"]}'
```

legacy 回归文件：P0 指定的 `tests/e2e/test_m1_study_room.py` 实际存在并已运行；另跑 `tests/e2e/test_schedule_dependencies.py`、`tests/e2e/test_must_fixes.py`。无 deepseek 守卫 diff，无 live 模型调用。

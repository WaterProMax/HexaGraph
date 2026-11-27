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

## P1-T05 · 批准写入 approved_baseline_hashes 与 grant 刷新

修改/新增：

- `[NEW] Test3/backend/app/execution/baseline.py`：`canonical_artifact_bytes` / `hash_artifact` / `write_approved_baseline_hash`（sha256，bytes 原样、dict 用排序紧凑 JSON）。
- `[NEW] Test3/backend/app/execution/grant_refresh.py`：`refresh_grant_status` 只在 `grant_stale_reason` 返回 `baseline_changed:*` 时标 `stale`。
- `[MODIFY] Test3/backend/app/services/runtime.py`：`resolve_gate` 人批成功时先写 hash、刷新 active grant，再 `_freeze`；新增 `baseline.hash` 事件并纳入快照持久化；`_refresh_grant_statuses` 与 `add_grant` 共用 `_grant_write_lock`。未改退休拒绝、legacy 调度与任务状态迁移入口。
- `[NEW] Test3/backend/tests/unit/test_grant_refresh.py`
- `[NEW] Test3/backend/tests/integration/test_resolve_gate_baseline_hashes.py`

Hash key 登记表（P4/P5 必须复用同一字符串）：

| key | 写入时机 | 哈希内容 |
|---|---|---|
| `REQUIREMENT` | “初步做法确认” approve | `{"idea": run.idea, "idea_card": ...}` 的 canonical JSON |
| `SPEC` | “SPEC基线确认” approve | `run.artifacts["spec"]` canonical JSON |
| `DESIGN` | “DESIGN基线确认” approve | `run.artifacts["design"]` canonical JSON |
| `PLAN` | “PLAN基线确认” approve | `run.artifacts["plan"]` canonical JSON |
| `DecisionPackage` | P4 人工规格门 approve | 由 P4 按同一 helper 写入（P1 不实现） |

行为：

- 批准后 `approved_baseline_hashes[key] == hash_artifact(产物)`；`run.revision` 仍按既有逻辑递增。
- 仅 `run.revision` 变化不会使 grant stale；产物 hash 变化 → `refresh_grant_status` 返回 `stale`，DB 状态更新，再 schedule 子集得 409 `baseline_stale`。
- 并发 resolve 由既有 `_gate_lock_for` 串行化：一次 200、一次 400，`run.revision` 只 +1，hash 为完整单次写入值。
- 无权限 resolve：仓库当前无调用者身份/鉴权层，沿用既有门禁与 gate lock；本卡不新增或削弱鉴权，报告声明未新增权限测试。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_grant_refresh.py tests/integration/test_resolve_gate_baseline_hashes.py -v
collected 7 items
tests/unit/test_grant_refresh.py .....  [71%]
tests/integration/test_resolve_gate_baseline_hashes.py ..  [100%]
7 passed in 0.47s

$ cd Test3/backend && uv run pytest tests/e2e/test_m1_study_room.py tests/e2e/test_design_input.py tests/e2e/test_design_input_lifecycle.py tests/e2e/test_later_phases.py tests/e2e/test_deepseek_retired.py -q
27 passed
```

`hash_artifact(b"plan-v1") == sha256(b"plan-v1")` 已由单测固定；gate 集成测试用实际 PLAN artifact 对比 `hash_artifact(plan)`。

## P1-T06 · 隔离 worker：改代码、跑离线测试、收集证据

修改/新增：

- `[NEW] Test3/backend/app/execution/isolated.py`：`WriteSpec`、`CommandResult`、`build_evidence`、`execute_task_granted`、`redact_secrets`。
- `[MODIFY] Test3/backend/app/services/runtime.py`：`execute_task` 在 `execution_profile=granted_v1` 且任务带 `granted_execution` 计划时进入 `_execute_granted_task`；使用 per-task 隔离 worktree（`data_dir/runs/<run>/wt/granted-<code>`，分支 `grant.feature_branch/<code>`），只在该目录写入与跑命令；未改动既有 model/tool 执行路径与 legacy 行为。
- `[NEW] Test3/backend/tests/unit/test_isolated_execute_task.py`
- `[NEW] Test3/backend/tests/e2e/test_granted_v1_sandbox_write.py`
- `[NEW] Test3/docs/plans/p1-evidence-sample.json`（无密钥的 evidence 结构样例）

行为：

- 写入经 `normalize_under` + `in_write_set` 限定在隔离目录；用户项目根不产生 fixture 文件。
- 测试命令来自任务卡 `granted_execution.command`（缺省 `python -m pytest -q -m "not live"`），经既有 `run_command` 白名单执行；环境仅传 `PATH`（可显式追加），不发起 HTTP/模型调用。
- 退出码非 0：证据仍落盘、`ok=false`，任务状态不为 `done`（授予路径用 `env_fail` 标记，不递归重试）。
- evidence JSON 含 `task_code`、`isolation_root`、`written`、`commands[{argv,cwd,exit_code,log_path,output}]`、`ok`、`grant_id`、`run_id`、`feature_branch`；日志与 evidence 均经 `***REDACTED***` 处理 `*_KEY/*_TOKEN/*_SECRET/*_PASSWORD` 环境值。
- 并行两个任务使用各自隔离目录，不交叉写入。未调用网络；pytest 默认 `-m 'not live'`。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_isolated_execute_task.py tests/e2e/test_granted_v1_sandbox_write.py -v
collected 6 items
tests/unit/test_isolated_execute_task.py ....  [66%]
tests/e2e/test_granted_v1_sandbox_write.py ..  [100%]
6 passed in 0.97s

$ cd Test3/backend && uv run pytest <P1-T01…T06 全部测试> -q
52 passed
```

evidence 样例：`Test3/docs/plans/p1-evidence-sample.json`（示例命令 `python -c "print('ok')"`，exit_code 0，log 在临时目录，不提交日志正文）。测试运行时真实 evidence 位于 pytest `tmp_path/runs/<run>/wt/granted-<code>-evidence/`，随临时目录清理。

## P1-T07 · 幂等 git 提交、push、真实 PR（阶段出口）

新增：

- `Test3/backend/app/execution/github_auth.py`：`GitHubWriteAuth` 与 `parse_github_write_auth`；无授权句返回 `None`，字段不全抛 `GitHubWriteDenied`。
- `Test3/backend/app/tools/live_git.py`：`commit_all`、`push_once`、`create_pr_idempotent`。
- `Test3/backend/tests/unit/test_live_git_idempotent.py`
- `Test3/backend/tests/e2e/test_live_pr_optional.py`（`@pytest.mark.live`，默认不运行）
- `Test3/docs/plans/p1-pr-record.json`

行为与边界：

- `push_once` 对同一 marker + 同一 HEAD sha + 同一 feature_branch + 同一 grant_id 的第二次调用不再执行 `git push`；测试假 shell 的 push 次数为 1。
- `create_pr_idempotent` 先 `gh pr list --head <feature> --base <base>` 复用已有 URL；list+create 由进程内锁串行化，并发两次只创建 1 个 PR。返回 URL 必须以 `https://` 开头。
- 拒绝推送 base：refspec 精确比较 `HEAD:refs/heads/<feature_branch>`，任何 argv 等于 `base_branch` 或 refspec 等于 base 均抛 `GitHubWriteDenied`；测试断言 push argv 不含 `teamwork-001` / `refs/heads/teamwork-001`。
- 未授权：`parse_github_write_auth(None) is None`；`push_once(None, ...)` 抛 `GitHubWriteDenied` 且假 shell 调用次数为 0。
- 模块中不存在 `merge_pr` / `gh pr merge` / `deploy` 函数或命令；防护测试扫描 `live_git.py` 源码，禁止子串 `pr merge`、`gh merge`、`git merge --no-ff origin`、`deploy`。
- 未自动把“全部 granted task 成功”接到真实发布：没有授权时绝不自动出网；本阶段不新增任何隐式 push/PR 触发器。
- `model_live` 与 `github_write` 分离：本轮两者都没有，因此不调用真实/付费模型。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_live_git_idempotent.py -v
collected 7 items
7 passed in 0.04s

$ cd Test3/backend && uv run pytest -m live tests/e2e/test_live_pr_optional.py -q
s  (1 skipped: missing github_write authorization)
```

`p1-pr-record.json`（实际内容）：

```json
{
  "status": "BLOCKED",
  "reason": "missing_github_write",
  "mv_04": "not_completed",
  "authorization_present": false,
  "push_attempted": false,
  "pr_attempted": false,
  "github_pr_url": null
}
```

**MV-04 本阶段未完成**：没有真实 `github_pr_url`。BLOCKED 不当作首版验收通过。

## P1 阶段汇总

| 卡 | 本地状态 | 证据 |
|---|---|---|
| P1-T01 | 完成 | `tests/unit/test_grant_policy.py` 10 passed；commit `05d226b` |
| P1-T02 | 完成 | schema/repo/alembic 9 passed；commit `187fcf1` |
| P1-T03 | 完成 | API 7 passed；OpenAPI 快照已更新；commit `728852c` |
| P1-T04 | 完成 | guard 13 passed；legacy e2e 44 passed；commit `47bc415` |
| P1-T05 | 完成 | refresh/gate 7 passed；gate 相关 e2e 27 passed；commit `7d3e44f` |
| P1-T06 | 完成 | isolated/evidence 6 passed；commit `ad7c90e` |
| P1-T07 | **BLOCKED（缺 github_write）** | 假适配器 7 passed；真实 PR 未尝试 |

全量后端回归（非 live）：

```text
$ cd Test3/backend && uv run pytest -m "not live" -q
250 passed
```

下线边界回归：

- 未修改 `Test3/frontend/src/App.tsx`；静态课堂与 `/deepseek` 退休路由无 diff。
- `runtime.py` 的 DeepSeek 退休只读判断、`_reject_retired`、`_is_retired_run`、恢复只读分支、legacy schedule/execute 路径均保留；新增代码仅限 grant 分支与批准的 hash 写入。
- `routes.py` 的 `_retired` / 410 映射、schedule/gates 既有行为保留；新增 grant 路由与可选 schedule body 不改变 legacy 成功形。
- `tests/e2e/test_deepseek_retired.py` 在 T05 回归中通过；全量 250 passed 包含该文件。
- 未触碰 `Test3/data/`、密钥、现有服务或运行数据；未 push、未创建 PR、未调用真实模型。

剩余阻塞：

1. **BLOCKED**：缺 C.7 `github_write` 授权句，无法执行真实 push / `gh pr create`；`MV-04` 未完成。
2. P1-T06 的 granted 执行目前只在任务携带 `granted_execution`（writes + command）计划时启用；完整 DAG 连续执行与缺陷回流在 P5 实现，本阶段未越界。
3. 若后续授权真实 PR，必须使用 C.7 原句与独立 feature 分支，仍禁止 merge / deploy / push base。

## 提交记录与最终回归（本地分支）

```text
05d226b P1-T01 add grant_stale_reason subset-safe policy
187fcf1 P1-T02 add ExecutionGrant schema, SQLite table and repo
728852c P1-T03 add execution-grant HTTP with server-owned profile
47bc415 P1-T04 guard granted_v1 schedule scope without legacy change
7d3e44f P1-T05 record approved baseline hashes and refresh grants
ad7c90e P1-T06 run granted tasks in isolated worktree with evidence
140d1cc P1-T07 add idempotent git/PR adapters with BLOCKED record
f079ae6 style(test3): sort execution-grant alembic test imports
2902308 P1-T03 return ErrorBody for unknown run on grant list
```

最终后端全量（非 live）：

```text
$ cd Test3/backend && uv run pytest -m "not live"
250 passed, 2 deselected in 22.81s
```

`2 deselected` 为 `@pytest.mark.live`（真实模型 / 真实 PR 探测），本轮未运行。

本报告附注 commit 仅登记上述 SHA 与输出，不改变业务代码。P1 本地部分到此停止；**未进入 P2**，未 push，未创建真实 PR。

# P1 审查修复 · F-04 服务端生产启用与执行计划物化

- 日期：2026-11-19（Asia/Singapore）
- 前置：F-02（SQLite 权威 profile/hashes）、F-03（Alembic 单一权威）已完成。
- 本任务结束后停止第一批；未启动服务、未调用真实模型/网络、未触碰用户实际业务库。

## 1. 选定的生产启用路径

**专用服务端端点**（不是测试 setter）：

```text
POST /api/runs/{run_id}/execution-profile
GET  /api/runs/{run_id}/execution-profile
```

请求体只接受 `granted_v1`：

```json
{
  "execution_profile": "granted_v1",
  "approved_baseline_hashes": {"PLAN": "..."},
  "approved_plan_hash": "可选，必须与当前 PLAN artifact 一致",
  "allowed_tool_refs": ["python -m pytest"]
}
```

- `execution_profile="legacy"` 被 Pydantic `Literal` 拒绝（400 `validation_error`），不存在降级路由。
- legacy run 仍不能通过 `POST /execution-grants` 自升级（403 `profile_not_granted_v1`）。
- 路由调用 `Workbench.enable_granted_execution()`；该函数校验：
  - run 存在；
  - hashes 非空，且与 run 当前 approved baseline 一致（否则 409 `baseline_stale`）；
  - `approved_plan_hash`（若提供）必须等于当前 PLAN 的 sha256；
  - 通过 `persist_run_execution_state()` 写入 SQLite `run_execution_state`，再更新内存并落快照。
- 该端点只负责“启用 + 持久化”，不设置任何执行安全标志。
- P1 应用目前没有独立的管理员认证层；此端点是服务端唯一启用入口，客户端只能提交 `granted_v1`
  与已批准 hashes，不能提交 legacy、不能设置安全标志。管理员鉴权属于后续安全边界工作。

## 2. 生产物化

`Workbench._materialize_tasks()` 在 run 为 `granted_v1` 时，为每个任务生成
`task["granted_execution"]`，字段来源：

| 字段 | 来源 |
|---|---|
| `execution_profile` | 固定 `granted_v1` |
| `approved_plan_hash` | 当前 PLAN artifact 的 sha256 |
| `approved_baseline_hashes` | SQLite / run 当前批准基线 |
| `task_codes` | 匹配的 active Grant scope；尚无 Grant 时为当前 task code |
| `grant_id` / `feature_branch` | 匹配的 active Grant；无 Grant 时为空 |
| `write_set` | TaskCard.write_set |
| `command` | TaskCard 第一条 acceptance command；无则 profile test_command |
| `tool_refs` | Grant.allowed_tool_refs（无 Grant 时为空，执行期再与全局策略求交） |
| `writes` | 保留既有内容；生产物化初始为空，等待 worker 产出 |
| `source` | `server_materialize_tasks` |

- `add_grant()` 会把 Grant 的 `grant_id`、scope、tool refs、feature branch、hashes 重新绑定到范围内任务。
- 未启用 granted 的普通 `create_run()` 物化后没有 `granted_execution`（测试覆盖）。
- 重新确认同一计划（fingerprint 相同）时，也会重新附加/刷新生产 spec，不会留下旧 scope。

## 3. 执行安全门（第一批停止点）

`Workbench.execution_safety_ready` 是服务端属性，初始 `False`，无 HTTP 入口、请求体或工具可设置。

`_require_execution_safety()` 在以下真实入口调用：

- `execute_task()`（直接执行、retry、缺陷递归最终都回到这里）；
- `_accept_review_merge()`（review/merge 副作用前）；
- `_submit_takeover()`（takeover submit 的 review/merge 前）。

granted run 在标志为 false 时抛：

```text
GrantRejected(category="execution_safety_not_ready", status_code=409)
```

因此第一批不会把新 granted 入口接到旧的 legacy `run_tool_agent()` / 本地自动 merge 链。
`tests/e2e/test_granted_v1_sandbox_write.py` 已改为走生产 enable/materialize，并断言：

- `execution_safety_not_ready` 拒绝；
- 不创建 granted worktree、不写外部文件；
- retry 同样被拒绝且任务不为 done。

F-05 会在统一 Grant 边界完成后替换此临时总闸；F-06 的隔离预检通过前不得把标志置真。

## 4. 测试

```text
cd Test3/backend && .venv/bin/python -m pytest \
  tests/integration/test_p1_rev08_production_enable_path.py \
  tests/integration/test_execution_grant_api.py \
  tests/e2e/test_granted_v1_sandbox_write.py -v
# 14 passed
```

覆盖：

- 只走生产 enable + materialize，得到非空 spec（plan hash / scope / command / tool refs）；
- 建 Grant 后 spec 绑定 `grant_id`；
- 端点启用后进程重启仍为 `granted_v1`（依赖 F-02 SQLite）；
- 客户端提交 legacy 仍 4xx；
- legacy run POST Grant 仍 403；
- 普通 run 物化不带假 `granted_execution`；
- granted 执行/retry 在安全门未就绪时被拒绝。

OpenAPI 结构快照已用 `UPDATE_OPENAPI_SNAPSHOT=1` 重生成（新增两条路由）。

全量非 live：

```text
9 failed, 272 passed, 2 deselected
```

剩余 9 条均为后续批次尚未修复的 F-01 红灯：REV-02（2）、REV-03（2）、REV-06（2）、
REV-07（2）、REV-09（1）。REV-01/04/05/08 已在本批转绿。

收尾加固：`_restore_execution_profile()` 会把 `conflict` 标记保留到下一次恢复（不会第二次启动自动
“愈合”）；`_refresh_grant_statuses()` 在人批更新 baseline hashes 后同步写 SQLite，避免制造
SQLite/快照假冲突；`_run_regression()` 也经过同一个安全门。

## 5. 边界

- 未启用真实任务自动执行；`execution_safety_ready` 仍为 false。
- 未做 P2/P5 DAG、未做 Git 授权/仓库绑定/PR 幂等（F-09…F-11）。
- 真实 PR 记录仍为 BLOCKED；修复测试全绿不等于首版真实 PR 完成。
- 未对用户实际 `Test3/data/test3.db` 执行迁移或写入。
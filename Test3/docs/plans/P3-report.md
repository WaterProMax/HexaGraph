# P3 阶段报告（T01–T05）

本报告覆盖 P3 记忆域的 T01–T05。所有测试命令均带 `-o addopts=''`，迁移统一经 `upgrade_database` 执行，不使用 `create_all`。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | `4cd60d0b3b105f2a3ba242f45d61c652baccf888` | `feat(test3): P3-T01 add memory store and memory_records` |
| T02 | `92726449a769f60f56a10ecdc563b173045a3439` | `feat(test3): P3-T02 isolate memory access after membership removal` |
| T03 | `5af35a447da46effd8c33237ed0bece16c4b56c5` | `feat(test3): P3-T03 publish supersede and memory optimistic lock` |
| T04 | `ec09119adc468639db0b49358abf30fbcf5f931e` | `feat(test3): P3-T04 add memory HTTP and call_agent injection` |
| T05 | 本报告所在提交 | `docs(test3): P3-T05 exit report and OpenAPI snapshot` |

T05 的完整 SHA 由本文件内容决定，无法在提交前写入自身；最终 SHA 见交付汇报或 `git log -1 --format=%H`，未使用 amend。

## 新增文件总表

- `app/schemas/memory.py`
- `app/memory/__init__.py`
- `app/memory/store.py`
- `app/memory/access.py`
- `app/memory/promotion.py`
- `app/memory/injection.py`
- `app/api/routes_memory.py`
- `alembic/versions/0008_memory_records.py`
- `tests/unit/test_memory_store.py`
- `tests/unit/test_memory_access.py`
- `tests/unit/test_memory_promotion.py`
- `tests/unit/test_memory_injection.py`
- `tests/integration/test_memory_member_removed.py`
- `tests/integration/test_memory_api.py`

## 修改文件总表

- `app/storage/models.py`（`MemoryRecordRow`、`ix_memory_owner`）
- `app/main.py`（挂载 memory router，prefix=/api）
- `app/agents/runtime.py`（`call_agent` 新增 `project_id` / `memory_slot` 与记忆块）
- `app/memory/store.py`（`publish_version` / `supersede_version`）
- `app/memory/promotion.py`（expected_version 语义修正）
- `tests/integration/snapshots/openapi_structure.json`（P3 记忆路由）
- `Test3/docs/API.md`（P2 标题空行修复 + P3 记忆路由）
- `Test3/docs/plans/P3-report.md`

## T01 · memory_records 与 MemoryStore

- 时间：2026-11-20 10:48 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_memory_store.py -v`
- 退出码：0
- 计数：9 passed
- 回归：`tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 27 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0（既有 0005 表达式索引 SAWarning）

### 触及文件

- `app/schemas/memory.py`（NEW）
- `app/memory/__init__.py`（NEW）
- `app/memory/store.py`（NEW）
- `alembic/versions/0008_memory_records.py`（NEW）
- `tests/unit/test_memory_store.py`（NEW）
- `app/storage/models.py`（MODIFY：`MemoryRecordRow` 与 `ix_memory_owner`）
- `Test3/docs/plans/P3-report.md`（NEW）

### 实现要点

- `(mem_id, version)` 复合主键；`create` 生成 uuid、version=1、status=pending。
- 旧 version body 由 SQLite 触发器 `trg_memory_body_immutable` 保护；直接 SQL UPDATE v1 body 会 abort，测试覆盖。
- `append_version` 先以 no-op `UPDATE` 取写锁，再校验 expected_version；并发两个 append 只有一个成功，版本线为 1/2。
- 密钥扫描覆盖嵌套 dict/list、大小写不敏感字段名（`api_key` / `password` / `secret` / `token` / `access_token` / `*_api_key`）与 `sk-` 前缀字符串，显式放行 `token_budget`。
- 只写 SQLite，不写 JSONL；`run_id` 只放 payload。

### 契约扩展登记

- `MemoryRecord.promoted_by` / `promoted_at`：T03 publish 时记录人工晋升者与时间，默认 `None`。

## T02 · 越权隔离与撤成员保留个人记忆历史

- 时间：2026-11-20 10:49 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_memory_access.py tests/integration/test_memory_member_removed.py -v`
- 退出码：0
- 计数：7 passed（单元 5 / 集成 2）
- 回归：`tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 27 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0

### 触及文件

- `app/memory/access.py`（NEW）
- `tests/unit/test_memory_access.py`（NEW）
- `tests/integration/test_memory_member_removed.py`（NEW）
- `Test3/docs/plans/P3-report.md`（MODIFY）

### 实现要点

- `is_project_member` 直接查 P2 `ProjectMembershipRow`，没有第二套成员表。
- `private` / `run` 仅 owner 读写；`project` 仅当前项目成员读写；`run` 默认 fail-closed，不广播给任意 Bot。
- `MemoryAccessService.get` 显式拒绝他人 private 与非成员 project；`list_visible` 只返回 actor 可见的每个 mem 最新版本。
- 移出成员只删除 `project_memberships` 行；私有记忆 v1/v2 仍可读，body 与移出前一致，`memory_records` 行数不变。
- 集成测试并发读取私有历史/项目记忆与 DELETE membership，读取不会 500；最终 B1 失去项目可见性，B2 仍可读。
- `GET /api/bots/{B1}` 在移出后仍 200。

## T03 · 人工晋升、supersede 与乐观锁

- 时间：2026-11-20 10:49 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_memory_promotion.py tests/unit/test_memory_store.py -v`
- 退出码：0
- 计数：18 passed（promotion 9 / store 9）
- 回归：`tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 27 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0

### 触及文件

- `app/memory/promotion.py`（NEW）
- `tests/unit/test_memory_promotion.py`（NEW）
- `app/memory/store.py`（MODIFY：新增 `publish_version` / `supersede_version` 原子方法）
- `Test3/docs/plans/P3-report.md`（MODIFY）

### 实现要点

- 仅 `project` 可见性可 publish；`private` / `run` 抛 `VisibilityNotProject`。
- publish / supersede 复用 T02 `is_project_member`，非成员抛 `MemoryForbidden`。
- publish 只在当前 version 为 `pending` 时成功；写 `promoted_by=actor`、`promoted_at`，body 不变；同版本再次 publish 抛 `MemoryVersionConflict`。
- supersede 先把旧 version 置为 `superseded`（body 不变），再插入 N+1 `pending` 新版本；新 body 走密钥扫描；已 superseded 或 expected 不符抛 `MemoryVersionConflict`。
- 所有状态变更先以 no-op `UPDATE` 取 SQLite 写锁；并发 publish 一成一冲突，并发 supersede 只产生一条新版本。
- 契约扩展 `promoted_by` / `promoted_at` 已在 T01 登记，本卡实现写入。

## T04 · 记忆 HTTP 与 call_agent 注入槽

- 时间：2026-11-20 10:55 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/integration/test_memory_api.py tests/unit/test_memory_injection.py tests/integration/test_memory_member_removed.py tests/unit/test_memory_promotion.py -q`
- 退出码：0
- 计数：28 passed（memory_api 10 / injection 5 / member_removed 3 / promotion 10）
- 回归：`tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 27 passed，退出码 0
- API 契约：`tests/integration/test_api_contract.py` → 28 passed，退出码 0
- OpenAPI：`UPDATE_OPENAPI_SNAPSHOT=1 ...` → 1 passed；不带变量复跑 → 1 passed

### 触及文件

- `app/api/routes_memory.py`（NEW）
- `app/memory/injection.py`（NEW）
- `tests/integration/test_memory_api.py`（NEW）
- `tests/unit/test_memory_injection.py`（NEW）
- `app/main.py`（MODIFY：挂载 memory router，prefix=/api）
- `app/agents/runtime.py`（MODIFY：`call_agent` 新增 `project_id` / `memory_slot` 并注入记忆块）
- `app/memory/promotion.py`（MODIFY：expected_version 语义修正）
- `tests/integration/test_memory_member_removed.py`（MODIFY：补 HTTP 撤成员场景）
- `tests/unit/test_memory_promotion.py`（MODIFY：补 expected=99 -> conflict 单测）
- `tests/integration/snapshots/openapi_structure.json`（MODIFY）
- `Test3/docs/API.md`（MODIFY）
- `Test3/docs/plans/P3-report.md`（MODIFY）

### 实现要点

- 所有记忆路由要求 `X-Bot-Id`；缺失/空白 400，actor 不存在 404；body 不再作为调用者身份。
- 请求体与查询参数手工校验，失败 400；错误体统一 `{"error_category","detail"}`。
- 三层可见性：private/run 仅 owner；project 仅成员；无 global。
- `/publish` 与 `/supersede` 使用 expected_version 乐观锁；publish 仅 project，supersede 生成 N+1 pending 并保留旧 body。
- `build_memory_slot` 注入 actor private、所属项目 published、actor run；逐项密钥扫描并在序列化后再查 `sk-`。
- `call_agent` 先解析冻结 pin，再构建记忆槽；`bot_id=None` 不读 pin/bots/记忆；显式 `memory_slot` 可注入。
- T03 语义修正后，任何错误的 expected_version（包括库中不存在的 99）都返回 409 `memory_version_conflict`，不再变成 404。

### 契约扩展登记

- `MemoryRecord.run_id` 仅存 payload。
- `promoted_by` / `promoted_at` 记录人工晋升者与时间。
- `call_agent` 新增 `project_id` / `memory_slot`。
- `MemoryStore.latest_only`、`publish_version` / `supersede_version`、`app/memory/injection.py`。

## T05 · 出口验证

### A · P3 测试集

- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -v tests/unit/test_memory_store.py tests/unit/test_memory_access.py tests/unit/test_memory_promotion.py tests/unit/test_memory_injection.py tests/integration/test_memory_member_removed.py tests/integration/test_memory_api.py`
- 结果：**42 passed**，退出码 0（store 9 / access 5 / promotion 10 / injection 5 / member_removed 3 / memory_api 10）

### B · P2 回归、隔离、契约与全量

- 镜像检查：`docker image inspect test3-isolation-local:pytest` 成功，ID `sha256:af6493938f5df1f06ca97f63bac9e0eebd9119185183dbc25cc4cc7143ef72cd`；无需 retag，未 pull/build。
- P2 回归：技能/Bot/成员/pin 7 个文件 → **50 passed**，退出码 0。
- 隔离相关 8 个文件（`TEST3_ISOLATION_IMAGE=test3-isolation-local:pytest`）→ **70 passed, 1 skipped**，退出码 0。
- `tests/integration/test_api_contract.py -v` → **28 passed**，退出码 0。
- 全量非 live：`pytest -o addopts='' -m 'not live'` → **508 passed, 1 skipped, 2 deselected**，退出码 0，**0 failed**（P2 466 + P3 42）。保留 2 条 warning：既有 0005 表达式索引 SAWarning，以及一次非致命的 aiosqlite 线程告警。

### C · 无镜像 fail-closed

- 命令：`env -u TEST3_ISOLATION_IMAGE .venv/bin/python -m pytest -o addopts='' -m 'not live' -rs tests/unit/test_p1_rev03_isolation_preflight.py`
- 结果：**8 passed, 1 skipped**，退出码 0。
- skip 原因：`no isolation backend on this host: isolation image is not present locally: python:3.11-slim (no pull attempted)`。
- 跑后 `docker images python:3.11-slim -q` 为空，确认未拉取。

### 契约核对

- **追加写不改旧 body**：SQLite 触发器 `trg_memory_body_immutable` 生效；直接 SQL UPDATE v1 body 的测试失败为预期。
- **三层可见性**：private/run 仅 owner，project 仅成员，无 global；`run_id` 不塞进 `project_id`。
- **撤成员**：只删 `project_memberships` 行；private/history 保留且 body 不变；该 Bot 不能再读项目记忆，仍在项目的 Bot 可读；`memory_records` 行数不减；`GET /api/bots/{id}` 仍 200。
- **publish/supersede/乐观锁**：publish 仅 project 且记录 `promoted_by`/`promoted_at`；supersede 旧版 superseded、body 不变，新版本 pending；并发 publish/supersede 均一成一冲突；错误 expected_version 为 409。
- **注入隔离**：`build_memory_slot` 不返回他人 private/run，不返回非成员项目记忆；逐项扫描密钥并丢弃脏记录；`call_agent` 先解析冻结 pin，再注入，记忆槽不会绕过 pin。
- **无真实付费 API**：P3 测试全部使用 scripted / 本地 SQLite；scripted 路径外部 HTTP 调用计数为 0。
- **OpenAPI**：仅新增 P3 记忆路由，未删除既有路径；`UPDATE_OPENAPI_SNAPSHOT=1` 后复跑 1 passed。
- **前端/P4**：未改前端；未新增讨论协议、独立提案、异议、交叉评审、规格门、执行 DAG 或前端工作台；未改既有 `app/discussion/` 状态机。
- **品牌黑名单**：未新增任何“模型/provider 等于某品牌就拒绝”的逻辑。

### 明确声明

- 未进入 P4。
- `execution_safety_ready` 仍为 `False`，唯一赋值点仍是 `app/services/runtime.py:218`。
- `Test3/docs/plans/p1-pr-record.json` 仍为 `status=BLOCKED`、`github_pr_url=null`。
- 未 push、未建远程分支、未开 PR。
- 未安装/启动 Docker，未 pull、未 build；本次镜像 inspect 成功，未执行 retag。
- 原 5 个未跟踪文件（`P1-review.md`、`P0-report.md`、`baseline-lock.json`、`decommission-target-state.json`、`p0-t01-cmd.log`）仍未纳入任何提交。

### 人工验收提醒

- 缺 `X-Bot-Id` 调任意 `/api/memory/...` 应 400 `validation_error`。
- 再点一次 `POST /api/projects/x/bots`：应 404/405，且 `bots` 表零新增。
- 用两个 Bot 验证 private/run 互不可见、project 仅成员可见；移出成员后项目记忆 403，但 private 历史仍可读。
- 用同一 expected_version 并发 publish/supersede，应一方 200、一方 409。
- 检查 `git log --oneline -6` 应看到 T01–T05 五个 P3 提交，工作区仅剩上述 5 个既有未跟踪文件。
# P3 阶段报告（T01–T03）

本报告按卡追加。所有测试命令均带 `-o addopts=''`，迁移统一经 `upgrade_database` 执行。

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

- `MemoryRecord.promoted_by` / `promoted_at`：T03 publish 时记录人工晋升者与时间，默认 `None`。## T02 · 越权隔离与撤成员保留个人记忆历史

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
- `GET /api/bots/{B1}` 在移出后仍 200。## T03 · 人工晋升、supersede 与乐观锁

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
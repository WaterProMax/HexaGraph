# P4 阶段报告（T01–T03）

本报告按卡追加。所有测试命令均带 `-o addopts=''`，迁移统一经 `upgrade_database` 执行，不使用 `create_all`。

## T01 · 会话状态机与 Leader 动态编组

- 时间：2026-11-20 11:21 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_discussion_steward.py tests/integration/test_discussion_session_api.py -v`
- 退出码：0
- 计数：14 passed（单元 7 / 集成 7）
- 回归：`tests/unit/test_discussion_rules.py tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 40 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0（既有 0005 表达式索引 SAWarning）

### 触及文件

- `app/discussion/models.py`（NEW）
- `app/discussion/session_store.py`（NEW）
- `app/leader/__init__.py`（NEW）
- `app/leader/steward.py`（NEW）
- `app/api/routes_discussion.py`（NEW）
- `alembic/versions/0009_discussion.py`（NEW）
- `tests/unit/test_discussion_steward.py`（NEW）
- `tests/integration/test_discussion_session_api.py`（NEW）
- `app/storage/models.py`（MODIFY：三张 discussion 表 ORM）
- `app/main.py`（MODIFY：挂载 discussion router，prefix=/api）
- `Test3/docs/plans/P4-report.md`（NEW）

### 实现要点

- `DiscussionSession` / `DiscussionRoundState` 等类型在 `app/discussion/models.py`；`DiscussionRoundState` 不含 score / score_delta / variance。
- `DiscussionSessionStore` 的 `status` 列与 `payload.status` 同步；`get_locked` 用 no-op `UPDATE` 取 SQLite 写锁。
- `DiscussionSteward.create_session` 动态查 `ProjectMembershipRow`：leader 必须 `is_leader==1`，participant 必须都是项目成员；参与者去重保序，空列表拒绝。
- `requirement_snapshot_hash = hash_artifact(requirement_snapshot)`；默认 `max_rounds=3`；初始 `draft` / `current_round=0`。
- `group` actor 必须是 leader；允许 `draft`/`grouping`；传入列表则重新校验并替换；并发 group 通过写锁串行，最终是某一次完整列表。
- 未修改 `app/discussion/engine.py`、`rules.py`、`__init__.py`，legacy `GET /api/runs/{run_id}/discussion` 零行为变化；未写 `discussion_msg`。
- 未更新 OpenAPI 快照/API.md（按 P4 约定留到后续统一）。
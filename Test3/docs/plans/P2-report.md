# P2 阶段报告（T01–T04）

本报告按卡追加。所有测试命令均带 `-o addopts=''`，并显式设置
`TEST3_ISOLATION_IMAGE=test3-isolation-local:pytest`（不执行 docker pull/build）。

## T01 · Skill 定义库

- 时间：2026-11-20 10:20 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_skill_registry.py tests/integration/test_skills_api.py -v`
- 退出码：0
- 计数：11 passed（单元 6 / 集成 5）
- 回归：`tests/unit/test_p1_f08_tool_authorization.py tests/unit/test_tools_llm_agents.py` → 27 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0

### 触及文件

- `app/schemas/skill_definition.py`（NEW）
- `app/skills/__init__.py`（NEW）
- `app/skills/registry.py`（NEW）
- `app/api/routes_skills.py`（NEW）
- `alembic/versions/0004_skill_definitions.py`（NEW）
- `tests/unit/test_skill_registry.py`（NEW）
- `tests/integration/test_skills_api.py`（NEW）
- `app/main.py`（MODIFY：挂载 skills router，prefix=/api）
- `app/execution/tool_policy.py`（MODIFY：仅新增 `effective_tools`，`authorize_granted_command` 未改）
- `app/storage/models.py`（MODIFY：新增 `SkillDefinitionRow`，供 Alembic `Base.metadata` 与旧 `create_all` 测试路径共用）
- `docs/plans/P2-report.md`（NEW）

### 偏差与说明

- T01 路径清单未列 `app/storage/models.py`，但项目约定 ORM 行类集中在该文件；为保证 Alembic 元数据与 `create_all` 测试路径一致，本卡加入 `SkillDefinitionRow`。
- `effective_tools` 对空列表返回空集，不把 `description_md` 中的工具名当作授权。
- 本卡未改 `authorize_granted_command`，既有 F-08 27 项回归通过。## T02 · Bot 持久化与独立 Model / Skill pin

- 时间：2026-11-20 10:21 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_bot_registry.py -v`
- 退出码：0
- 计数：8 passed
- 回归：`tests/unit/test_p1_f08_tool_authorization.py tests/unit/test_tools_llm_agents.py` → 27 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0（SQLite 表达式索引反射告警 1 条，不影响结果）

### 触及文件

- `app/schemas/bot.py`（NEW）
- `app/bots/__init__.py`（NEW）
- `app/bots/registry.py`（NEW）
- `alembic/versions/0005_bots_and_pins.py`（NEW）
- `tests/unit/test_bot_registry.py`（NEW）
- `app/storage/models.py`（MODIFY：`BotRow`、`BotPinRevisionRow`、大小写不敏感唯一索引）
- `docs/plans/P2-report.md`（MODIFY）

### 实现要点

- `display_name` 大小写不敏感唯一：`uq_bots_display_name_ci` 表达式唯一索引兜底，`IntegrityError` 映射为 `BotNameConflict`。
- pin revision 使用单条 `INSERT ... SELECT COALESCE(MAX(revision),0)+1` 原子分配；并发更新先以 no-op `UPDATE` 取得 SQLite 写锁再读取，避免读快照升级冲突。
- 仅 `model` / `provider_ref` / `skill_bindings` 实际变化时追加 pin；只改 `display_name` 不新增 pin。
- 归档后行与 pin 历史保留；重复归档 `BotAlreadyArchived`，归档后改绑定 `BotArchived`。
- `secret_ref` 仅保存环境变量名；测试在环境中放入 `sk-leak` 后确认表 `payload` 不含该值。
- 未写死任何模型品牌拒绝逻辑。## T03 · 全局 Bot HTTP

- 时间：2026-11-20 10:21 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/integration/test_bots_api.py tests/unit/test_bot_registry.py -v`
- 退出码：0
- 计数：17 passed（集成 9 / 单元 8）
- 回归：`tests/unit/test_p1_f08_tool_authorization.py tests/unit/test_tools_llm_agents.py` → 27 passed，退出码 0

### 触及文件

- `app/api/routes_bots.py`（NEW）
- `tests/integration/test_bots_api.py`（NEW）
- `app/main.py`（MODIFY：挂载 bots router，prefix=/api）
- `docs/plans/P2-report.md`（MODIFY）

### 契约与扩展

- `POST /api/bots` 服务器生成 `bot_id`；返回 201。
- `GET /api/bots?status=active|archived`；非法 status 返回 400 `validation_error`。
- `GET /api/bots/{bot_id}` 404 `bot_not_found`；`PATCH` 支持 `pin_revision` 只读扩展字段。
- `POST /api/bots/{bot_id}/archive` 返回 `{"bot_id", "status": "archived"}`；重复归档 409 `bot_already_archived`。
- `PATCH` 已归档 Bot 的 `model` / `provider_ref` / `skill_bindings` 返回 409 `bot_archived`。
- 未注册 `POST /api/projects/{project_id}/bots`；自然 404，测试断言 `bots` 行数不变。
- 未新增顶级 Model CRUD 路由，未改 `GET/PUT /api/config/models`，未改前端。## T04 · 项目成员 M:N、唯一 Leader、移出保留 Bot

- 时间：2026-11-20 10:22 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_membership.py tests/integration/test_memberships_api.py -v`
- 退出码：0
- 计数：15 passed（单元 8 / 集成 7）
- 回归：`tests/unit/test_p1_f08_tool_authorization.py tests/unit/test_tools_llm_agents.py` → 27 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0

### 触及文件

- `app/projects/__init__.py`（NEW）
- `app/projects/membership.py`（NEW：`MembershipService`、`ProjectMembership`、`MembershipCreate` 与错误类型）
- `app/api/routes_memberships.py`（NEW）
- `alembic/versions/0006_project_memberships.py`（NEW）
- `tests/unit/test_membership.py`（NEW）
- `tests/integration/test_memberships_api.py`（NEW）
- `app/main.py`（MODIFY：挂载 memberships router，prefix=/api）
- `app/storage/models.py`（MODIFY：`ProjectMembershipRow`、`uq_project_one_leader` 部分唯一索引）
- `docs/plans/P2-report.md`（MODIFY）

### 实现要点

- 项目存在判定与 `POST /api/projects/{project_id}/runs` 一致：`project_id not in bench.projects` → 404 `project_not_found`。
- `project_memberships` 只对 `bots(bot_id)` 建外键，未给内存项目表加外键。
- 同一项目至多一个 `is_leader=1`：`uq_project_one_leader ... WHERE is_leader = 1` 部分唯一索引真正生效；并发写入时先以 no-op `UPDATE` 取 SQLite 写锁，`IntegrityError` 按索引/列名映射为 `leader_already_set` 或 `membership_exists`。
- 同一 Bot 可加入多个项目；`DELETE` 只删除该项目 join 行，不删除 `bots` 行或 pin 历史。
- 归档 Bot 加入成员返回 403 `bot_archived`；缺失关系 404 `membership_not_found`。
- 未创建 T05 的 `run_bot_pin_snapshots`，未进入记忆/讨论/DAG/前端工作台。
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
- 未创建 T05 的 `run_bot_pin_snapshots`，未进入记忆/讨论/DAG/前端工作台。## T05 · call_agent / Gateway 使用 Bot pin 快照

- 时间：2026-11-20 10:26 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_bot_pin_snapshot.py -v`
- 退出码：0
- 计数：7 passed
- 回归：`tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 27 passed，退出码 0
- 附加回归：`tests/unit/test_error_taxonomy.py tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 26 passed，退出码 0

### 触及文件

- `app/bots/snapshot.py`（NEW）
- `alembic/versions/0007_run_bot_pin_snapshots.py`（NEW）
- `tests/unit/test_bot_pin_snapshot.py`（NEW）
- `app/agents/runtime.py`（MODIFY：`call_agent` 新增 `bot_id` / `run_id`，仅 bot_id 非空时读取冻结快照）
- `app/llm/gateway.py`（MODIFY：`complete` / `_complete_with_retry` 接受 `model` / `provider_ref`；model 覆盖槽位默认值；provider_ref 只记录不转发）
- `app/storage/models.py`（MODIFY：`RunBotPinSnapshotRow`）
- `docs/plans/P2-report.md`（MODIFY）

### 实现要点

- `freeze_bot_pins` 按 `(run_id, bot_id)` 写入当时 `latest_pin` 的 `revision/model/provider_ref/skill_bindings`；已存在则跳过，并用 `INSERT OR IGNORE` 保证并发下也绝不覆盖。
- `get_frozen_pin` 缺失时抛 `BotPinError("pin_snapshot_missing")`，不回退 latest pin。
- `get_frozen_skill` 只按冻结绑定中的 `pinned_version` 读取 `skill_definitions`；未绑定抛 `skill_not_bound`，版本行缺失抛 `skill_version_missing`，不使用更高版本。
- `call_agent(bot_id=...)` 必须同时给 `run_id`，否则 `run_id_required`；使用 `gateway.data_dir/test3.db` 读取快照，并把冻结的 model/provider_ref 传给 Gateway。
- `bot_id=None` 时不导入/调用快照读取路径，保持原槽位与 scripted 行为。
- Gateway 不把 `provider_ref` 传给 provider（避免未知关键字）；scripted/replay/DashScope/通用 OpenAI-compatible 路径未改，未启用 `model_live`，无品牌黑名单。
- 未创建/修改 T06 的 OpenAPI 快照与 `docs/API.md`。## T06 · 出口：回归、报告、停止

- 时间：2026-11-20 10:33 CST

### OpenAPI 快照与 API 文档

- `UPDATE_OPENAPI_SNAPSHOT=1 .venv/bin/python -m pytest -o addopts='' tests/integration/test_api_contract.py::test_openapi_structure_matches_snapshot -q` → 1 passed，退出码 0
- 再次不带更新变量运行同一命令 → 1 passed，退出码 0
- `tests/integration/snapshots/openapi_structure.json` 增加 P2 的 11 条路由（skills / bots / memberships），无既有条目被删除。
- `Test3/docs/API.md` 末尾追加“P2 新增路由”章节：路由表、`{"error_category","detail"}` 错误体、P2 错误码、`pin_revision` 只读扩展与无需项目下建 Bot 的说明；既有内容未改写。

### 六个提交

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | `e1ef5ceed3c8f94f17adec294ff54c96201869ae` | `feat(test3): P2-T01 add versioned skill definition registry` |
| T02 | `c82cedce8ab0da4795d3f03299f00f1f86f32f59` | `feat(test3): P2-T02 persist bots and pin revisions` |
| T03 | `1d8d979c8becd37fe1aed65823a5c8568b2330b2` | `feat(test3): P2-T03 add global bot HTTP routes` |
| T04 | `8552420214d1648af6e7fdfa5bc5b3959a482a33` | `feat(test3): P2-T04 add project memberships and unique leader` |
| T05 | `9671029b47e41f8f9cfa6265fd1cc8372b781d82` | `feat(test3): P2-T05 freeze bot pin snapshots for call_agent` |
| T06 | 本报告所在提交 | `docs(test3): P2-T06 exit report and OpenAPI snapshot` |

> 自引用说明：T06 的完整 SHA 由本文件内容决定，无法在提交前写入自身；最终 SHA 见本次交付汇报或 `git log -1 --format=%H`，未使用 amend。

### T06 触及文件

- `Test3/docs/plans/P2-report.md`（MODIFY）
- `Test3/backend/tests/integration/snapshots/openapi_structure.json`（MODIFY）
- `Test3/docs/API.md`（MODIFY）

### 新增文件总表（T01–T06）

- `app/schemas/skill_definition.py`
- `app/skills/__init__.py`
- `app/skills/registry.py`
- `app/api/routes_skills.py`
- `alembic/versions/0004_skill_definitions.py`
- `tests/unit/test_skill_registry.py`
- `tests/integration/test_skills_api.py`
- `app/schemas/bot.py`
- `app/bots/__init__.py`
- `app/bots/registry.py`
- `alembic/versions/0005_bots_and_pins.py`
- `tests/unit/test_bot_registry.py`
- `app/api/routes_bots.py`
- `tests/integration/test_bots_api.py`
- `app/projects/__init__.py`
- `app/projects/membership.py`
- `alembic/versions/0006_project_memberships.py`
- `tests/unit/test_membership.py`
- `tests/integration/test_memberships_api.py`
- `app/api/routes_memberships.py`
- `app/bots/snapshot.py`
- `alembic/versions/0007_run_bot_pin_snapshots.py`
- `tests/unit/test_bot_pin_snapshot.py`

### 修改文件总表（T01–T06）

- `app/main.py`（挂载 skills / bots / memberships router）
- `app/execution/tool_policy.py`（新增 `effective_tools`，未改 `authorize_granted_command`）
- `app/storage/models.py`（`SkillDefinitionRow`、`BotRow` / `BotPinRevisionRow`、`ProjectMembershipRow`、`RunBotPinSnapshotRow` 与索引）
- `app/agents/runtime.py`（`call_agent` 可选用 `bot_id` / `run_id`）
- `app/llm/gateway.py`（`model` / `provider_ref` 可选参数）
- `docs/plans/P2-report.md`
- `tests/integration/snapshots/openapi_structure.json`
- `docs/API.md`

### 每卡测试命令与实际结果

| 卡片 | 命令摘要 | 结果 | 退出码 |
|---|---|---|---|
| T01 | `pytest -o addopts='' tests/unit/test_skill_registry.py tests/integration/test_skills_api.py -v` | 11 passed | 0 |
| T02 | `pytest -o addopts='' tests/unit/test_bot_registry.py -v` | 8 passed | 0 |
| T03 | `pytest -o addopts='' tests/integration/test_bots_api.py tests/unit/test_bot_registry.py -v` | 17 passed | 0 |
| T04 | `pytest -o addopts='' tests/unit/test_membership.py tests/integration/test_memberships_api.py -v` | 15 passed | 0 |
| T05 | `pytest -o addopts='' tests/unit/test_bot_pin_snapshot.py -v` | 7 passed | 0 |
| 每卡回归 | `pytest -o addopts='' tests/unit/test_p1_f08_tool_authorization.py tests/unit/test_tools_llm_agents.py` | 每卡 27 passed | 0 |
| T05 附加 | `pytest -o addopts='' tests/unit/test_error_taxonomy.py tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` | 26 passed（1 SAWarning） | 0 |

### T06 出口命令

- A：`pytest -o addopts='' -v` 六个 P2 测试文件 + `test_bot_pin_snapshot.py` → **50 passed**，退出码 0（1 条非致命 aiosqlite 线程告警，未影响结果）。
- 镜像检查：`docker image inspect test3-isolation-local:pytest` 成功，镜像 ID `sha256:af6493938f5df1f06ca97f63bac9e0eebd9119185183dbc25cc4cc7143ef72cd`；`docker images` 可见同一 ID。无需 `docker tag` 重挂，未执行任何 pull/build/安装/启动。
- B 隔离子集：`export TEST3_ISOLATION_IMAGE=test3-isolation-local:pytest` 后运行 8 个指定测试文件 → **70 passed, 1 skipped**，退出码 0。
- B 全量非 live：`pytest -o addopts='' -m 'not live'` → **466 passed, 1 skipped, 2 deselected**，退出码 0，**0 failed**。skip 为 `test_worker_fails_closed_without_backend` 所在机器条件跳过项；2 deselected 为 live 标记。
- C：`env -u TEST3_ISOLATION_IMAGE pytest -o addopts='' -m 'not live' -v tests/unit/test_p1_rev03_isolation_preflight.py` → **8 passed, 1 skipped**，退出码 0。`test_worker_fails_closed_without_backend` 通过；`test_escape_is_contained_when_backend_available` skip，默认镜像 `python:3.11-slim` 本地不存在且 no pull attempted。跑后 `docker images python:3.11-slim -q` 为空，确认未拉取。
- D：未运行 `cd Test3 && make test`。该目标等价于 `cd backend && uv run pytest -q -m "not live"`，与 B 全量重复，且 `uv run` 可能解析/创建另一环境；B 已在项目 `.venv` 与隔离镜像条件下完成全量非 live 验证。

### 契约与边界核对

- **不在项目下建 Bot**：未注册 `POST /api/projects/{project_id}/bots`；集成测试断言 404/405 且 `bots` 表行数不变。
- **唯一 leader**：`uq_project_one_leader` 部分唯一索引真实生效；并发两个 Bot 争 leader 时仅 1 个 201、1 个 409，leader 数量为 1。
- **移出不删 Bot**：DELETE membership 仅删除 join 行；`GET /api/bots/{bot_id}` 仍 200，其他项目成员关系仍在。
- **pin 冻结不被中途 PATCH 改掉**：`run_bot_pin_snapshots` 在 run 开始时写入；后续 `PATCH /api/bots/{bot_id}` 追加 pin revision，但 `get_frozen_pin` 仍返回冻结值，T05 测试覆盖。
- **PATCH 200 体扩展**：`pin_revision` 为只读整数，已写入 API.md 与本报告。
- **effective_tools 与 F-08 未互相破坏**：`authorize_granted_command` 未改；每卡回归 27 passed；`effective_tools` 空列表返回空集，描述文本不扩权。
- **无品牌黑名单**：未出现“模型名/provider 等于 DeepSeek 就拒绝”的新逻辑；仅保留既有 DeepSeek 专用入口下线行为。
- **无顶级 Model 路由**：未新增 Model CRUD；`GET/PUT /api/config/models` 未改。
- **无前端 Skill 导航**：前端未改；未进入 P3，未新建 `app/memory/`，未做记忆/讨论/DAG/前端工作台。
- **scripted/replay/DashScope/通用兼容**：保留；T05 测试确认 scripted 路径外部 HTTP 调用计数为 0，未启用 `model_live`。

### 明确声明

- 未进入 P3。
- `execution_safety_ready` 仍为 `False`，唯一赋值点仍是 `app/services/runtime.py:218`。
- `Test3/docs/plans/p1-pr-record.json` 仍为 `status=BLOCKED`、`github_pr_url=null`。
- 未 push、未建远程分支、未开 PR。
- 未安装/启动 Docker，未 pull、未 build；隔离镜像检查成功，未执行 tag 重挂。
- 原 5 个未跟踪文件（`P1-review.md`、`P0-report.md`、`baseline-lock.json`、`decommission-target-state.json`、`p0-t01-cmd.log`）仍未纳入任何提交。

### 人工验收提醒

- 再点一次 `POST /api/projects/x/bots`：应返回 404/405，且 `bots` 表零新增。
- 可选人工复核：创建 Bot → PATCH 改 model → 检查 `GET /api/bots/{id}` 与 PATCH 返回的 `pin_revision`；运行开始后冻结快照不随 PATCH 改变。
- 检查 `git log --oneline -7` 应看到 T01–T06 六个 P2 提交，工作区仅剩上述 5 个既有未跟踪文件。
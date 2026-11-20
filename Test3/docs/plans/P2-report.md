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
- 本卡未改 `authorize_granted_command`，既有 F-08 27 项回归通过。
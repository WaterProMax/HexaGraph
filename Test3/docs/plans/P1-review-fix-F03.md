# P1 审查修复 · F-03 单一 Alembic 权威

- 日期：2026-11-19（Asia/Singapore）
- 前置：F-01 REV-05 失败测试；F-02 已完成。
- 本任务只在 `tmp_path` 临时库演练；未触碰用户主库，未执行 `alembic stamp`。

## 1. 实现

### 1.1 生产启动只走 Alembic

`Workbench._ensure_db()` 不再调用 `create_all()`：

1. `sqlite_url(self.db_path)` 确保目录存在；
2. `await asyncio.to_thread(upgrade_database, self.db_path)` 执行 `alembic upgrade head`；
3. 迁移成功后才创建 async engine / session factory。

新增 `app/storage/migrate.py`：`alembic_config(db_path)` 使用同步 `sqlite:///` URL（`env.py` 是同步
`engine_from_config`），`upgrade_database()` 是唯一生产入口。

`alembic.ini` 默认 URL 从 `sqlite+aiosqlite:///./test3.db` 改为 `sqlite:///./test3.db`，避免直接运行
`alembic` 时在迁移前因 async driver 失败。

### 1.2 schema-aware 迁移（不是 stamp）

- `0001_init`：逐表检查是否存在；存在则核对期望列，缺列抛 schema drift；不存在才建表。
- `0002_execution_grants`：表存在则核对 `grant_id/run_id/status/payload`，并补建缺失的
  `ix_execution_grants_run`；缺列抛 drift。
- `0003_run_execution_state`：表存在则核对列集合，缺列抛 drift。

因此两条历史冲突路径都能继续升级：

1. 已到 `0001`、旧 Workbench `create_all()` 建了 `execution_grants`：`upgrade head` 识别并核验现有表，
   不重复 `CREATE TABLE`；
2. 旧 Workbench 先建了整棵元数据但无 `alembic_version`：`0001` 逐表识别并核验，随后写入真实版本号；
   没有使用 `stamp`。

### 1.3 测试路径

- `tests/unit/test_grant_repo.py` fixture 改为 `upgrade_database(db)`，不再用 `create_all()` 造生产同款库。
- `tests/integration/test_p1_rev05_alembic_handoff.py` 新增源码守卫：`runtime.py` 不得出现 `create_all(` 调用。

## 2. 演练与结果

临时库 upgrade → downgrade 0001 → upgrade：

```text
head: 0003
tables: ['alembic_version', 'event', 'execution_grants', 'project', 'run', 'run_execution_state']
after downgrade 0001: 0001
grants exists: False
re-upgrade head: 0003
```

交接测试：

```text
cd Test3/backend && .venv/bin/python -m pytest \
  tests/integration/test_p1_rev05_alembic_handoff.py \
  tests/integration/test_alembic_execution_grants.py \
  tests/unit/test_grant_repo.py -v
# 8 passed
```

- 路径 A：先 `upgrade 0001`，旧 Workbench 路径建 `execution_grants` 并写一条 Grant，再 `upgrade head`
  → 成功，Grant 行仍在。
- 路径 B：修复后运行时 `_ensure_db()` 启动，再执行 Alembic `upgrade head` → 不报
  `table project already exists`，版本到达 `0003`。

## 3. 生产库操作边界（人工门）

本次**没有**对 `Test3/data/test3.db` 或任何用户业务库执行 upgrade/downgrade。若未来需要迁移真实库：

1. 停止 Workbench；
2. 复制 `test3.db`、`test3.db-wal`、`test3.db-shm` 到备份目录；
3. 在副本上运行 `alembic upgrade head`，核对 `alembic_version` 与 `execution_grants` / `run_execution_state`
   数据行数；
4. 确认 schema 等价后才对生产副本替换；
5. 禁止用 `alembic stamp head` 作为修复手段。

## 4. 边界

- 未新增 P2 表设计；`0001` 仍只覆盖 P0 的 project/run/event，其他 ORM 表不再由生产启动创建。
- 未改用户主库；未 push；未启动服务。
- F-04 的生产启用会使用本任务建立的 Alembic head schema。
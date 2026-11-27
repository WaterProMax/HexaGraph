# ADR 0001: 持久化写边界

状态：Accepted（P7-T01）
范围：Test3 工作台后端

## 决策

新域以 SQLite 为唯一写权威。具体表与归属：

| 域 | 表 | 写权威 |
|---|---|---|
| Bot 实例与 pin 历史 | `bots`、`bot_pin_revisions` | SQLite |
| Skill 定义（按版本只追加） | `skill_definitions` | SQLite |
| 项目成员 | `project_memberships` | SQLite |
| 执行授权 | `execution_grants` | SQLite |
| 运行执行档案与基线哈希 | `run_execution_state` | SQLite |
| 冻结的 Bot pin 快照 | `run_bot_pin_snapshots` | SQLite |
| 记忆（版本追加） | `memory_records` | SQLite |
| 讨论会话 / 提案 / 评审 | `discussion_sessions`、`discussion_proposals`、`discussion_reviews` | SQLite |
| 模块验收 / 缺陷 | `module_acceptances`、`defects` | SQLite |

## legacy 例外

遗留 legacy run 的项目字典、运行快照与事件继续使用 JSON：

- `data_dir/projects.json`
- `data_dir/runs/<run_id>/snapshot.json`
- `data_dir/runs/<run_id>/events.jsonl`
- 恢复失败时追加 `data_dir/recovery.jsonl`

这些文件只承载 legacy 运行态，不是任何新域的写权威。

## 禁止事项

- 不把新域双写进 JSONL：创建 Bot / Skill / 成员 / Grant / 记忆 / 讨论 / 验收 / 缺陷不得新增 JSONL 行。
- 不把 legacy 历史 JSONL 全量迁移到 SQLite；legacy 写入路径（`emit` → `events.jsonl`）保持可用。
- 不在生产路径用 `create_all`；Alembic 是唯一 schema 权威，当前 head 为 `0010`。
- 不删除已提交的记忆历史行，不把 `published` 记忆降级为 `pending`。

## 重启恢复步骤

1. `Workbench.__init__` 同步执行 `restore_runs()`：读 `projects.json`，按目录反序列化 snapshot + events，重建任务状态。
2. `_restore_execution_profile()` 以 `run_execution_state` 为准；snapshot 自称 `granted_v1` 但库中无行时解析为 `conflict`（fail closed），绝不降级为可用 profile。
3. 同一处用只读 sqlite3 连接把该 run 的 `execution_grants` 回填进进程内 `_grant_cache`；`_ensure_db()` 在引擎就绪后再以 SQLite 为准整体回填一次，`_refresh_grant_statuses()` 刷新后也回填，保证缓存与库不分叉。
4. `app/ops/reconcile.py` 做进程内对账：统计 active grant；把 `memory_records.status` 索引列与 payload 的 status 对齐（不改 payload/body、不删行）。重复执行为 no-op。
5. 进程内锁（`asyncio.Lock`、`RunLockRegistry`、`GenerationGuard`）随进程消失，不做跨进程文件锁。
6. 运行中任务：`restore_runs()` 把 `model_stage.running` 标为 `interrupted`；`repo/.git` 存在时 `recover_tasks()` 收口或把残留 `running/verifying` 转回 `ready`。半截运行态可继续或明确中断，不产生重复 grant、重复 pin 快照或重复删除。
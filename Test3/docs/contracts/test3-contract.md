# Test3 契约（增量，指向已确认设计）

本契约不另造规则。对外行为以 `Design.md`、`Architecture.md`、`ImplementationPlan.md` 为准。

## 状态机

- 阶段转换：Architecture.md 第 6.1 节表。不在表中的转换抛 `IllegalTransition`。
- 任务状态：Architecture.md 第 9.1 节。只允许 `transition()` 修改 `task.state`。
- 变更单：submitted → analyzed → evaluated → decided → applied → verified → closed。
- 反馈：new → distilled → evaluated → routed → closed。

## 不变量

1. **唯一性**：同一 run 内编号（Q/I/F/N/M/C/T/A/CR/FB/R）严格递增不重复。保证层：Service Invariant + 行锁/事务。
2. **同事务原子性**：控制操作在同一事务内检查 `expected_revision`、改状态、版本加一、写事件。冲突返回 409。
3. **终态幂等**：done / skipped / cancelled 上的非法转换拒绝；已合并分支恢复时不重复合并。
4. **归属**：本机单用户；操作者记为 `operator` 字段（默认 `owner`）。控制必须带理由的操作缺理由则拒绝。

## SQLite

每个连接：`PRAGMA foreign_keys = ON;` `PRAGMA journal_mode = WAL;`

## REAL / MOCK

| 边界 | 属性 |
|---|---|
| DashScope 真实调用 | REAL，仅 `@pytest.mark.live` 与 `make check-models` |
| scripted / replay | MOCK，默认测试 |
| 反馈 HMAC | REAL，密钥来自 `FEEDBACK_HASH_KEY` |

## 默认上限

见 `config/limits.yaml`，与 Design.md 第 15.10、17.4 节一致。

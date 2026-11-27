# P5 返工适配与崩溃恢复差距清单（2026-11-24）

本文件只记录**实际已接上的能力**与**仍未闭环的差距**，不把适配描述成完整闭环。

## 已接上（有测试）

1. **模块验收 → 缺陷**
   - `POST /api/runs/{run_id}/module-acceptances` 的 `rejected` 会为每个任务打开一条 `open` 缺陷，并把任务置为 `failed`（既有能力）。
   - `model_self_review` 继续被 400 拒绝；缺陷/验收都要求已存在的证据 URI。

2. **修复 → 复验（本轮新增）**
   - 同一 run/任务再次提交 `accepted` 模块验收时，旧的 `open`/`reopened` 缺陷被标记为 `resolved`，并写入 `resolved_by_acceptance_id`、`resolved_at`；缺陷行与历史证据**不删除**。
   - 验收/缺陷响应附 `evidence`：`scripted` 环境显示为“脚本/模拟验收”，不会写成真实测试通过。
   - 测试：`tests/integration/test_module_acceptance_and_defects.py`。

3. **崩溃恢复（本轮新增）**
   - 进程重启时，快照中处于 `running`/`verifying` 且没有证据的任务被标记 `needs_reconciliation=True`、`paused=True`；调度器不会自动再派发，投影阶段为 `needs_reconciliation`。
   - `POST /api/runs/{run_id}/reconcile` 返回只读报告（任务、状态、证据数），不自动执行、不改任务状态；重复调用结果一致。
   - 手动 `retry`/`takeover` 以及显式 `schedule(task_codes=[...])` 对这类任务返回 409 `needs_reconciliation`。
   - 测试：`tests/unit/test_workflow_recovery.py`。

## 仍未闭环（明确差距）

1. **讨论主线仍以整 run 验收为主**
   - 前端讨论 e2e 走 `POST /api/runs/{run_id}/accept`（整 run 验收），不是模块验收主路径。
   - 模块验收与整 run 验收之间尚无强制的“模块证据必须被整 run 验收消费”的绑定；本轮没有伪造这层闭环。

2. **缺陷不会自动生成修复任务**
   - 缺陷只把任务置 `failed`，后续仍依赖人工 retry / 既有变更请求（CR）链路；没有“缺陷 → 自动返工任务卡”的生成器。

3. **复验历史只保留在缺陷 payload**
   - `resolved_by_acceptance_id` + 多次 `ModuleAcceptance` 行可追溯，但没有独立的“同一缺陷第 N 次复验”表；若将来需要统计复验轮次，需加法迁移。

4. **和解只有只读报告**
   - 没有“人工确认已核查、恢复任务为 ready”的写接口；当前安全默认是保持暂停并等待人工决定。后续如需要，应新增显式人工动作，而不是自动重放。

5. **外部副作用不保证恰好一次**
   - 本轮的保证是“不自动重放未知执行”；命令/ Git 写入本身仍不是端到端事务。

6. **真实隔离执行仍不可用**
   - `execution_safety_ready` 保持 `False`；granted 真实执行的隔离/授权链路未在本轮打开，相关真实写入未验证。

## 结论

P5 的“失败 → 缺陷 → 修复 → 复验”在模块验收层已可追踪且保留历史；讨论主线仍以整 run `accept` 为主，二者尚未合并成单一闭环。崩溃恢复采用**暂停 + 人工和解**，不自动重放。以上差距不得在 README/UI 中写成已闭环。
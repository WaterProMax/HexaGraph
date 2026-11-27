# 最终边界收口 · 交付总结（2026-11-24）

## 0. 交付提交

- 代码与测试：`5a64bf0`（fix(workflow): 收口候选驳回、原子采用、成果证明与和解持久化）
- 并发串行化小修：`5acf739`（candidate gate 与任务执行共用 per-run 写锁，审计暂存不会吞掉并发事件）
- 审计与交付文档：`6d8fc6f`、`59434ba` 及其后的本文件更新
- 交付时 HEAD 以 `git log -1 --oneline` 为准；未 push、未开/改 PR。

## 1. 开工审计

- 分支：`feat/test3-agent-team-v1`
- 开工 HEAD：`4c1e04035bc6eb6bda9e58d5b02dadaa61f74a40`
- 与审查锚点 `4c1e040` 的关系：相同（未 reset、未丢弃任何用户提交）。
- 工作树登记（未读取内容、未回显、未提交、未清理）：
  - `Test3/config/models.yaml`
  - `Test3/data-removed-runs/`
  - `Test3/data.bak-20261123-165249/`
  - `Test3/data.bak-20261123-212933-replan/`
  - `Test3/data.bak-20261123-232154-fine/`
  - `Test3/docs/screenshots/`
- 审计文档：`Test3/docs/plans/final-boundary-repair-audit-2026-11-24.md`

## 2. 改前 / 改后离线测试（本轮实际运行）

改前：

- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o "addopts=-m 'not live'" -q`
- 结果：`846 passed, 3 skipped, 2 deselected, 1 warning in 46.24s`，退出码 0。
- 日志：`/tmp/final_boundary_prechange.log`

改后：

- 同一命令（最终代码，含 per-run 串行化小修）：`886 passed, 3 skipped, 2 deselected, 1 warning in 52.56s`，退出码 0。
- 日志：`/tmp/final_boundary_post3.log`（前一次同代码语义运行 `/tmp/final_boundary_post2.log` 为 64.92s，同为 886 passed）。
- 前端：`npm test` → `427 passed (427)`，退出码 0；`npm run build` → `✓ built in 2.77s`，退出码 0。
- 讨论主线 e2e：`npm run test:e2e:discussion` → `1 passed (8.2s)`，退出码 0（模拟执行器；日志 `/tmp/final_boundary_e2e.log`）。
- 未跑：真实模型、真实容器隔离执行；产品 `execution_safety_ready` 仍为 `False`。
- 没有把 scripted/模拟结果写成真实执行通过；没有用历史自述绿数代替本轮结果。

## 3. 按卡变更

### 卡 A：候选再确认门驳回独立分派

- `Workbench._candidate_gate_binding` 统一识别绑定候选的 `PLAN基线确认` 门；`_resolve_gate_locked` 在改门状态前先分流到 `_resolve_candidate_gate`。
- 候选 approve/reject 共用 `_validate_candidate_gate`：CAS、pending、candidate_id/hash、project/run/session、父基线哈希；SPEC 变更只在 approve 时要求 ack+reason。
- `_reject_candidate_gate` 只更新该门/该候选/审计，不调用 `run_plan`、`_apply_replan`、`_apply_incremental_docs`，不改 active SPEC/DESIGN/PLAN、批准哈希或 grant；不复活 stale grant；不清手工 pause/任务 reconciliation。
- 最后一个 pending 候选被驳回时只清除 `baseline_reapproval_required`（以及由它拥有的 run pause），之后可创建新候选或 resume。
- 普通非候选 PLAN 门驳回仍走原 `plan_rewrite` + `run_plan`。

### 卡 B：候选采用先校验、再一次提交

- 采用路径先完成全部校验，再按固定顺序写侧状态：旧 grant 标 stale（SQLite）→ 同步 `run_execution_state` 基线哈希（SQLite）→ 原子替换 `snapshot.json`（权威采用提交点）→ 才落盘 gate/baseline/task 审计事件。
- 审计事件在提交前通过 `_stage_audit(run)` 暂存，失败不写入 `events.jsonl`，避免重启把半采用事件回放进任务状态。
- 采用失败：门保持 pending，active 与批准哈希保持旧值（内存 identity-preserving 回滚）；旧 grant 可能已 stale，这是选定的安全中间态。重启时若没有 active grant，按快照恢复基线并允许带同一 `expected_revision` 重试；不存在“新快照 + 旧 grant 可执行”的组合。
- 已 adopted 的候选/门再次批准不会重复追加 approval；并发至多一次成功；采用路径不调用 git/worktree/命令/网络。
- `add_grant` 在创建新 grant 时把当前 run 基线同步进 `run_execution_state`，避免上一次采用中断留下的哈希偏差在下一次重启伪装成冲突。
- 单进程假设：Workbench 内存 + per-run/gate 锁 + `run.revision` CAS；不支持多进程共享同一 `data_dir`。没有使用通用事务框架，也不声称 SQLite 事务覆盖快照、事件与 grant。

### 卡 C：任务成果按 attempt 证明

- `_begin_attempt(..., repo=..., branch=..., integration_hint=...)` 在真实执行前冻结：规范化 repo / repo_identity、`base_commit`、`integration_ref` 及其 SHA、任务分支、write_set、任务的 run/project。
- 真实执行前先初始化 repo（仍在既有授权/safety 之后），再写 attempt；模拟执行不建 repo，attempt 明确不可自动证明。
- grant 指定 `base_branch` 但本地不存在该 ref 时不回退猜测 HEAD；detached 或无法解析集成引用时 `proof_ready=false`，`accept_evidence` 失败封闭。
- `verify_task_completion` 现在要求：attempt 身份、当前基线、repo 身份一致；commit/base 存在；commit 与任务分支绑定（commit 在分支上，或分支已 merge 进该 commit）；base 是 commit 祖先；`integration_ref` 当前 SHA 存在且未回退；commit 已是集成 ref 祖先；`git diff --no-renames base..commit` 非空且所有路径规范化后落在 write_set（目录前缀可用，删除/重命名两端都检查）。
- 旧正例已改为真实集成正例；未合并、老文件未改、无关 commit、越界变更、跨 repo、基线漂移、集成 ref 换到无关历史、缺少冻结字段均拒绝。squash/cherry-pick 本轮不自动通过，留给人工决议。
- 校验只读（`_git_sync`），不 checkout/reset/merge/fetch/tag，不跑测试命令，不写工作区。

### 卡 D：和解决议绑定 attempt 并跨重启保持

- 新增 append-only `task.reconciliation_resolutions`：run/task/attempt、当时基线、task/run revision、decision、actor、reason、`verified_safe_scope`、`risk_accepted`、completion report 与哈希、时间；`reconciliation_history` 继续保留人类审计。
- 未知集合按 attempt 计算：`started/unknown/无 attempt_id` 且没有有效 closure 的 attempt 才阻断；`finished_failed` 视为可信终态；`finished_ok` 只在任务 done 时可信。不把 history 改写为 `finished_failed`，不设全局 reconciled 布尔。
- `resolve_reconciliation` 可选 `attempt_id`，缺省取最新未决议 attempt；决议只关闭该 attempt。仍有其它未决议 attempt 时任务保持 `needs_reconciliation`，不强行 done/failed；全部关闭后才迁移状态。`applied` 与持久化在一次快照提交内完成，失败回滚同进程内存。
- 同一决议重复提交幂等（不重复写记录）；同一 attempt 换 decision 409；错误 attempt、跨 run、旧基线、错误 CAS 均无状态副作用（拒绝审计除外）。
- `mark_failed_safe_retry` 不自动重试、不新增 attempt；`continue_reconcile` 仍不清 unknown；只清本任务和解暂停，不清手工 run pause。只读 `/reconcile` 仍只读。

## 4. 验收矩阵

| 卡 | 关键不变量 | 证据 | 状态 |
| --- | --- | --- | --- |
| A | 候选非 approve 不走 run_plan；active 与批准哈希字节不变；过期门不能驳回新候选；手工暂停保留；普通 PLAN 驳回不变 | `test_candidate_gate_rejection.py`（8 项，真实 HTTP） | 通过 |
| B | 先校验后一次提交；失败/重启无 approved 半采用；CAS 至多一次；幂等不重复 approval；不宣称跨进程事务 | `test_candidate_adoption_atomicity.py`（8 项，故障注入 + 新 Workbench） | 通过 |
| C | 创建时冻结集成引用/base；真实 diff 落在 write_set；标 done 必须已集成；旧正例已改；只读无副作用 | `test_completion_proof.py`（15 项）；`test_workflow_reconciliation_api.py` 正例已改真实 merge | 通过 |
| D | 决议绑定 attempt 并持久化；重启不回弹；新 unknown 仍拦；不全清；safe_retry 不自动执行 | `test_reconciliation_persistence.py`（9 项，真实 API + 两次新 Workbench） | 通过 |
| 回归 | F1 未决议窗口、F2 批准 CAS/supersede/SPEC ack、F3 间谍 0、证据/基线守卫 | 全量后端、前端、既有 F1–F4 测试 | 通过 |

## 5. 迁移 / 回滚

- 提交拆分说明：A/B 共用 `_resolve_gate_locked`/`_resolve_candidate_gate`，C/D 共用 attempt 与和解状态；机械按卡拆分会留下不可独立运行/回滚的半套补丁，因此本轮代码与对应测试作为一个原子提交，文档另一个提交。回滚按下列整组原则执行，不提交半套安全补丁。
- 无数据库迁移；新增字段都在既有 snapshot task 与 `reconciliation_resolutions` 内。
- 旧 attempt 缺少 `base_commit`/`integration_ref`/`repo_identity` 时：不接受为完成，返回失败并提示重新执行或人工和解；不伪造回填。
- 旧 `reconciliation_history` 不会被当作 closure；升级后若只有历史记录没有新决议，任务仍按 attempt 规则保守阻断。
- 回滚原则：优先停用动作并保持阻断。若回滚 A/B，禁止恢复“候选驳回落 run_plan”或“先标 approved 再写产物”；若回滚 C，`accept_evidence` 必须全部失败封闭；若回滚 D，F1 的未决议不自动重放必须保留。
- 本轮的 `execution_state_recovered` 仅是恢复审计标记；没有把它当作执行授权。

## 6. 仍未闭环（诚实列表）

- 产品 `execution_safety_ready` 仍为 `False`，真实隔离写/真实容器执行仍不可用；这是预期诚实状态。
- P5 讨论主线仍整 run `/accept`；本轮未改。
- CR/重排真实模型生成链、模型失败重试副作用计数 E2E 未补；本轮只覆盖候选门与采用路径。
- `X-Bot-Id` 仍是本机单用户声明，不是 OAuth；未新增认证。
- 自动循环事件去重仍仅进程内。
- squash/cherry-pick 无只读证明，本轮按产品约定不自动接受。
- Cutpoint D（磁盘比快照更脏）与 loop 启动顺序仍不在本轮扩测范围。
- 多进程共享同一 data_dir 的并发写不支持；本轮不声称跨进程 exactly-once。
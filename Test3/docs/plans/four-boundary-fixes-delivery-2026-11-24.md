# 四项边界闭环交付总结（2026-11-24，本地）

## 1. 开工审计

- 分支：`feat/test3-agent-team-v1`
- 开工 HEAD：`61ad86a`（审查锚点，相同；功能提交止于 `351cde1`）
- 交付 HEAD：见提交 `fix(workflow): 四项边界闭环...` 后的 `git log -1`
- 未纳入提交（只登记）：`Test3/config/models.yaml`、`Test3/data-removed-runs/`、`Test3/data.bak-20261123-*`、`Test3/docs/screenshots/`
- 未读取/未提交密钥、`.env`、BotSecret；未触碰 `Test3/data`。

## 2. 改前测试基线（本轮实跑）

`cd Test3/backend && uv run pytest -m "not live" -o addopts="" -q`

**832 passed, 3 skipped, 2 deselected，退出码 0（43.87s）。** 这是本轮实测，不是历史自述。

## 3. 按 F1–F4 变更

### F1 恢复窗口：ready + started 不再自动重放

- `task["attempt_history"]` append-only；旧快照只有 `attempt` 时迁移进历史。attempt 新增 `repo_identity / worktree / branch / write_set / target_branch / task_code / run_id / project_id`。
- `_begin_attempt` 先把未结束的当前 attempt 入历史，再写新 attempt 并持久化；`_finish_attempt` 状态改为 `finished_ok|finished_failed|unknown`，同时更新历史同 id 记录。
- 恢复扫描改为 `_tasks_requiring_reconciliation`：扫描历史 + 当前 attempt，而不是快照当时状态；ready+scheduled+running+verifying、有无 repo/worktree/部分 evidence 均纳入；`done` 也仅在无 started/unknown 时跳过。
- `_mark_unknown_executions` 使用该集合，设置 `needs_reconciliation + paused`。
- 调度双门：`conflict_ready` 与 `select_tasks` 的 paused 集合都排除 `needs_reconciliation`；显式 `task_codes` 仍 409。
- 测试：`test_workflow_recovery.py` 新增 Cutpoint A（无 repo）、B（有 repo/部分 evidence）、旧快照迁移、二次重启、纯 ready 不误伤。

### F2 不可变候选与原子采用

- `workflow_candidates[candidate_id]` 保存冻结文档（SPEC/DESIGN/PLAN）、canonical hashes、父基线、project/run/session、candidate_revision、candidate_hash、mode/affected；`workflow_candidate` 仅是指向 pending 候选的 id。
- 新候选创建时 supersede 旧 pending 候选，并把旧候选门标 `superseded`；旧门 resolve 返回 409。
- 存在已批准基线时，CR/重排只写候选与门，不覆盖 active artifacts、不提前物化/取消任务；无基线仍保持原草稿写入。
- 候选门 payload 含 candidate_id/hash/changed_keys/文档/source_gate_id。`POST /gates/{id}/resolve` 对候选门：
  - 必须带 `expected_revision`（缺 400）；
  - 校验候选仍 pending、candidate_hash 重算一致、project/run/session 绑定一致；
  - 只采用候选快照，不读 live artifacts；
  - SPEC 变更必须 `payload.acknowledge_spec_change=true` + reason，否则 400 `spec_reapproval_required`；
  - 采用时写 active、哈希、approval、旧 grant stale、只清基线拥有的暂停；replan 才取消/物化任务，CR 只同步受影响任务卡。
- `resume` 遇到 `baseline_reapproval_required` 返回 400，不能靠清 paused 调度。
- 旧 dict 形候选在恢复时拒绝旧门，要求重新生成，不采用 live。
- 测试：`tests/integration/test_reapproval_candidate_api.py`（旧门不改 live、缺 revision、supersede、SPEC 覆盖、手工暂停、并发一次成功）、`test_workflow_invalidation.py` 更新为生产门+CAS。

### F3 模拟路径完整零副作用

- `accept` 不再 init repo；`_verify_spec_item` 返回 `simulated://`。
- takeover 只写 `simulated://...` 虚拟工作区，不建 repo/worktree。
- submit-takeover 在模拟下直接写 simulated 证据并走状态迁移，不 merge。
- force-pass 在模拟下跳过回归命令，证据 `simulated`。
- `_export_release` 在模拟下只写元数据 JSON，不 tag、不 copytree、不生成 release/code。
- 测试：`test_simulation_zero_side_effects.py` 对 init/create_worktree/tag/merge/copytree/run_command 全部装间谍，accept + release 与 takeover + submit 两条路径计数为 0，repo/wt/release-code 目录不存在；讨论 e2e 仍走模拟器并通过（证据 simulated）。
- 产品入口仍只能通过 `create_app(execution_policy=...)` 服务端注入；HTTP/env/请求字段不可打开。

### F4 和解证明与 safe_retry 审计

- 新增 `app/workflow/completion.py::verify_task_completion`：校验 attempt 在历史、task/run/project 一致、基线一致、repo 身份匹配本 run、commit 存在、write_set 全部在 commit 树、branch 存在、commit 在目标分支 ancestry，并记录 provenance。
- `accept_evidence` 只在该报告 ok 时迁移 done；README HEAD、任意 commit、缺 write_set/branch/字段一律失败并记录 `accept_evidence_rejected`，保持 unknown。
- `mark_failed_safe_retry` 必须 `verified_safe_scope` 非空且 `risk_accepted=true`，审计写入 scope/risk/actor/attempt；不启动新执行，后续 retry 仍走同一授权。
- `continue_reconcile` 不清 flag。
- 测试：`test_workflow_reconciliation_api.py` 重写：README 假成功失败、真实任务分支 write_set 成功、缺 scope/risk 拒绝、continue 保持、HTTP actor/CAS。

## 4. 改后测试（本轮实跑）

| 项 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `cd Test3/backend && uv run pytest -m "not live" -o addopts="" -q` | **846 passed, 3 skipped, 2 deselected，退出码 0（45.60s）** |
| 前端单测 | `cd Test3/frontend && npm test` | **427 passed（19.54s）** |
| 前端构建 | `npm run build` | 成功（2.65s，仅既有 chunk 警告） |
| 讨论 e2e | `npx playwright test --config playwright.discussion.config.ts` | **1 passed（6.2s，总 8.2s）** |
| 真实模型 / 真实 sandbox | — | **未跑**：未授权；产品总闸仍 false |

声明：未跑真实模型；产品 `execution_safety_ready` 仍为 `False`；没有把模拟/scripted 结果称为真实执行通过。

## 5. 对照矩阵

| 主题 | 状态 |
|---|---|
| F1 恢复窗口（ready+started、历史扫描、二次重启、计数不增） | 通过（新增 4 个 cutpoint/迁移用例） |
| F2 不可变候选、门绑定、CAS、SPEC 不偷换、手工暂停、旧 grant stale | 通过（新增 6 个 HTTP 用例；CR 生成内容用候选 helper 固定） |
| F3 accept/takeover/submit/release 零副作用 | 通过（间谍为零；e2e 通过且证据 simulated） |
| F4 成果校验、safe_retry 审计、continue/CAS | 通过 |
| 产品总闸 / 真实模型 / P5 / 模型重试 E2E | 仍未闭环（见第 8 节） |

## 6. 生产步骤

1. 在已批准基线上提交并批准变更决定/重排提案 → 只生成不可变候选与 pending `PLAN基线确认` 门，active 不变。
2. 打开待办门，查看 SPEC/DESIGN/PLAN 与 changed_keys。
3. 带 `expected_revision` resolve；若含 SPEC 变更，额外 `payload.acknowledge_spec_change=true` + `payload.reason`。
4. 采用后旧 grant 全 stale；真实执行仍需新 grant 且总闸开启（当前关闭）。
5. 重启出现 `needs_reconciliation`：先看只读 `POST /reconcile`，再用 `accept_evidence`（需 commit/write_set/ancestry）或带 scope/risk 的 `mark_failed_safe_retry`。

## 7. 迁移与回滚

- 无 Alembic 迁移；候选/attempt/决议字段均为快照加法；旧 dict 候选门拒绝并要求重新生成。
- 回滚须整项：F1 扫描与调度门禁不可单独回退；F2 只能“候选门一律拒绝采用”，不能回到“先改 active 再读 live”；F3 撤回统一分派也须保留各入口模拟拒绝；F4 校验器失败时保持 unknown，不能恢复字符串成功。

## 8. 仍未闭环（诚实）

1. 产品总闸仍 false，真实隔离执行不可用。
2. P5 讨论主线仍整 run accept，缺陷不自动生成返工任务。
3. 模型失败重试“副作用只计一次”无端到端计数测试。
4. CR/重排的真实模型生成链未集成测试；本轮以候选 helper + 真实 gate HTTP 覆盖采用语义。
5. accept_evidence 的 actor 仍是本机 `X-Bot-Id` 声明，不是 OAuth。
6. 自动循环事件去重仅进程内；重启会重发第一条可观测事件。
7. F1 Cutpoint D（磁盘比快照更脏）与 loop-start 顺序仅由代码路径与现有测试间接覆盖，未单独构造磁盘脏数据用例。
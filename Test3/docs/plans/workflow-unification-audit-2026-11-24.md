# 工作流统一（讨论→规格→计划→PLAN→执行→验收）开工审计

日期：2026-11-24
范围：HexaGraph Test3 本仓库副本（当前工作树即仓库根，命令均在仓库根执行，路径前缀 `Test3/...`）。

## 1. 仓库与提交事实

| 项 | 实际值 |
| --- | --- |
| `git branch --show-current` | `feat/test3-agent-team-v1` |
| `git rev-parse HEAD` | `63e3608939e0744cc8e9f6b34707fa2df2d65713` |
| `git log -1 --oneline` | `63e3608 feat(ui): 精简项目头部并优化讨论消息交互` |
| GitHub 参考 SHA | `63e3608939e0744cc8e9f6b34707fa2df2d65713` |

结论：与参考 SHA **相同**；没有超前 / 落后 / 分叉。未执行任何 reset、checkout 覆盖或改写提交。

## 2. 工作区脏改动（只读记录，未触碰）

`git status --porcelain`：

```text
 M Test3/config/models.yaml
?? Test3/data-removed-runs/
?? Test3/data.bak-20261123-165249/
?? Test3/data.bak-20261123-212933-replan/
?? Test3/data.bak-20261123-232154-fine/
?? Test3/docs/screenshots/
```

- `Test3/config/models.yaml`：用户本地模型槽位切换（DeepSeek → 百炼 model/base_url 调整）。属于已跟踪文件的既有本地改动，**本任务不重置、不覆盖、不纳入提交**；后续提交只 `git add` 本卡相关文件。
- 四个 `data*` 目录与 `docs/screenshots/`：用户未跟踪的备份/截图，**不清理、不提交**。
- 未修改 `.env`、密钥或 `Test3/data` 业务库。

## 3. 改前测试基线（本机实测）

命令（在 `Test3/backend`）：

```bash
uv run pytest -q -m "not live"
```

结果：退出码 **0**；`--collect-only` 共 **754** 个离线用例被收集。该数字是本机本次运行结果，不代表历史或参考提交的绿数。

未运行：`-m live`（需要真实/付费模型）、Playwright 讨论 e2e（需要前端依赖与浏览器，见第 7 节）。

## 4. 关键文件与本地事实核对

| 事实 | 本地核对结果 |
| --- | --- |
| `Test3/backend/app/api/routes_discussion_control.py::plan_discussion` | 存在；要求 leader、项目 Leader、`status == "approved"` 且 `decision_package` 非空，否则 409 `invalid_status`「需先确认需求规格」；成功返回 `{"run_id": ...}` |
| `Test3/backend/app/discussion/planning.py::run_id_for` | `uuid5(NAMESPACE_URL, f"hexagraph:discussion:{session_id}")` |
| `planning.prepare_run` | 进程内 `asyncio.Lock` + `bench.runs` 判重；**没有**跨重启/跨进程判重，也未校验 session 与既有 run 的 project 一致性 |
| `create_discussion_plan_run` | 新 run 显式 `PROFILE_LEGACY`；写 DecisionPackage、SPEC 哈希；PLAN 门 `PLAN基线确认` pending；`engine.current = "6"` |
| PLAN 基线哈希 | 在 `_resolve_gate_locked` 的 `PLAN基线确认` 分支中通过 `_record_approved_baseline(run, "PLAN", ...)` 写入；讨论 run 同时补 DESIGN 哈希。**已存在**，不是缺口 |
| `execution_safety_ready` | `Workbench.__init__` 为 `False`；全仓库产品代码无赋 True 路径 |
| `_require_execution_safety` | 只对 `granted_v1` 总闸生效；`legacy` 绕过总闸。`execute_task` 入口调用 |
| `POST /execution-grants` | legacy run 返回 403 `profile_not_granted_v1`；grant 创建不改总闸 |
| `POST /execution-profile` | 只升 `granted_v1`，不降级、不开总闸 |
| `POST /projects/{id}/runs` | `create_run` 标 `PROFILE_LEGACY`，随后 `start_idea` 可能调用模型；不直接写仓库 |
| `POST /projects/{id}/design-runs` | 设计规格导入，调用模型整理并停在 DESIGN 门；不生成任务、不写仓库 |
| `GET /runs/{id}/monitor` | `build_monitor_snapshot` 无证据级别字段 |
| `POST /runs/{id}/accept` | legacy 路径执行验收命令；granted 路径被 409 拒绝 |
| `bot_endpoint` | Bot 无自身 key 时返回 `None`，调用方回退工作台默认凭据（真实模式失效开放缺口） |
| `model_self_review` | 验收路由 400 拒绝，已有测试 |
| 讨论 `/plan` 专项用例 | `tests/` 中未发现；OpenAPI 快照有路由，但无行为测试 |
| 现有工作流目录 | `app/workflow/` 不存在（本任务新增） |

## 5. 执行入口清单（卡 3 门禁必须覆盖）

1. `POST /api/discussion-sessions/{id}/plan` → `planning.prepare_run`（生成计划，不执行仓库）。
2. `POST /api/runs/{id}/schedule` → `Workbench.schedule_once` → `execute_task`（真实执行入口）。
3. 自动调度循环 `Workbench._schedule_loop` → `schedule_once`（与 2 共用）。
4. `POST /api/tasks/{id}/{action}` → `control_task`；`retry`、`takeover`、`submit-takeover`、`force-pass` 会重新进入执行/合并/回归。
5. `POST /api/runs/{id}/accept` → `accept`（执行验收命令、导出 release）。
6. `POST /api/runs/{id}/execution-profile`、`execution-grants`：授权输入，不直接执行。
7. `POST /api/projects/{id}/runs`：只启动模型草稿流程，不写仓库；需在响应中带 workflow/证据标识。
8. `POST /api/projects/{id}/design-runs`：模型整理，不执行仓库；不在本轮新增门禁，记录在案。

## 6. 本轮实施边界（与提示词一致）

- 新增 `app/workflow/`（stages / projection / admission / evidence / invalidation / recovery）、`app/execution/authorization.py`；不新增第三套权威状态，不新增迁移（除非实现中发现必须，且先补审计理由）。
- 对外字段只做加法；保留 `status`、门名称、`data-testid`、OpenAPI 既有形状。
- 服务端 `execution_safety_ready` 保持 False；不新增开闸 UI；不把规格批准或 PLAN 确认当执行授权。
- scripted/Replay 视为**模拟执行**（不访问真实模型、不向外部仓库推送），证据标 `scripted`；真实 provider + legacy 执行一律拒绝，要求 `granted_v1` + active grant + 基线一致 + 总闸开启（总闸仍关，故真实执行本轮不可用）。
- 每卡：先失败测试 → 实现 → 回归 → 最小本地 commit。不推送、不改线上 PR。

## 7. 未跑项与原因

| 项 | 原因 |
| --- | --- |
| `pytest -m live` | 需要真实/付费模型，未授权 |
| `frontend` Vitest / Playwright 讨论 e2e | 需先确认前端依赖已安装；本机未在开工阶段运行，第一轮出口前补跑并记录真实输出 |
| 真实 sandbox 写入 | 总闸关闭，按设计不可达 |

## 8. 第一轮/第二轮卡与依赖

- 卡 1（投影+准入）→ 卡 2（证据+缺 key）→ 卡 3（统一授权）→ 卡 4（幂等+第一轮出口）。
- 卡 5（失效/重新批准）→ 卡 6（P5 返工适配+崩溃和解+差距文档）。
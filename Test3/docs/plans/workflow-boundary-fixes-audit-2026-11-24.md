# 工作流边界修复开工审计（2026-11-24）

## 1. 仓库与提交

- `git branch --show-current`：`feat/test3-agent-team-v1`
- `git rev-parse HEAD`：`d4618d1`（`docs(workflow): 标注交付 HEAD e8f8a53`）
- `git log -1 --oneline`：`d4618d1 docs(workflow): 标注交付 HEAD e8f8a53`
- 与审查锚点关系：**与 d4618d1 相同**；功能提交止于 `71ccdc8`（本 HEAD 比它多两个文档提交）。无 reset、无覆盖。

## 2. 工作区（只登记，不读取/不提交/不清理）

- 已修改：`Test3/config/models.yaml`（不读取内容、不回显、不纳入提交）
- 未跟踪：`Test3/data-removed-runs/`、`Test3/data.bak-20261123-165249/`、`Test3/data.bak-20261123-212933-replan/`、`Test3/data.bak-20261123-232154-fine/`、`Test3/docs/screenshots/`
- 未触碰 `.env`、密钥、BotSecret、`Test3/data` 业务库。

## 3. 改前离线测试基线（本机实测）

命令（`Test3/backend`）：

```bash
uv run pytest -m "not live" -o addopts="" -q
```

结果见本轮交付文档；不抄前轮 817/427/e2e 数字。

## 4. 本轮已核实的缺口（与审查一致）

1. `app/execution/authorization.py::is_simulated` 只看 provider；legacy + scripted 仍进入真实 worktree/命令/merge。
2. `decide_cr/_apply_incremental_docs`、`_apply_replan` 改写产物但不重记批准哈希；drift 后无生产再批准入口，旧测试靠手工 append 门 + `paused=False`。
3. `_mark_unknown_executions` 把任意 evidence 当终态；granted 先写 evidence 再改状态；`recover_tasks` 未合并时回退 ready，可被自动循环重放。
4. `_resolve_acceptance` 在 `pass=false` + reason 时仍 `done`；`verification_status_for` 把 done 当 passed；`skipped/cancelled/blocked` 算执行；模块响应挂 run 级证据；`model_mode` 用 gateway 全局 calls。
5. `baseline_drift` 以 `artifacts.approvals` 为空直接放行，存量“有哈希无 approvals”漏检。

## 5. 本轮边界

- 不开 `execution_safety_ready`；不新增开闸 UI；不调用真实/付费模型；不推送。
- 只允许通过显式注入的**无副作用模拟执行器**或测试进程内授权来跑 scripted e2e；产品默认仍拒绝真实写。
- 禁止跳过漂移、禁止把任意 evidence 当终态、禁止手工改 paused 当作生产再批准证明。
- 每卡先失败测试 → 实现 → 回归 → 最小本地 commit。
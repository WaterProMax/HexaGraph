# 四项边界闭环开工审计（2026-11-24）

## 1. HEAD 与脏文件

- 分支：`feat/test3-agent-team-v1`
- 开工 HEAD：`61ad86a`（`chore(workflow): 清理本轮引入的未用导入与格式问题`）
- 与审查锚点 `61ad86a`：**相同**；功能提交止于 `351cde1`。
- 未纳入提交（只登记，不读取/不提交/不清理）：
  - `Test3/config/models.yaml`（用户本地模型配置）
  - `Test3/data-removed-runs/`、`Test3/data.bak-20261123-165249/`、`Test3/data.bak-20261123-212933-replan/`、`Test3/data.bak-20261123-232154-fine/`
  - `Test3/docs/screenshots/`
  - `.env`/密钥/BotSecret 未触碰。

## 2. 改前测试基线

命令（`Test3/backend`）：`uv run pytest -m "not live" -o addopts="" -q`

本轮实际结果见交付文档（不抄历史 832/427/e2e）。

## 3. 当前代码事实（按符号重新核对）

与计划一致，四项缺口均存在：

- F1：`_begin_attempt` 先写 snapshot，状态仍 ready；`restore_runs` 只把快照中 running/verifying 记入 pending；`_mark_unknown_executions` 不扫 attempt 历史；`_schedule_once_locked` 只靠 `task.paused`。
- F2：`_apply_incremental_docs` / `_apply_replan` 直接覆盖 active artifacts 后才开门；`_open_reapproval_gate` 的 payload 只有 plan/design；`resolve_gate` 的 candidate 分支读 live artifacts，不校验 candidate hash；`expected_revision` 可选；`set_run_control resume` 无条件清 paused。
- F3：`accept` 仍可能 init_repo；`control_task takeover`、`_submit_takeover`、`_export_release` 仍可能建 repo/worktree/tag/copy；模拟分支只覆盖 execute。
- F4：`accept_evidence` 只校验 attempt.status/commit==HEAD/基线；初始化 README HEAD 可被当作成功；`mark_failed_safe_retry` 只要求 reason。

## 4. 架构声明

单进程 `Workbench` 内存权威 + 文件快照 + SQLite；per-run 写锁 + run.revision CAS。不支持多进程共享同一 data_dir，不宣称分布式事务。`X-Bot-Id` 是本机单用户声明，不是认证。

## 5. 本轮范围

仅 F1–F4，按 F1→F2→F3→F4 顺序。不打开 `execution_safety_ready`，不新增模拟入口，不调用真实模型，不触碰用户数据。
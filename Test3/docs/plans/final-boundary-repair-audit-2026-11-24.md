# 最终边界收口 · 开工审计（2026-11-24）

## 工作副本与提交

- 工作目录：`HexaGraph-Test3-agent-v1`（git worktree）
- 分支：`feat/test3-agent-team-v1`
- HEAD：`4c1e04035bc6eb6bda9e58d5b02dadaa61f74a40`
- `git log -1 --oneline`：`4c1e040 docs(workflow): 四项边界闭环审计、交付与旧承诺更正`
- 与审查锚点 `4c1e040` 的关系：**相同**（`git merge-base --is-ancestor 4c1e040 HEAD` 退出码 0；当前 HEAD 即锚点）。
- 功能父提交 `dc5b83b` 是本轮起点之前的 F1–F4 实现。

## 工作树登记（只登记路径，未读取、未回显、未纳入提交）

- 已修改：`Test3/config/models.yaml`
- 未跟踪：`Test3/data-removed-runs/`
- 未跟踪：`Test3/data.bak-20261123-165249/`
- 未跟踪：`Test3/data.bak-20261123-212933-replan/`
- 未跟踪：`Test3/data.bak-20261123-232154-fine/`
- 未跟踪：`Test3/docs/screenshots/`

以上均属于用户本地数据/配置/截图，本轮不读取内容、不清理、不提交。未发现或读取 `.env`、密钥、BotSecret 或任何凭据文件。

## 改前离线测试（本轮实际运行）

- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o "addopts=-m 'not live'" -q`
- 结果：`846 passed, 3 skipped, 2 deselected, 1 warning in 46.24s`，退出码 0。
- 日志：`/tmp/final_boundary_prechange.log`
- 说明：这是本轮独立跑出的基线，不是引用历史交付中的 846/427/e2e 自述。未调用真实模型、未读 `models.yaml` 的真实模型配置。

## 改后离线测试（本轮实际运行）

- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o "addopts=-m 'not live'" -q`
- 结果：`886 passed, 3 skipped, 2 deselected, 1 warning in 52.56s`，退出码 0（最终代码含 per-run 串行化小修）。
- 日志：`/tmp/final_boundary_post3.log`；前一次同语义运行 `/tmp/final_boundary_post2.log` 为 64.92s、同为 886 passed。
- 前端：`npm test` → `427 passed (427)`，退出码 0；`npm run build` → `✓ built in 2.77s`，退出码 0。
- 新增测试：`test_candidate_gate_rejection.py` 8、`test_candidate_adoption_atomicity.py` 8、`test_completion_proof.py` 15、`test_reconciliation_persistence.py` 9。
- 更新：`test_workflow_reconciliation_api.py` 的正向样例改为真实任务分支 + merge；OpenAPI 结构快照仅新增 `ReconciliationBody.attempt_id`。
- 未跑：真实模型、真实隔离容器执行；产品总闸保持 `False`。没有把模拟/scripted 结果写成真实执行通过。

## 本轮范围

只处理审查确认的四项缺口，按 A → B → C → D 串行：

- A：候选再确认门驳回不再落入普通 PLAN 重写。
- B：候选采用先校验/准备、再一次权威提交；失败无半采用。
- C：任务成果按 attempt 的 base/integration ref 与真实 diff 证明。
- D：和解决议绑定 attempt 并跨重启持久化。

不打开 `execution_safety_ready`，不新增开闸入口，不扩到 UI、模型路由、Docker、OAuth、通用事务框架或分布式一致性。
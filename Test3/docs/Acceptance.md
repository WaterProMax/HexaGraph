# HexaGraph Test3 — 验收状态与证据边界

> 当前口径更新：2026-11-15，修复分支 `fix/design-spec-workflow-validation`。
> 本页区分**页面交互验证**、**scripted 流程验证**和**真实模型能力验收**，不把前两者写成后者。

## 1. 本轮范围

目标流程：

`设计规格输入 → PM Agent 分解开发任务 → 编排器按依赖安排执行 → 可视化及执行交互`

本轮修正三个小范围问题：

1. SSE 断线后保留提示，允许显式重新连接，并重新同步运行、任务、产物和事件。
2. 失败或取消的依赖与普通的未完成依赖分别显示；依赖合法恢复后按真实状态解锁。
3. 设计规格导入的缺项、需拆分、异常和成功待确认状态分别表达；失败导入不再提前写入 SPEC 确认历史。

保留 PR23 的原有架构：同一份 `SpecDoc` / `DesignDoc`，DESIGN 确认后生成 PLAN，PLAN 确认后物化任务并进入既有调度器。原 idea 入口保留，没有第二套任务图。

## 2. 三类证据不得混用

### A. mock 浏览器交互

`frontend/scripts/verify-design-spec.cjs` 拦截 `/api`，只验证页面组件、按钮、展示和交互约定。

- 可证明：mock 数据下页面能完成设计规格入口、DESIGN/PLAN 确认、任务展示、缺项/异常/超长输入展示。
- 不能证明：真实 FastAPI 路由、数据库/持久化、SSE、调度器或真实模型调用正确。

### B. scripted 模型 + 真实后端 HTTP + 真实页面

`frontend/scripts/verify-design-spec-http.cjs` 不拦截 `/api`。后端由 `backend/tests/e2e/design_spec_http_server.py` 启动，显式使用 `ScriptedProvider`，不运行 `app.main` 的 settings lifespan，不读取 `.env`，不发真实模型请求。健康检查返回 `schedule_mode=manual`；页面就绪提示为「请点击调度执行」，不得写成「每 5 秒自动调度」。主样例是 `examples/design-specs/self-study-room.md`，与预置座位查询任务一致。`club-signup.md` 只证明上传/原文保存，不能声称座位任务由社团文档生成。运行与产物持续标注「预置测试输出／模拟执行」，不是一次性 toast。

浏览器实际完成：选择设计规格入口、输入示例、查看整理结果、确认 DESIGN、查看任务分解、确认 PLAN、点击调度、查看任务依赖与状态。后端 API 仅用于只读核对运行编号、任务、依赖和状态。

本轮已实际通过：

- 成功路径：`T-01 → T-02`，两个任务均由页面调度后到达 `done`，运行进入验收阶段。
- 页面刷新后仍读取同一运行，显示 PLAN 已确认及相同任务状态。
- 缺项路径：返回 `needs_input`，无 DESIGN/PLAN 关卡、无任务、无 SPEC 确认历史；刷新后仍一致。
- 浏览器无运行时异常。

证据截图：

- `docs/design/screenshots/design-spec-http-happy.png`
- `docs/design/screenshots/design-spec-http-missing.png`

这项验证证明的是**预置模型结果经过真实前后端 HTTP 后的流程衔接与离线执行**，不是 PM 的泛化生成能力。

复位：停掉离线服务器并用新的隔离数据目录再启动；没有生产环境公开复位 API。队列限制：每次启动只有一次成功整理 + 一次缺项整理，然后耗尽。自动化测试与人工演示必须分开启动，不要共用进程或数据目录。两次完整复位后的首次导入应一致。

### C. 真实模型生成与实际工具执行

真实模型测试必须在组长另行授权后，使用组长指定的真实模型配置单独进行，并保留请求记录、产物、工具结果、退出状态和成本。

本轮没有调用付费真实模型，没有修改原始探测文件，也没有生成新的真实调用记录。

## 3. 真实模型当前状态：部分验证，能力尚未验收

原始记录：`docs/RealModelTest-design-spec-self-study.json`。

- 原始输入为自学网站设计规格。
- 实际返回为 `needs_input`，整理阶段给出 12 条缺项。
- 原始记录停在 `stage=5`；`DESIGN 确认 → PM 分解 → PLAN 确认 → 调度执行` 均未进入。
- 返回缺项本身可能是模型对不完整输入的合理判断，不能为了通过验收而忽略缺项或伪造关卡。
- 本轮没有把原始 `llm_calls` 或 `gates` 改写为成功。

因此真实模型验收只能写为：

> **部分验证：真实模型整理返回 needs_input；真实模型任务分解、PLAN、实际调度和真实业务产品验收尚未完成。**

| 能力 | 当前真实模型证据 |
| --- | --- |
| 外部文档整理与字段/质量检查 | 已完成一次实际整理，结果为 `needs_input`；不等于完整入口验收 |
| DESIGN 确认 | 未验收，原始记录未进入该关卡 |
| PM 对设计规格的业务理解与任务分解 | 未验收 |
| PLAN 关卡与依赖物化 | 未验收 |
| 真实模型驱动的实际工具执行 | 未验收 |
| 示例业务产品已开发并验收 | 否，不得作此声明 |

## 4. 两产品与业务变更测试的准确含义

“健康监测 + 用药提醒”和“高校社团报名与活动管理”测试使用不同的**预置 scripted 分解结果**。

它们验证：

- 不同预置任务内容能保留各自业务来源和依赖；
- `管理员逐条审核 → 满足条件后自动通过` 的预置任务内容在下游计划中发生变化；
- 涉及需求源、描述、写集和验收来源的任务内容没有被固定模板替代。

它们不证明真实模型已经理解两种产品、识别业务变更或生成可验收的业务系统；系统也没有据此真实开发并验收示例产品。

## 5. 页面控制与状态映射

| 控制 | 调用 | 状态来源 | 主要测试 |
| --- | --- | --- | --- |
| 想法入口启动 | `POST /projects`、`POST /projects/{id}/runs` | `stage`、`status`、事件 | 后端 idea 回归、PR22 浏览器测试 |
| 设计规格整理 | `POST /projects/{id}/design-runs` | `design_input_status`、`missing/errors/checks` | 导入后端测试、mock 与真实 HTTP 浏览器测试 |
| DESIGN/PLAN 确认 | `POST /runs/{id}/gates/{gate_id}` | `gates[]`、`baseline_*`、`stage` | 重复/并发确认、真实 HTTP 页面闭环 |
| 调度执行 | `POST /runs/{id}/schedule` | `tasks[].state`、运行事件 | 依赖、并发、重复调度、真实 HTTP 页面闭环 |
| 暂停/恢复/终止 | `POST /runs/{id}/pause|resume|terminate` | `paused`、`status`、事件 | 后端控制与前端 control 测试 |
| 重新连接 SSE | 新建同一运行的 SSE，并重新拉取历史及当前查询 | 连接状态与运行状态分离 | `useRunEvents` 单测 |
| 验收 | `POST /runs/{id}/accept` | 集成回归与交付结果 | 后端验收测试 |

任务阻塞文案：

- 普通依赖未完成：`等待依赖：T-02`。
- 失败/取消等依赖：`失败依赖阻塞：T-02（failed）`。
- 合法重试成功后，`blocked_by/waiting_on` 和页面提示随刷新后的真实状态更新。

## 6. 离线复现命令

以下命令均不得发起真实模型请求；完整启动说明见 `frontend/tools/README.md`。

```bash
# 后端（uv 不在 PATH 时，可使用仓库已有虚拟环境）
cd Test3/backend
uv run pytest -q -m "not live"

# 前端
cd Test3/frontend
npx tsc --noEmit
npm test
npm run build

# mock 浏览器交互
UI_PLAYWRIGHT_MODULE=/tmp/hexagraph-e2e/node_modules/playwright \
  node scripts/verify-design-spec.cjs

# mock 逐按钮表（操作 / 请求 / 反馈 / 状态 / 截图）
UI_PLAYWRIGHT_MODULE=/tmp/hexagraph-e2e/node_modules/playwright \
  node scripts/verify-design-spec-acceptance.cjs

# 真实后端 + 真实前端 + scripted provider（需先按 README 启动两个服务）
UI_PLAYWRIGHT_MODULE=/tmp/hexagraph-e2e/node_modules/playwright \
  node scripts/verify-design-spec-http.cjs
```

`tests/prototype/test_dashscope_smoke.py` 整体标记为 `live`，其中会构造 `DashScopeProvider`；`-m "not live"` 用于排除它。其他测试仍须保持显式 scripted/fake provider。为避免自动读取本地 `.env`，全量后端验证应在不含 `.env` 的干净工作树执行。

## 7. 当前验收边界

- PR23 的离线流程和本轮三个交互修复可以继续接受代码审核。
- mock 浏览器结果不能替代真实 HTTP 页面闭环；本轮已补齐后者。
- scripted 离线执行成功不能替代真实模型任务分解和实际工具执行。
- 真实模型能力仍需组长授权后另行验收，本轮不宣称通过。

## 8. 2026-11-16 展示稳定性 Task 5

计划写下的 pre-fix 基线（前端 11 测 + tsc；后端 138 过 / 1 失败）**不是**本轮结果。空队列失败用测试夹具 `test3_scripted_fixture=""`（空字符串，关闭 study-room 自动灌队列；不是环境值 `none`）复现为 `POST /runs` 400，已在测试夹具灌入 `scripted_m1_queue()`，断言未删。

本轮未沙箱回归：后端 `179 passed, 1 deselected`；前端 `tsc` + `89 passed / 11 files`。逐按钮 mock 表 10 行见 `docs/superpowers/evidence/task-5-click-log.md`。真实 HTTP scripted 覆盖成功路径的暂停/恢复/调度与缺项刷新；驳回 DESIGN 因离线队列只有一次成功导入，只在 mock 点击。离线成功 ≠ 真实模型通过。

## 9. 首版关闭条件（P7）

首版关闭以真实、可打开的 PR 为准。当前记录仍是 `BLOCKED`（缺少 C.7 `github_write`，`github_pr_url=null`），关闭校验按设计失败：

- 关闭门槛测试：`Test3/backend/tests/unit/test_pr_record_not_blocked_as_done.py::test_real_p1_pr_record_is_complete`
- 校验函数：`assert_pr_record_complete`
- 证据与待办：`Test3/docs/plans/P7-report.md` 的「关闭节」

本指针不改变上面历史验收口径；真实 PR 由父代理在整期独立验收通过且用户授权后幂等创建，再更新记录并重跑关闭校验。

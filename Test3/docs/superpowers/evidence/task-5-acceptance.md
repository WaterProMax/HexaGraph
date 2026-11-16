# Task 5 验收记录（展示稳定性）

日期：2026-11-16。分支 `feat/display-stability-ux`。离线成功 ≠ 真实模型通过。

## 基线（计划写下的 pre-fix，不是本轮结果）

计划原文：前端 11 项测试 + `tsc` 通过；后端 138 通过 / 1 失败。那是 Tasks 1–4 之前的基线，不能当成修复后数字。

`test_health_and_project_flow` 的空队列失败在默认 `TEST3_SCRIPTED_FIXTURE=study-room` 下会被 `_prepare_scripted` 自动灌队列掩盖。本轮用测试夹具 `test3_scripted_fixture=""`（空字符串，关闭 study-room 自动灌队列；不是环境值 `none`）复现：

- 断言仍在：`assert run_res.status_code == 200`
- 实际：`400 != 200`（`start_idea` 碰到空 `ScriptedProvider`）
- 修复：测试夹具显式 `ScriptedProvider(scripted_m1_queue())`，并在本测试关掉 auto-fill。未删断言。

## 本轮自动回归（post-fix）

沙箱内 `pytest -m "not live"` 会因 git worktree 把任务标成 `failed`（约 19 条）。按计划在未沙箱环境重跑：

```
cd Test3/backend && uv run pytest -q -m "not live"
179 passed, 1 deselected in 19.95s
```

```
cd Test3/frontend && npx tsc --noEmit && npm test
tsc 无输出（通过）
Test Files  11 passed (11)
Tests  89 passed (89)
```

自动测试重点均有覆盖：注入短截止时间 / 假计时器、重复提交、刷新恢复、超时与迟到结果、终止后不能成功、六类错误、409 正文解析、原文恢复、入口选择、按钮禁用、操作反馈。新增：空文/超限/上传本地校验、连点整理、恢复失败 toast、DESIGN 驳回保留原文、页签内容。

## 页面逐按钮

必须点击，不能只用 HTTP。记录见 `task-5-click-log.md`，截图在 `docs/design/screenshots/design-spec-accept-*.png`。

| 覆盖 | 环境 |
| --- | --- |
| 上传 / 空文超限 / 连点整理 / 等待刷新超时 / 驳回 DESIGN / 批准 DESIGN·PLAN / 暂停调度恢复 / 页签 / 失败留原因 | mock 浏览器 `verify-design-spec-acceptance.cjs`（10 行全过） |
| 批准 DESIGN·PLAN、暂停不派发、恢复后调度、页签、缺项路径、刷新 | 真实 HTTP + scripted `verify-design-spec-http.cjs`（本机通过） |
| 驳回 DESIGN | 仅 mock。离线队列每次只有一次成功导入，HTTP 成功路径不能再耗一次做驳回。 |
| 真实 10 分钟超时 | 未在浏览器里空等。后端用 `import_timeout_s=0.08`；前端用假时钟；mock 刷新后写入 `failed` + `timeout` 类别。 |

## 仍需人工演示的部分

自动化已点击计划表各行（mock），HTTP 走通成功+缺项+暂停恢复调度。人工演示仍建议按 `docs/Demo.md` 复位后看 toast 与预置标签，因为截图是 headless、且 mock ≠ 真实页面网络时序。

未做：付费真实模型导入。原始真实记录仍是 `needs_input`，不得把离线成功写成真实通过。

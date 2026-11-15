# Test3 对照 ImplementationPlan 第 23 章

「通过」只表示本轮有对应自动化证据。「未做」不是隐晦的通过。

| # | 标准 | 本轮 |
|---|---|---|
| 1 | P00–P17 验收项全过，`make lint` / `make test` / `make e2e` 成功 | `pytest -m "not live"`：**138 passed**。`make lint` 的 format/mypy 仍被 `\|\| true` 忽略 |
| 2 | replay 走通 E1–E10；真实联调至少一次且有记录 | 设计规格真实模型探测有记录（`RealModelTest-design-spec-self-study.json`）：整理成功但 `needs_input`，未进 PLAN；**未**声称分解成功。无 E1–E10 replay |
| 3a | 讨论规则以第 11 章为金标准 | 通过（既有单测） |
| 3b | 评审通过与分流 | 通过（既有） |
| 3c | 任务图检查 | 通过；本轮补空图/重复编号/自依赖 |
| 3d | 调度、完成条件、失败分类 | 通过；本轮 `test_schedule_dependencies` 覆盖 A/B/C/D、暂停/终止/重复调度 |
| 3e | 控制可用状态 | 通过（既有） |
| 3f | 变更分级与影响 | 既有 + 设计规格规则变更 scripted 对比 |
| 3g | 反馈分流 | 既有；本轮未扩 |
| 4 | 信息边界、写集、命令白名单、密钥不进日志 | 通过；密钥未进前端/Git |
| 5 | 任务状态只有 `transition()` 一处修改 | **未满足**（历史债） |
| 6 | 控制台可演示任务图、证据、暂停、重试、变更、反馈 | 设计规格入口可操作到调度；浏览器 mock 证据见 Progress |
| 7 | 文档与实现一致，偏差已记录 | Progress / API / 本文件已记限制 |
| 8 | 没有空函数冒充完成 | 导入失败不写已确认产物；真实调用失败不静默回退 preset |

## 设计规格闭环（本轮专项）

| 项 | 结果 |
|---|---|
| 空文本 / 100 KiB 超限拒绝 | 通过（`test_design_input`） |
| 合法输入 → 可确认 SPEC/DESIGN，不自动建任务 | 通过 |
| 缺项停在 needs_input | 通过 |
| 非法模型输出不留已确认产物 | 通过 |
| DESIGN→PLAN 确认幂等 | 通过 |
| 非法任务图不进入执行 | 通过（`check_task_graph`） |
| A/B/C/D 依赖与暂停/终止/去重调度 | 通过（`test_schedule_dependencies`） |
| 审核→自动通过变更比较业务内容 | 通过（`test_design_input_change`） |
| 浏览器：闭环 + 缺项/生成失败/任务失败 | 通过（mock API） |
| 真实模型根据输入整理 SPEC/DESIGN | 通过（`generation=model`，F1–F5/M1–M4）；因缺项未进 PLAN，任务分解未跑 |

## 本轮绑定命令

```text
cd Test3/backend
uv run pytest -q -m "not live"
cd ../frontend && npx tsc --noEmit && npm test
UI_PLAYWRIGHT_MODULE=$PWD/tools/node_modules/playwright \
  UI_BASE_URL=http://127.0.0.1:5173 \
  node scripts/verify-design-spec.cjs
```

# Test3 阶段记录

证据只记本轮实际跑过的命令。未跑的项标「未跑」。

## 设计规格工作流（本轮）

- **起点提交**：`2d46abf`（`feat/design-spec-workflow` 自 `origin/teamwork-001`）
- **目标**：设计规格输入 → SPEC/DESIGN 整理 → DESIGN/PLAN 确认 → 依赖调度 → 页面展示；不重写现有编排器

### 命令与结果

```text
$ git rev-parse HEAD   # 工作开始时
2d46abf7f9024312d7ce00f5e36e099c635d9f27

$ cd Test3/backend && uv run pytest -q -m "not live"
138 passed, 1 deselected

$ cd Test3/frontend && npx tsc --noEmit && npm test
# tsc 无错误；control.test.ts 1 passed

$ UI_PLAYWRIGHT_MODULE=Test3/frontend/tools/node_modules/playwright \
  UI_BASE_URL=http://127.0.0.1:5173 \
  node Test3/frontend/scripts/verify-design-spec.cjs
PASS happy path: design import → DESIGN → PLAN → schedule
PASS missing input stops before planning
PASS generation failure surfaces error
PASS task failure detail + SSE disconnect alert
PASS no browser runtime errors
```

说明：Cursor 沙箱禁写 `.git/hooks` 时，依赖 git worktree 的调度测试会假失败；上表数字在无沙箱环境下取得。

### 真实性区分

| 步骤 | 方式 | 证据 |
|---|---|---|
| 计划/文档生成（回归） | 预置 scripted | `test_design_input.py`、`test_design_input_change.py`；`provenance.generation=preset` |
| 任务执行（回归） | 模拟工具调用 | `test_schedule_dependencies.py`（A→B/C→D） |
| 浏览器闭环 | mock `/api/` | `verify-design-spec.cjs`（不消耗模型） |
| 真实模型分解 | DashScope 探测 | 见下；**未**静默回退为预置任务 |

### 真实模型探测

环境有 `DASHSCOPE_API_KEY`。一次 `create_design_run(self-study-room.md)`：

- `provenance.generation=model`，模型 `qwen3.8-max-0902`
- 结果 `status=failed`，错误暴露为 SOCKS 代理缺少 `socksio`（本机代理环境问题）
- **没有**回退成 preset 任务图后显示“生成成功”
- 记录：`docs/RealModelTest-design-spec-self-study.json`
- 取消代理后的重试长时间无响应已中止；**不声称真实分解已成功**

### 示例输入与变更

- `examples/design-specs/self-study-room.md`：座位、时段、冲突、预约/取消
- `examples/design-specs/club-signup.md`：活动、名额、截止、**管理员审核**、导出
- `examples/design-specs/club-signup-auto.md`：同上但改为**满足条件后自动通过**
- 变更对比（scripted）：`test_design_input_change.py` 比较 F4 来源/标题/依赖，不以任务数量为唯一依据（两版均为 7 任务）

### 演示步骤（对照）

1. 工作台切换「从设计规格开始」，粘贴或读取 Markdown  
2. 「整理并检查」→ 查看结构化 SPEC/DESIGN 与缺项；跳过的讨论阶段显示「不适用」  
3. 确认 DESIGN → 分解停在 PLAN；确认 PLAN → 调度；点任务查看状态/等待原因/错误  
4. 异常：空文/超限、缺项、生成失败、任务失败、事件断开均应显式提示  

### 已知限制

- 真实模型端到端分解在本环境因代理未完成；可控输出与编排已有自动化证明  
- 浏览器脚本依赖本机 Chrome + `frontend/tools` 内 Playwright，未写入产品 `package.json`  
- 设计规格入口跳过讨论仅为 UI「不适用」标注，后端仍从 stage 5 起步  

---

## 历史命令（更早轮次）

```text
$ cd Test3/backend && uv run pytest -q -m "not live"
# 曾记录 94 passed；已被本轮 138 取代，勿混用
```

## P00–P17

| 阶段 | 状态 | 证据 |
|---|---|---|
| P00 工程与模型配置 | 落地 | `Makefile`、`pyproject.toml`、`config/models.yaml` |
| P01–P12 | 见历史实现 | 既有单测/e2e |
| P08 任务分解 | 增强 | `POST /design-runs`、`spec_importer`/`design_importer`、`check_task_graph` 空图/重复/自依赖 |
| P10 编排 | 增强 | 调度锁、终止迟到结果、`test_schedule_dependencies` |
| P13–P14 前端 | 增强 | 设计规格入口组件；mock 浏览器脚本 |
| P15 变更 | 增强 | 社团审核→自动通过 scripted 对比 |
| P17 文档 | 本文件 + Acceptance + API | 含真实性区分与限制 |

## M1（想法入口，未改）

`tests/e2e/test_m1_study_room.py`：scripted 想法 → 讨论 → SPEC 关卡（完整流程入口仍保留）。

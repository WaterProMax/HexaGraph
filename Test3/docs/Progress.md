# Test3 阶段记录

## 2026-11-15 设计规格工作流修复与证据口径校正

- 本轮修复分支：`fix/design-spec-workflow-validation`，基于 PR23 head `87a23cdf6606430b135725f186637726f4accb2f`。
- Acceptance 已分开记录 mock 浏览器、scripted＋真实 HTTP、真实模型＋实际工具执行三类证据。以下历史条目只表示当时执行记录，不代表当前真实模型能力验收。
- 原始 `RealModelTest-design-spec-self-study.json` 保持不改：真实模型整理返回 `needs_input`，停在阶段 5；真实 PM 分解、PLAN 和调度仍未验收。
- 两产品及“管理员审核→自动通过”只验证预置不同分解结果的下游处理，不证明真实模型理解业务变更，也不证明示例业务产品已开发验收。
- 本轮新增真实 HTTP 页面闭环已实际通过：页面完成 DESIGN/PLAN 确认与调度，T-01/T-02 到达 `done`，刷新读取一致；缺项路径无关卡、无任务且刷新一致。
- 本轮离线复测（修复分支工作树，未调用真实模型）：
  - 后端 `pytest -q -m "not live"`：**139 passed, 1 deselected**
  - 前端 `npx tsc --noEmit`、`npm test`（11 passed）、`npm run build` 通过
  - mock 浏览器 `verify-design-spec.cjs` 与真实 HTTP `verify-design-spec-http.cjs` 均通过（HTTP 成功 run `0c4557c9-…`，缺项 run `065efe6b-…`）
  - 合成版本（teamwork-001 + 本修复 + PR22）结果见最终提交报告
- 没有运行付费真实模型，没有伪造 DESIGN/PLAN 或真实调用记录。

---

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

环境有 `DASHSCOPE_API_KEY`。对 `examples/design-specs/self-study-room.md` 调用 `create_design_run`（`qwen3.8-max-0902`）：

1. 首次：本机 SOCKS 代理导致 `status=failed`（缺 `socksio`），错误直接返回，未静默回退 preset  
2. 取消代理后重试成功走到模型整理：`status=needs_input`，`generation=model`  
   - 产出功能 F1–F5、模块 M1–M4（标题与自习室预约相关，非社团案例）  
   - 因缺项与 SPEC/DESIGN 检查未通过，**未建 DESIGN 关卡、未进入任务分解**  
   - 记录：`docs/RealModelTest-design-spec-self-study.json`  

结论：可证明「模型确实根据输入做了整理」；因停在缺项，**不声称**已完成真实模型任务分解与调度。

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

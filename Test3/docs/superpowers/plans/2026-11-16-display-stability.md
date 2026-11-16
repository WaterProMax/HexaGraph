# HexaGraph 展示稳定性修改计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让“上传设计规格 → 确认设计 → 分解任务 → 调度与交互”能够稳定展示，遇到失败也能明确处理。

**Architecture:** 保留 `design-runs` 与现有运行实体；导入尽快返回 `run_id` 并后台整理；前端用既有 run/artifacts 查询更新；错误结构化分类；离线演示标注预置并匹配样例；不新建 job 平台或第二套任务图。

**Tech Stack:** FastAPI + Workbench runtime（snapshot 持久化）、React/Ant Design Workstation、scripted 离线演示。

**Baseline:** 本机 `teamwork-001` @ `e517b79`。PR 目标 `teamwork-001`。对照 [PR #25](https://github.com/WaterProMax/HexaGraph/pull/25) 复用持久化，不另起运行存储。

## Global Constraints

- 不加新业务功能；不重写编排器；不建通用后台任务平台；不建第二套任务图。
- 真实导入总时限 **600 秒**（含两次整理、网关重试、备用）；假计时器测，不真实等 10 分钟。
- 取消本地任务 ≠ 供应商停止计费；AbortController ≠ 后端取消。
- 不把密钥、Authorization、底层异常原文返回前端。
- 离线成功 ≠ 真实模型通过；预置结果必须持续标注。
- 功能分支提交；不合入 `main`；不顺便合并他人 PR。
- 测试：先复现再修；不删断言凑绿。回归：`uv run pytest -q -m "not live"`；`npx tsc --onEmit` / `npm test`。

---

## 任务 1：整理等待、超时和重复提交

**Files:**
- Modify: `Test3/backend/app/api/routes.py`
- Modify: `Test3/backend/app/services/runtime.py`
- Modify: `Test3/backend/app/schemas/design_input.py`
- Modify: `Test3/frontend/src/components/DesignSpecInput.tsx`
- Modify: `Test3/frontend/src/components/DesignSpecPreview.tsx`
- Modify: `Test3/frontend/src/pages/Workstation.tsx`
- Modify: `Test3/frontend/src/api/client.ts`（409 保留类别／摘要／已有 run_id）

**验收**
- 慢请求很快拿到 run_id；刷新仍见整理中。
- 连点只一次导入；断开不自动再开一轮。
- 超时明确原因，无 DESIGN 关卡；迟到结果不覆盖终态。
- 终止取消导入任务；服务重启不永远 importing（识别中断，允许重提，不要求续跑模型）。

- [ ] **Step 1:** 写失败测试：导入 ASAP 返回 `importing`+`run_id`；同项目冲突 409；600s 超时终态；迟到结果忽略；terminate 取消；restore 中断 importing。
- [ ] **Step 2:** 实现后台导入、artifacts 步骤／起止时间、去重、取消、恢复最小处理。
- [ ] **Step 3:** 前端：整理中文案+已等待时间、禁重复提交、轮询既有接口、超时提示、冲突转原运行；Abort 只停等待。
- [ ] **Step 4:** 跑相关后端／前端测试并提交。

## 任务 2：错误分类和提示

**Files:** gateway/providers/runtime；DesignSpecPreview/Input；api/client（若任务 1 未完成 409）

至少区分：连接失败、鉴权失败、限流、超时、文档缺项、输出结构不合法。保留 `errors[]`/`message`。错误常驻页面。

- [ ] 假造六类错误测试 + UI 标题／下一步正确。
- [ ] 实现结构化错误类别；不把一切归为结构检查失败。
- [ ] 提交。

## 任务 3：原文恢复与按钮状态

**Files:** DesignSpecInput、Workstation、新增 DesignSpecInput.test.tsx

- design_spec 运行默认「从设计规格开始」；从 artifacts 恢复原文；失败可改后重提（新运行）；按钮按后端状态启用；操作有成功／失败反馈。

- [ ] 测试 + 实现 + 提交。

## 任务 4：离线演示一致

**Files:** design_spec_http_server、调度提示、演示说明／示例入口

- 主演示用 `self-study-room.md`；社团文档不冒充生成座位任务；持续预置标注；后端暴露调度模式；手动模式文案「请点击调度执行」；复位说明；队列限制写清。

- [ ] 测试／文档 + 实现 + 提交。

## 任务 5：自动测试与逐按钮验收

- 补齐回归；先修 `test_health_and_project_flow` 空队列（若仍红）；页面逐按钮记录操作／请求／反馈／状态／截图。
- [x] 跑全量离线回归 + 写验收记录 + 提交。

## 提交顺序（与上文任务对齐）

1. 导入可查询、总时限、去重和取消保护（+ 409 解析）
2. 前端整理状态、错误分类与原文恢复
3. 按钮启用规则和操作反馈
4. 离线来源、样例、调度提示与复位说明
5. 自动回归、逐按钮验收记录和演示说明

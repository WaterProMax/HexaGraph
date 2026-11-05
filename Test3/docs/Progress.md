# Test3 阶段记录

证据只记本轮实际跑过的命令。未跑的项标「未跑」。

## 命令

```text
$ cd Test3/backend && uv run ruff check app tests
All checks passed!

$ cd Test3/backend && uv run pytest -q -m "not live"
.......................................................                  [100%]
# 55 passed（collect-only 分文件：unit 44 + integration 4 + e2e 6 + prototype 1）

$ cd Test3 && make e2e
# 等同 pytest tests/e2e：6 passed

$ make check-models
# 未跑（本环境无 DASHSCOPE_API_KEY）

$ make test-live
# 未跑
```

`make lint` 中 `ruff check` 已绿；`ruff format --check` 与 `mypy app` 在 Makefile 里是 `|| true`，不作为通过门。

```text
$ cd Test3/frontend && npm test
✓ src/control.test.ts (1 test)
Test Files  1 passed (1)

$ curl -sS http://127.0.0.1:8765/api/health
{"status":"ok"}

# 本机 scripted 夹具连续两次 HTTP 走完 M1 至关卡 SPEC基线确认
# 争议状态 I-01/02/05/06/07=采纳，I-03/04=待定
# 再批准 SPEC：400 scripted queue empty（设计/分解未灌队列，不假装成功）
```

未做浏览器点击验收；前端只跑了 vitest。

## P00–P17

| 阶段 | 状态 | 证据 |
|---|---|---|
| P00 工程与模型配置 | 落地，百炼探测未跑 | `Makefile`、`pyproject.toml`、`config/models.yaml`、`.env.example`；`check-models.py` 无密钥时打印 `no-key` |
| P01 模式/配置/编号/转换表 | 落地 | `tests/unit/test_core_tables.py`（6） |
| P02 事件/存储/API/SSE | 部分 | 内存事件 + FastAPI；DB/EventBus 有集成测试。HTTP 主路径不持久化 |
| P03 网关与 Agent | 落地（scripted） | `tests/unit/test_tools_llm_agents.py`、`test_info_boundary.py` |
| P04 讨论纯函数 | 落地 | `tests/unit/test_discussion_rules.py`（13），金标准 11.4 |
| P05 想法+讨论 | 落地 | `test_m1_study_room_scripted` |
| P06 方案/评审/SPEC/关卡 | 落地 | 同上，走到 `SPEC基线确认` |
| P07 追溯+设计 | 检查与 API 有，全流程薄 | `check_design`、`TraceGraph`；`run_design` 无两位设计评审 |
| P08 任务分解 | 检查有，全流程薄 | `check_task_graph`、`run_plan`；无 scripted 分解队列 |
| P09 工作区与沙箱 | 落地 | `test_git_smoke`、`command_allowed`、工作树 |
| P10 编排 | 部分 | 调度/分类/修复轮/控制有单测；执行会跑验收命令；任务状态未统一走 `transition()` |
| P11 验收 | 函数有 | `acceptance_pass`；无完整执行后验收 e2e |
| P12 控制/待办/预算 | API+函数有 | 乐观锁、待办、预算；`tokens_used` 从网关统计累加（scripted 多为 0） |
| P13 前端基础页 | 页面有 | `App.tsx` 路由；未跑 Playwright |
| P14 任务图/时间线 | 页面有 | `@xyflow/react` 依赖在 `package.json`；无浏览器 e2e |
| P15 变更 | 分级函数+API | `classify_cr`、提交 CR；「扫码进教室」端到端未做 |
| P16 监听 | 导入流水线有 | `test_import_study_room_feedback`；聚类用字符和向量，不是 embedding 槽 |
| P17 综合/文档 | 文档补齐，E1–E10/真联调未做 | 本文件与 README / API / Acceptance / Handoff / Demo |

## M1

`tests/e2e/test_m1_study_room.py`：scripted 队列驱动想法检查 → 讨论（I-01/05/06/07 采纳，I-03/04 待定）→ 方案 → 四维评审 → SPEC（含 I-03/I-04 开口、功能来源含 I-02、功能标题不含「门禁」）→ `SPEC基线确认`。

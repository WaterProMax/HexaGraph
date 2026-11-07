# Test3 阶段记录

证据只记本轮实际跑过的命令。未跑的项标「未跑」。

## 命令

```text
$ cd Test3/backend && uv run ruff check app tests
All checks passed!

$ cd Test3/backend && uv run pytest -q -m "not live"
........................................................................ [ 82%]
...............                                                          [100%]
# 87 passed（含 M1–M11：关卡驳回、并发合并回滚、JSONL 恢复、工具协议、白名单、令牌并发、CR 1.2、设计评审、文档重写循环、冲突 worktree 往返、想法→验收长跑）

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
| P02 事件/存储/API/SSE | 部分 | `emit` 写 JSONL + snapshot + EventBus；启动恢复并 `recover_tasks`。SQLite 双写未做 |
| P03 网关与 Agent | 落地（scripted） | `tests/unit/test_tools_llm_agents.py`、`test_info_boundary.py`；工具 schema/`tool_call_id` 已校验 |
| P04 讨论纯函数 | 落地 | `tests/unit/test_discussion_rules.py`（13），金标准 11.4 |
| P05 想法+讨论 | 落地 | `test_m1_study_room_scripted` |
| P06 方案/评审/SPEC/关卡 | 落地 | 同上，走到 `SPEC基线确认` |
| P07 追溯+设计 | 落地（scripted） | `run_design` 调 `review_arch`/`review_quality`，不通过走 `route_design_review` |
| P08 任务分解 | 落地（scripted） | `check_task_graph`、`run_plan`；`scripted_full_queue` 含分解与两任务 |
| P09 工作区与沙箱 | 落地 | `test_git_smoke`、`command_allowed`、工作树 |
| P10 编排 | 落地（scripted） | 状态经 `_set_state`→`apply_transition`；merge 锁包住回归回滚；冲突后 `worktree remove` |
| P11 验收 | 函数有 | `acceptance_pass`；未通过生成缺陷变更单（最多 2 轮）；通过确认后打 `build-<版本>` 并导出 `release/` |
| P12 控制/待办/预算 | API+函数有 | 乐观锁、待办、预算；takeover/submit-takeover；终止需 `confirm=true`；5 秒调度兜底 |
| P13 前端基础页 | 页面有 | `App.tsx` 路由；未跑 Playwright |
| P14 任务图/时间线 | 页面有 | `@xyflow/react` 依赖在 `package.json`；无浏览器 e2e |
| P15 变更 | 落地（scripted） | 批准增量重写受影响条目，版本 1.1→1.2，驳回 `rejected`；stale 等到调度 |
| P16 监听 | 导入流水线有 | `test_import_study_room_feedback`；embedding 失败走 `cluster_fast` |
| P17 综合/文档 | 文档补齐，E1–E10/真联调未做 | 本文件与 README / API / Acceptance / Handoff / Demo |

## M1

`tests/e2e/test_m1_study_room.py`：scripted 队列驱动想法检查 → 讨论（I-01/05/06/07 采纳，I-03/04 待定）→ 方案 → 四维评审 → SPEC（含 I-03/I-04 开口、功能来源含 I-02、功能标题不含「门禁」）→ `SPEC基线确认`。

`tests/e2e/test_contract_must.py::test_idea_to_acceptance_exports_release`：同一夹具再批准 SPEC/DESIGN/PLAN，跑完两任务，验收导出 `code/`、`trace.json`，标签 `build-1.0`。

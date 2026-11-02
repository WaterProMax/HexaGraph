# Task Plan — LangGraph 六人编排 demo

```yaml
TASK_ID: HEXA-4-orchestration-demo
MODE: Mode 2 (Brownfield / Scoped Dev)
SCALE: M
CONTRACT_PATH: docs/contract.md
TASK_PLAN_PATH: docs/tasks/xxkingzyy-langgraph-orchestration-demo.md
PHASE_STATUS: Phase 2 完成，Phase 3 待 PR 合并
OWNER: XXkingzyy
ISSUE: WaterProMax/HexaGraph#4
```

## 1. In-Scope（本轮做什么）

1. `orchestration/` 包：State 定义、六个节点、图装配、CLI 入口。
2. 两条条件回流：契约门禁打回契约官、评审打回实现官。
3. 六条可执行不变量检查，附 pytest 用例。
4. 交付文档：`Architecture.md`（架构理解）与 `docs/dev-doc.md`（开发文档）。

## 2. Non-Goals（本轮明确不做）

- **不接大模型**：节点全部为确定性规则，运行不依赖任何 API Key；LLM 节点的接入不在本轮验收范围。
- **不做 HTTP 服务层**：无 FastAPI/Flask 路由，入口只有 CLI。
- **不做持久化**：checkpoint 使用 `MemorySaver`，进程退出即丢；未接 SQLite/Postgres。
- **不做并发分支**：图中无 fan-out 并行节点，全部串行 + 两处回流。
- **不做鉴权与多租户**。

## 3. File Whitelist（允许新增/修改的文件）

```
AGENTS.md
Architecture.md
README.md
requirements.txt
.gitignore
docs/contract.md
docs/dev-doc.md
docs/tasks/xxkingzyy-langgraph-orchestration-demo.md
orchestration/__init__.py
orchestration/state.py
orchestration/nodes.py
orchestration/graph.py
orchestration/cli.py
orchestration/tests/__init__.py
orchestration/tests/test_graph.py
```

白名单外文件一律不改。`.venv/` 不进版本库（见 `.gitignore`）。

## 4. 分步验证命令

**Step 1｜依赖可装**

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

**Step 2｜主链路可跑（应输出 `最终结论 : accepted`）**

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli
```

**Step 3｜不变量与图结构**

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest orchestration/tests -q
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli --mermaid
```

## 5. 验收项与证据

| # | 验收项 | 通过标准 | 证据产出 |
| --- | --- | --- | --- |
| A1 | 主链路可跑通 | CLI 退出码 0，结论 `accepted` | CLI stdout |
| A2 | 体现 State + 多 Node 流转 | trace 中出现 8 条节点记录、含 2 次契约官 | CLI stdout / `test_trace_order_follows_graph` |
| A3 | 条件边真实生效 | `gate_rounds == 2` 且契约版本 `v2` | `test_gate_actually_reworked_once` |
| A4 | 不变量真实执行 | 6 项全 PASS，且负向用例可判 FAIL | `test_all_invariants_pass`、`test_verifier_rejects_illegal_transition` |
| A5 | 状态可持久化 | 同一 `thread_id` 可 `get_state` 回收终态 | `test_checkpoint_persists_final_state` |
| A6 | 兜底路径可用 | 无业务词需求仍能走完全流程 | `test_unknown_requirement_falls_back_to_defaults` |

**已知未验证边界**：未验证并发写入、未验证跨进程 checkpoint、未验证 LLM 节点接入、未做性能压测。

## 6. 交付物

- 代码：`orchestration/`（781 行，含测试）
- 架构理解：`Architecture.md`
- 开发文档：`docs/dev-doc.md`（按 writing-skill 写法）
- PR：本分支 `feat/xxkingzyy-langgraph-orchestration-demo`

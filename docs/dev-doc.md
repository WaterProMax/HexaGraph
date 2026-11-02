# 开发文档 — LangGraph 六人编排 demo

**读者**：HexaGraph 负责人
**对应 Issue**：WaterProMax/HexaGraph#4
**文档口径**：本文所有命令输出均为 2026-11-02 在本机一次连续执行的真实结果，未经改写；
所有「代码位置」均指本分支 `feat/xxkingzyy-langgraph-orchestration-demo` 的实际行号。

---

## 1. 交付物与可核验入口

| 交付物 | 路径 | 形态 |
| --- | --- | --- |
| 编排代码 | `orchestration/{state,nodes,graph,cli}.py` | 781 行（含测试） |
| 行为测试 | `orchestration/tests/test_graph.py` | 11 个用例 |
| 契约 | `docs/contract.md` | State / 节点 / 路由 / 不变量 / 变更分级 |
| 任务计划 | `docs/tasks/xxkingzyy-langgraph-orchestration-demo.md` | 范围、白名单、验收项 |
| 架构理解 | `Architecture.md` | 我对 LangGraph 的整体模型 + 本仓库映射 |
| 仓库规则 | `AGENTS.md` | 长期红线与真源层级 |

三条命令即可核验全部结论：

```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli          # 主链路
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest orchestration/tests -q  # 不变量
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli --mermaid    # 图结构
```

实测环境：Python 3.13.14 / langgraph 1.2.19 / langchain-core 1.7.3 / pytest 9.2.0。

---

## 2. 契约 → 实现 → 验证 的三联对照

这一节是本文的核心：**每一条契约条款，都能同时指到实现位置与验证方法**。任何一格缺失，就说明这一条没交付。

| 契约条款（`docs/contract.md`） | 实现位置 | 验证方式 |
| --- | --- | --- |
| `trace` 用 `operator.add` 归约（§2） | `state.py:57` | `test_trace_order_follows_graph` 断言 8 条轨迹顺序 |
| 其余字段后写覆盖（§2） | `state.py:26-58` | 契约版本从 v1 递增到 v2，未被历史值污染 |
| 六个节点各自职责（§3） | `nodes.py:49/90/144/260/298/383` | `test_graph_has_six_business_nodes` |
| 门禁五项检查（§3） | `nodes.py:144-176` | `test_gate_flags_missing_fields` 断言 5 个原因码 |
| 路由三岔 + 上限 3/2（§4） | `graph.py:25-26, 32-47` | `test_router_unit_paths` 断言 6 种输入 |
| 六条数据不变式（§5） | `nodes.py:298-380` | `test_all_invariants_pass`、`test_verifier_rejects_illegal_transition` |
| 回流真实发生（§4） | 图结构上的两条环 | `test_gate_actually_reworked_once` |

**对照结论**：契约中 7 类条款全部有实现与验证，无「写了但没实现」的空条款。

---

## 3. 验收证据（逐条）

### A1 · 主链路可跑通 → 通过

```text
$ python -m orchestration.cli ; echo exit=$?
...
实体        : order
字段        : order_no, amount, status, updated_at
契约版本    : v2
门禁轮次    : 2（上限 3）
评审轮次    : 1（上限 2）
最终结论    : accepted
...
验收：6/6 项不变量通过 · 结论 accepted
exit=0
```

### A2 · State + 多 Node 流转 → 通过

真实轨迹（CLI 输出原文）：

```text
intake             实体=order，字段=3 个，操作=create,cancel,get
contract_architect v1 · 首版契约
contract_gate      第 1 轮 · 打回 CHECK_AUDIT,CHECK_TERMINAL
contract_architect v2 · 按反馈修复 CHECK_AUDIT,CHECK_TERMINAL
contract_gate      第 2 轮 · 通过
implementer        依据契约 v2 生成 66 行源码
verifier           6/6 项不变量通过
reviewer           第 1 轮评审 · 通过
```

8 条记录覆盖 6 个节点，其中契约官与门禁各出现 2 次——这是状态回流留下的物理痕迹。

### A3 · 条件边真实生效 → 通过

`gate_rounds == 2`、`contract.version == 2`、`contract_architect` 出现 2 次（`test_gate_actually_reworked_once`）。
若把 `route_after_gate` 改成恒返回 `pass`，该用例立即变红——说明它测的是路由本身，不是巧合。

### A4 · 不变量真实执行 → 通过

```text
[PASS] create_valid_order         status=created
[PASS] reject_missing_field       字段缺失: amount
[PASS] idempotent_duplicate       count=1
[PASS] reject_illegal_transition  非法状态迁移: cancelled -> cancelled
[PASS] audit_field_written        updated_at=T2
[PASS] reject_unknown_record      '记录不存在: NOPE'
```

负向自检：把契约里终态的 `transitions` 改成 `{"cancelled": ["cancelled"]}`（即允许终态自我迁移），
`reject_illegal_transition` 立刻判 FAIL（`test_verifier_rejects_illegal_transition`）。
这条证明**检查项不是恒真断言**。

### A5 · 状态可持久化 → 通过

同一 `thread_id` 二次访问，`app.get_state(config).values["verdict"] == "accepted"`
（`test_checkpoint_persists_final_state`）。

### A6 · 兜底路径可用 → 通过

输入「随便做个东西」（不含任何业务词）时，`spec.entity == "resource"`、
字段回落 `biz_no / amount`，流程仍走完并 `accepted`
（`test_unknown_requirement_falls_back_to_defaults`）。

### 测试总览

```text
$ python -m pytest orchestration/tests -q
...........                                                              [100%]
11 passed in 0.55s
```

---

## 4. 三个关键实现决策

### 4.1 契约门禁独立成节点，而不是契约官里的一个 `if`

**证据**：`nodes.py:144`（门禁）与 `nodes.py:90`（契约官）是两个独立纯函数，互不 import。
**收益**：门禁规则可被单独喂数据测试（`test_gate_flags_missing_fields` 只构造一个空契约即可），
打回原因作为独立事件进入 `trace`，可复盘。
**代价**：多一次节点往返，图变复杂——但换来的是「裁判」与「运动员」的分离。

### 4.2 首版契约刻意不完整

**证据**：`nodes.py:107-114`，首版契约的 `terminal_states` 初值为 `[]`，且字段表里不含 `updated_at`。
**理由**：如果首版一次通过，rework 边永远不会被走到，那段逻辑就是**从未被验证的死代码**。
现在每次运行都必然经过「打回 → 修复 → 通过」，回流路径成为可断言事实。

### 4.3 契约驱动代码生成，而不是手写一个类

**证据**：`nodes.py:182-248`（模板）、`nodes.py:251`（渲染）、`nodes.py:286`（受控执行）。
**理由**：让「契约」真正成为唯一真相——契约少了 `updated_at`，生成出来的代码就真的不写审计字段，
验证官会当场发现。一致性是被机制逼出来的，不是靠自觉。
**代价**：使用 `exec` 执行生成源码，属 demo 级做法（见 §5）。

---

## 5. 偏差与边界（明确不做的部分）

| 项 | 现状 | 影响 |
| --- | --- | --- |
| 大模型节点 | **未接入**，六个节点均为确定性规则 | 证明的是编排骨架，不是多智能体协作质量 |
| HTTP 服务层 | 未做，只有 CLI | 不能当后端服务直接部署 |
| 持久化 | `MemorySaver`，进程内 | 进程退出即丢；不支持跨进程恢复 |
| 并发分支 | 图中无 fan-out / fan-in | 未验证「同一步内并行节点」的合并语义 |
| 代码生成方式 | `exec` 受控命名空间执行 | 生产应落盘再 import，或改用工具链 |
| 性能 | 未压测 | 无吞吐/延迟数据，文中也未声称任何性能指标 |

以上六项均**未在任何地方声称已完成**。文中出现的「通过」只对应第 3 节列出的六条验收项，不扩展到其他能力。

---

## 6. 复现步骤

```bash
git clone https://github.com/WaterProMax/HexaGraph.git
cd HexaGraph
git checkout feat/xxkingzyy-langgraph-orchestration-demo

python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt      # Linux/macOS 用 .venv/bin/python

PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest orchestration/tests -q
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli --mermaid
```

换成自己的需求：

```bash
./.venv/Scripts/python.exe -m orchestration.cli "做一个库存接口，字段有订单号、金额，支持创建、查询"
```

---

## 7. 两个 skill 在本次交付里怎么用的

| skill | 用在哪 | 具体痕迹 |
| --- | --- | --- |
| `dev-skill` | 契约先行流程 | 先落 `AGENTS.md` + 任务计划 + `docs/contract.md`，再写业务代码；文件白名单写在任务计划里；验收项在写代码前就定义好（任务计划 §5） |
| `writing-skill` | 证据纪律 | 本文每条结论都指向 `file:line` 或真实命令输出；第 5 节显式列边界，不用「完整」「生产可用」这类无对象、无边界的强词；`Architecture.md` 里的架构图由代码导出而非手绘 |

一处刻意的取舍：`writing-skill` 要求把「计划 / 验收目标 / 实测结果 / 已验证结论」四者分开。
本文第 3 节只放**实测结果**，第 5 节只放**边界**，宣称性表述一律收敛到「哪一条验收项通过」为止。

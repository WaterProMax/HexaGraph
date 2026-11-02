# 编排契约（CONTRACT_PATH）

> 本文件是本 demo 的**唯一真相**。`orchestration/` 下的字段名、状态枚举、路由分支、
> 检查项名称必须与本文 100% 一致；不一致以本文为准并修改代码。

## 1. 目的与范围

用一条**确定性**的 LangGraph 编排，把一句话需求推进到「有契约、有实现、有不变量证据、有结论」的交付态。
范围只覆盖编排层本身（State / Node / Edge / 检查口径），不覆盖 HTTP 层、数据库与鉴权。

## 2. State 契约

`OrchestrationState`（`orchestration/state.py:26`），字段如下。写入者一列即「谁有权写这个字段」。

| 字段 | 类型 | 写入者 | 归约方式 | 语义 |
| --- | --- | --- | --- | --- |
| `requirement` | `str` | 入口 | 覆盖 | 一句话需求原文 |
| `spec` | `dict` | intake | 覆盖 | 实体、字段、操作 |
| `contract` | `dict` | contract_architect | 覆盖 | 契约正文（含版本号） |
| `gate_feedback` | `list[str]` | contract_gate / reviewer | 覆盖 | 打回原因码；空列表即通过 |
| `gate_rounds` | `int` | contract_gate | 覆盖 | 门禁已执行轮次 |
| `implementation` | `dict` | implementer | 覆盖 | 生成源码与元信息 |
| `checks` | `list[dict]` | verifier | 覆盖 | 每条不变量检查结果 |
| `review_rounds` | `int` | reviewer | 覆盖 | 评审已执行轮次 |
| `verdict` | `pending / accepted / rejected` | reviewer | 覆盖 | 最终结论 |
| `trace` | `list[TraceEntry]` | 全部节点 | **追加（`operator.add`）** | 审计轨迹，见 `state.py:57` |

**约定**：除 `trace` 外全部为「后写覆盖」。因此每个节点必须一次写回完整字段值，
不允许「读自己的旧值再做增量拼接」的隐式累积——累积语义只允许出现在 `trace` 上。

## 3. 节点契约

| 节点 | 角色 | 必需输入 | 产出 | 判定 |
| --- | --- | --- | --- | --- |
| `intake` | 需求官 | `requirement` | `spec` | 无业务词时回落默认字段 `biz_no / amount` |
| `contract_architect` | 契约官 | `spec`、`gate_feedback` | `contract` | 首版只写最小契约；按反馈码逐项修复 |
| `contract_gate` | 契约门禁 | `contract` | `gate_feedback`、`gate_rounds` | 五项检查全通过才算通过 |
| `implementer` | 实现官 | `contract` | `implementation` | 依据契约渲染可执行源码 |
| `verifier` | 验证官 | `contract`、`implementation` | `checks` | 六条不变量逐条执行 |
| `reviewer` | 评审官 | `checks` | `verdict`、`review_rounds` | 全通过才 `accepted` |

## 4. 路由契约

| 决策点 | 条件 | 分支 | 目标 |
| --- | --- | --- | --- |
| `contract_gate` 之后 | `gate_feedback` 为空 | `pass` | `implementer` |
| | 非空且 `gate_rounds < 3` | `rework` | `contract_architect` |
| | 非空且 `gate_rounds >= 3` | `fail` | `END` |
| `reviewer` 之后 | `verdict == accepted` | `accept` | `END` |
| | 否则且 `review_rounds < 2` | `rework` | `implementer` |
| | 否则 | `fail` | `END` |

上限常量：`MAX_GATE_ROUNDS = 3`、`MAX_REVIEW_ROUNDS = 2`（`orchestration/graph.py:25-26`）。
两条回流边构成本图的两个环，上限是防止状态机死循环的唯一手段。

## 5. 数据不变式（验证官执行口径）

| 检查名 | 断言 | 失败含义 |
| --- | --- | --- |
| `create_valid_order` | 合法载荷创建后 `status == created` 且字段值保真 | 正常路径写入异常 |
| `reject_missing_field` | 缺必填字段抛 `ValueError` | 校验缺失，脏数据可入库 |
| `idempotent_duplicate` | 同幂等键二次提交不新增、不覆盖 | 幂等失效，可能重复扣款 |
| `reject_illegal_transition` | 终态二次迁移抛 `ValueError` | 状态机可被绕过 |
| `audit_field_written` | 创建/迁移后 `updated_at` 存在 | 审计链断裂 |
| `reject_unknown_record` | 查询不存在记录抛 `KeyError` | 空对象被当成功返回 |

检查项名称是契约的一部分，改名等于改契约（见 §6 L2）。

## 6. 变更分级

| 级别 | 内容 | 处理 |
| --- | --- | --- |
| **L1** | 节点内部实现、日志文案、局部重构 | 直接改，测试须仍全绿 |
| **L2** | State 字段增删、检查项名称、路由分支名 | 先改本文件，再改代码与测试 |
| **L3** | 编排拓扑（增删节点/改变环）、验收口径 | 需人工确认后才可动 |

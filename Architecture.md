# 我对 LangGraph 与后端编排的理解

## 1. Demo 要解决的问题

这个 Demo 用请假申请说明后端编排如何根据输入状态执行校验、选择处理分支并返回结果。它不是完整的请假服务：目前从 Python 调用 `graph.invoke()`，没有 HTTP 接口、数据库或真实教师审批交互。

## 2. 我理解的核心模型

用一句话概括 LangGraph 编排：

> **Node 返回数据更新 → State 合并更新 → 路由函数读取 State，选择下一步。**

这几个部分各自负责不同的事情：

- **State** 是一次图运行共享的数据。它既包含调用方传入的请假信息，也逐步包含节点生成的校验结果和处理结果。
- **Node** 读取当前 State，执行一项处理，并返回需要更新的字段。节点返回的是更新字典，不必重新返回整个 State。
- **Edge** 表示执行顺序或下一步的连接。普通 Edge 表示固定连接；条件 Edge 会在指定节点运行后调用路由函数，再按路由结果选择目标节点。
- **路由函数** 根据当前 State 返回目标节点名，负责“选路”，不负责像业务 Node 那样产生 State 更新。
- **编排** 是把 State、Node 和 Edge 组装为图，让 LangGraph 按连接执行，并把各节点返回的更新合并到 State。

最初我把“函数返回字典”和“State 已经变化”当成一件事。练习后我理解到，普通 Python 函数被单独调用时只会返回字典；由 LangGraph 执行节点时，图运行器才会把这个局部更新合并进共享 State。当前图没有为字段配置自定义 reducer，因此同名字段由后续更新覆盖；没有被更新的字段继续保留。

## 3. 从输入到结果的整体架构

```text
调用方
  |
  | graph.invoke(初始 State)
  v
START
  |
  v
validate_leave (Node: 校验输入并更新 valid / message)
  |
  | 条件 Edge 调用 route_leave (只读 valid / days 并选路)
  |
  +-- valid=False ----------------------> reject ---------> END
  |
  +-- valid=True 且 days <= 3 ----------> direct_pass ----> END
  |
  +-- valid=True 且 days > 3 -----------> teacher_review -> END
                                                             |
                                                             v
                                                    graph.invoke 返回最终 State
```

图的定义分为三个阶段：

1. `StateGraph(LeaveState)` 声明图使用的 State 结构。
2. `add_node` 注册处理节点，普通边和条件边定义节点之间的连接。
3. `compile()` 编译图；调用编译后的 `graph.invoke(input_state)` 才会运行一次图并得到最终 State。

`START` 和 `END` 是图的入口、结束标记，不是本 Demo 编写的业务函数。`route_leave` 也不是一个注册节点；它作为 `validate_leave` 发出的条件边的选择函数运行。

## 4. State 中保存什么

`LeaveState` 使用 `TypedDict` 声明，并设置 `total=False`。因此，类型声明允许字段不是全部出现；必填与格式检查由运行时的 `validate_leave` 执行。

| 字段 | 来源 | 在流程中的作用 |
| --- | --- | --- |
| `name` | 调用方 | 请假人姓名，作为必填信息检查 |
| `start_date` | 调用方 | 开始日期，要求是可由当前日期解析逻辑解析的字符串 |
| `end_date` | 调用方 | 结束日期，要求是可由当前日期解析逻辑解析的字符串 |
| `days` | 调用方 | 请假天数；验证为正整数后用于分流 |
| `reason` | 调用方 | 请假原因，作为必填信息检查 |
| `valid` | `validate_leave` | 表示本次输入是否通过当前校验规则 |
| `message` | `validate_leave` 或处理节点 | 保存校验错误或通过、待审批提示 |
| `status` | 处理节点 | 保存 `rejected`、`approved` 或 `pending` 结果 |

一次有效的两天申请开始时，State 大致是：

```python
{
    "name": "小明",
    "start_date": "2026-11-01",
    "end_date": "2026-11-03",
    "days": 2,
    "reason": "生病",
}
```

`validate_leave` 成功时返回 `{"valid": True}`。LangGraph 合并后，原来的姓名、日期、天数和原因仍在 State 中；接着 `direct_pass` 返回 `status` 和 `message`，图最终返回含有输入与处理结果的完整 State。

## 5. 节点如何协作

| 名称 | 类型 | 读取或执行 | 返回更新 / 结果 |
| --- | --- | --- | --- |
| `validate_leave` | Node | 检查必填字段、日期字符串及日期有效性和先后顺序、天数类型和值 | 失败时返回 `valid=False` 和具体 `message`；成功时返回 `valid=True` |
| `route_leave` | 条件路由函数 | 读取 `valid`，通过后再按 `days` 判断区间 | 返回 `reject`、`direct_pass` 或 `teacher_review` 之一 |
| `reject` | Node | 处理校验失败的申请 | 只返回 `status="rejected"`，因此保留校验节点写入的 `message` |
| `direct_pass` | Node | 处理通过校验且天数不超过三天的申请 | 返回 `status="approved"` 和直接通过提示 |
| `teacher_review` | Node | 处理通过校验且天数超过三天的申请 | 返回 `status="pending"` 和待审批提示 |

条件 Edge 对应的分支规则：

| `validate_leave` 更新后的状态 | `route_leave` 返回 | 后续节点 |
| --- | --- | --- |
| `valid=False` | `"reject"` | 拒绝并保留具体校验提示 |
| `valid=True` 且 `days <= 3` | `"direct_pass"` | 直接通过 |
| `valid=True` 且 `days > 3` | `"teacher_review"` | 标记待审批 |

`validate_leave` 必须先于 `route_leave`：路由依据 `valid` 分支，而这个字段正是验证节点计算并写回 State 的。若在验证前路由，图就没有本次校验结果可读。

## 6. 一次运行是怎样发生的

以姓名、日期、原因完整且 `days=4` 的申请为例：

1. 调用方将输入 State 交给 `graph.invoke()`。
2. 图从 `START` 进入 `validate_leave`。
3. 验证节点确认必填字段非空、日期符合格式且顺序正确、天数为正整数，返回 `{"valid": True}`。
4. LangGraph 将 `valid=True` 合并进原 State。
5. `validate_leave` 后的条件 Edge 调用 `route_leave`。路由函数读取 `valid=True` 和 `days=4`，返回 `"teacher_review"`。
6. 图执行 `teacher_review`，把 `status="pending"` 和“等待老师审批”提示合并进 State。
7. 该分支连接到 `END`，`graph.invoke()` 返回最终 State。

非法申请则会由验证节点将 `valid` 设为 `False` 并给出错误 `message`。路由函数据此选择 `reject`；拒绝节点只改 `status`，所以原错误提示不会被通用拒绝提示覆盖。

## 7. 当前实现边界

- `teacher_review` 只是返回 `pending` 后结束本次图运行；它没有暂停等待教师、接收审批决定或恢复执行。
- 日期通过 `datetime.strptime(..., "%Y-%m-%d")` 解析有效性和先后顺序；该实现没有严格要求月份、日期必须补足两位，因此提示中的 `YYYY-MM-DD` 不等于严格的字符串格式校验。
- `days` 只检查为正整数，不校验是否与日期跨度相等，也没有定义自然日或工作日算法。
- 姓名和原因没有强制类型检查；当前代码只对字符串去除首尾空格后判断是否为空。
- 没有规定原因长度、最长请假天数、节假日规则或实际组织的审批政策。
- Demo 展示的是本地后端图编排，不包含 API、持久化、鉴权、部署或并发控制。

## 8. 口头讲解

> 调用方把请假信息作为初始 State 传给编译后的图。图先运行 `validate_leave`，节点返回的 `valid` 和错误提示等局部更新由 LangGraph 合并到 State。接着条件 Edge 调用 `route_leave`，它读取 `valid` 和 `days` 选择拒绝、直接通过或待审批节点。被选中的 Node 再返回状态更新，图合并后到达 `END` 并返回最终 State。这里的待审批目前只是 `pending` 标记，还没有实现真正的人工暂停和恢复。

## 9. 我用来核对理解的依据

官方 Graph API 文档把图描述为共享 State、Nodes 和 Edges：Node 读取 State 并返回更新，Edge 决定下一步；State 中没有自定义 reducer 的字段默认采用最后一次写入的值。文档也说明图需先编译，再通过 `invoke` 运行。我的核心理解与这些定义一致；具体请假字段和分支规则则以本 Demo 源码为准。

| 本文中的实现说明 | 可核对位置 |
| --- | --- |
| `LeaveState` 字段与 State 类型 | `langgraph_demo.py:6-14` |
| 校验规则及返回的局部更新 | `langgraph_demo.py:34-83` |
| 读取验证结果并选择分支 | `langgraph_demo.py:85-91` |
| Node、普通边、条件边、编译图 | `langgraph_demo.py:93-116` |
| 代表性分支行为的自动化断言 | `test_langgraph_demo.py:7-84` |

参考资料：

- [LangGraph Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [Thinking in LangGraph](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph)
- [LangGraph Quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)

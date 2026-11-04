# 请假审批编排 Demo 开发文档

## 1. 交付说明

本文说明项目的实现范围、LangGraph 编排机制、复现步骤、验证证据和结论边界。它是一个教学性质的本地后端编排示例：输入经校验后按规则进入一个处理分支，并返回更新后的 State。

代码与文档文件：

| 文件 | 作用 |
| --- | --- |
| `langgraph_demo.py` | 定义 `LeaveState`、校验与处理节点、条件路由、图构建和演示输入 |
| `test_langgraph_demo.py` | 对编译后的图执行自动化行为测试 |
| `Architecture.md` | 记录学习者对 LangGraph / 后端编排架构的理解和口述主流程 |

本文按仓库 `skills/writing-skill/SKILL.md` 的证据治理要求组织：实现说明指向源码位置，行为结论由测试或本次运行支持，并明确结论边界。具体采用了该 Skill 的 `writing-workflow.md`、`claim-evidence-contracts.md`、`decision-rules.md`、`narrative-projection.md` 和 `code-verification-workflow.md` 中与工程文档及代码核验相关的规则。

## 2. 实现约定

### 输入与校验

调用方传入 `name`、`start_date`、`end_date`、`days` 和 `reason`。`validate_leave` 检查必填值是否缺失或为空字符串；字符串值在检查前去除首尾空格。日期字段必须是字符串，并交给 `datetime.strptime(..., "%Y-%m-%d")` 解析，开始日期不能晚于结束日期。该解析可拒绝无效日历日期，但不严格要求月份、日期使用两位数字。`days` 必须是大于零的整数，且明确排除 Python 的布尔值。

验证失败时，节点返回 `valid=False` 和对应错误 `message`；验证成功时返回 `valid=True`。当前实现没有强制校验姓名、原因的值类型，没有核对天数与日期跨度，也没有规定节假日或组织审批政策。

### State 与节点更新

`LeaveState` 是一个 `total=False` 的 `TypedDict`。节点返回部分更新字典，LangGraph 把更新合并到当前 State，未更新的输入字段会保留；同名字段由新更新覆盖。`reject` 只返回 `status="rejected"`，因此不会覆盖校验节点提供的错误信息。对应实现位于 `langgraph_demo.py` 的 `LeaveState`、`validate_leave` 和处理节点定义。

### 路由与执行顺序

图的执行关系如下：

```text
START -> validate_leave
           |
           +-- valid=False ------------> reject -> END
           +-- valid=True, days <= 3 --> direct_pass -> END
           +-- valid=True, days > 3 --> teacher_review -> END
```

`route_leave` 是条件边使用的路由函数，不是注册到图里的处理 Node。它读取验证后的 `valid`，并在有效时读取 `days`，返回目标节点名称。图通过 `StateGraph` 注册节点和边、调用 `compile()` 得到可运行图，之后由 `graph.invoke(input_state)` 启动一次运行。

`teacher_review` 只将结果标记为 `pending` 并返回；它不暂停等待教师、不保存检查点，也不支持稍后恢复审批。

## 3. 复现环境与命令

本次验证环境记录：

| 项目 | 值 |
| --- | --- |
| Python | 3.10.2 |
| LangGraph | 1.2.19 |
| 测试框架 | Python 标准库 `unittest` |
| 本机演示目录 | `D:\LangGraph` |
| 复核日期 | 2026-11-04 |

安装依赖：

```powershell
py -3 -m pip install "langgraph==1.2.19"
```

运行演示输入：

```powershell
py -3 -X utf8 .\langgraph_demo.py
```

运行自动化测试：

```powershell
py -3 -m unittest -v
```

Demo 目录尚未提供 `requirements.txt` 或锁文件。安装命令固定 LangGraph 版本以便复现本次测试；如果使用其他 Python 版本或依赖组合，需重新运行测试确认兼容性。

## 4. 验证证据

### 自动化测试

2026-11-04 执行 `py -3 -m unittest -v` 的实际摘要：

```text
Ran 6 tests in 0.026s
OK
```

测试证据与实现主张的对应关系：

| 主张 | 代码证据 | 自动化验证 | 本次结果 |
| --- | --- | --- | --- |
| 有效短假通过校验并进入直接通过分支 | `langgraph_demo.py:22-26, 81-91` | `test_langgraph_demo.py:7-17` 输入 2 天申请，断言 `valid=True`、`status="approved"` | 通过 |
| 有效长假进入待审批状态 | `langgraph_demo.py:28-32, 85-91` | `test_langgraph_demo.py:19-30` 输入 4 天申请，断言 `pending` 和待审批提示 | 通过 |
| 空字符串天数会被作为缺失信息拒绝，并保留字段错误提示 | `langgraph_demo.py:35-50, 16-19` | `test_langgraph_demo.py:32-43` 将 `days` 设为 `""`，断言 `valid=False`、`rejected` 和缺失字段提示 | 通过 |
| 开始日期不能晚于结束日期 | `langgraph_demo.py:59-72` | `test_langgraph_demo.py:45-56` 输入倒置日期并断言拒绝及具体提示 | 通过 |
| 不存在的日历日期会被拒绝 | `langgraph_demo.py:59-66` | `test_langgraph_demo.py:58-69` 输入 `2026-02-30` 并断言拒绝及具体提示 | 通过 |
| 天数必须是正整数，且布尔值无效 | `langgraph_demo.py:74-79` | `test_langgraph_demo.py:71-84` 的 `subTest` 分别输入 `0`、`-1`、`"2"`、`True` | 4 个子用例通过 |

因此，本次有 **6 个 unittest 测试方法、9 个具体输入场景**通过。此证据支持表中列出的局部行为，不等于验证了所有输入组合、真实审批流程或生产环境行为。

### 命令行演示

2026-11-04 执行 `py -3 -X utf8 .\langgraph_demo.py`，进程成功退出并打印三组完整 State。演示输入位于 `langgraph_demo.py:118-122`：

1. 整数 `start_date` 被拒绝，提示开始和结束日期必须是字符串。
2. `2026-02-30` 被拒绝，提示日期无效或格式不正确。
3. 有效日期且 `days=4` 的申请通过校验并得到 `status="pending"`。

运行输出证明这些演示输入在本次本地环境下可执行；自动化测试提供了更稳定的断言。没有据此推断未测试行为。

## 5. 结论与边界

在本次 Python 3.10.2、LangGraph 1.2.19 环境中，6 个自动化测试方法（含 4 个天数子用例）通过，演示脚本也能完成三组图运行。证据支持该 Demo 对已列输入实现 State 更新、条件分流和分支结果返回。

本次验证不支持以下更强结论：

- 教师能在流程中实际审批，或图可以暂停、持久化并恢复；
- 天数与日期跨度、工作日或节假日规则一致；
- 已实现 HTTP API、数据库持久化、鉴权、并发控制、部署或生产级可靠性；
- 对未列出的输入空间、所有业务规则或真实用户效果已完成验证。

自动化测试未配置覆盖率工具，因此不报告覆盖率。若后续需要教师交互，应另行定义审批输入、暂停/恢复方式和持久化边界，再补对应契约与测试。

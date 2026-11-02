# AGENTS.md — 仓库级长期规则

> 本文件只放**长期有效**的约定。当轮任务的范围、白名单与验收项放在
> `docs/tasks/<task-slug>.md`，不要把任务计划写进这里。

## 1. 技术栈与目录结构

- Python 3.11+（本机实测 3.13.14），依赖见 `requirements.txt`，虚拟环境放 `.venv/`（不入库）。
- 编排框架：`langgraph`（实测 1.2.19）。入口统一走 `python -m orchestration.cli`。

```
orchestration/
├── state.py    # State 定义与入口状态构造（唯一状态真相）
├── nodes.py    # 六个节点函数 + 代码模板（纯函数，state -> 局部增量）
├── graph.py    # 图装配、条件路由、上限常量
├── cli.py      # 命令行入口与报告渲染
└── tests/      # 行为级测试
docs/
├── contract.md # 契约（唯一真相）
└── tasks/      # 当轮任务计划
```

## 2. 真源层级

```
运行中的代码与测试 > docs/contract.md > 本文件 > README > 口头约定
```

`CONTRACT_PATH = docs/contract.md`。字段名、枚举、检查项名称、路由分支名以契约为准；
代码与契约冲突时，先确认哪一方是对的，再同步另一方，禁止只改一边。

## 3. 环境与验证约定

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest orchestration/tests -q
```

- Windows 控制台默认 GBK，跑中文输出必须带 `PYTHONIOENCODING=utf-8`。
- 提交前本地必须 `pytest` 全绿；PR 描述里贴真实输出，不贴「应该没问题」。

## 4. 编排层红线

1. **节点是纯函数**：入参 `state`，返回局部增量字典；不写全局变量、不发网络请求、不读环境变量。
2. **跨节点只通过 State 通信**：禁止节点之间互相 import 调用。
3. **每个环必须有上限**：新增回流边时同步新增 `MAX_*_ROUNDS` 常量，否则视为缺陷。
4. **检查项名称属于契约**：改名必须同步 `docs/contract.md` 与测试。
5. **不伪造证据**：文档里的命令输出必须来自真实执行，禁止手写编造。

## 5. 契约变更协议

| 级别 | 范围 | 处理 |
| --- | --- | --- |
| L1 | 节点内部实现、日志文案 | 直接改，测试保持全绿 |
| L2 | State 字段、检查项名称、路由分支名 | 先改 `docs/contract.md`，再改代码与测试 |
| L3 | 编排拓扑、验收口径 | 需负责人确认 |

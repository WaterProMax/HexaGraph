# Test3：多体工作流工作台系统架构

本文说明「从想法到交付」完整工作流（需求阶段第 0–4 步、实现阶段第 5–8 步，以及变更流程和环境监听）要做成的软件系统是什么结构。流程规则、角色边界、通过条件以 [Design.md](Design.md) 为准；本文只回答**用什么模块实现这些规则、模块怎样协作、数据怎样存放**。逐步实施和验收见 [ImplementationPlan.md](ImplementationPlan.md)。

本系统是**全新搭建**的项目，不依赖、不导入 Test1、Test2 的代码。

## 1. 设计范围与基本约定

| 约定 | 内容 |
|---|---|
| 使用者 | 我一个人，本机运行，不做账号体系和多用户权限 |
| 输入 | 一两句话的产品想法；之后导入的用户反馈文本 |
| 输出 | 需求规格、设计规格、任务图、集成分支上的代码、验收报告、变更单、反馈清单 |
| 流程规则 | **程序实现，不由 Agent 决定**：阶段流转、退回分流、通过判定、发言人选择、任务调度、失败分类、变更分级、反馈分流 |
| Agent 的作用 | 在规则划定的范围内产生内容：提问、发言、撰写、评审、编码、提炼。每个 Agent 有固定角色提示词、固定输出结构、固定信息边界 |
| 模型 | 通过阿里云百炼（DashScope）的 OpenAI 兼容接口调用；角色引用「模型槽位」，槽位在配置里映射到实际模型（Design.md 第 20 章） |
| 追溯 | 编号链 I → F/N → M → C → T → A → 文件 → 验收，由程序维护，不由 Agent 编写 |
| 可恢复 | 所有状态变化写入只追加的事件表，进程重启后可以重建状态并继续 |
| 人工介入 | 基线确认、裁决、变更决定、任务控制都通过「待办」和「控制」接口完成，每次操作留痕 |

**不使用现成的 Agent 框架（LangGraph、AutoGen 等）。**这套流程的核心价值在于规则（谁发言、何时结束、怎样退回）必须确定、可测试、可复现；把规则放进框架提供的图或对话抽象里，反而难以逐条用单元测试验证。首版自己实现一个轻量的阶段引擎和调度器，核心规则写成不依赖模型的纯函数。需要时可以在 Agent 运行时一层替换成框架，不影响上层。

## 2. 总体架构

```mermaid
flowchart TD
    UI["前端控制台<br/>总览 · 讨论 · 追溯 · 任务图 · 任务详情 · 时间线 · 预算 · 变更与反馈 · 待办"]
    API["HTTP API 与实时推送（FastAPI + SSE）"]

    subgraph CORE["核心引擎（Python，同一进程）"]
        STAGE["阶段引擎<br/>步骤 0–8 的状态机、基线、人工关卡"]
        DISC["多体讨论引擎<br/>三轮讨论、发言人选择、争议清单"]
        DOCS["文档流水线<br/>方案、评审、规格、设计、任务分解及各自的检查"]
        ORCH["任务编排器<br/>调度器、执行器、校验器、集成器"]
        CHG["变更引擎<br/>分级、影响分析、评价、增量更新"]
        LISTEN["环境监听<br/>导入、脱敏、聚类、提炼、评价、分流"]
        TRACE["追溯图服务<br/>编号关系与矩阵、影响范围"]
    end

    subgraph RUNTIME["运行支撑"]
        AGENT["Agent 运行时<br/>角色定义、提示词、结构化输出、校验"]
        GW["LLM 网关<br/>槽位解析、重试、备用模型、限流、计费"]
        WS["工作区管理<br/>git 仓库、任务工作区、合并"]
        SBX["受限执行器<br/>文件工具、白名单命令、超时"]
        EVT["事件总线<br/>追加事件、订阅、恢复"]
    end

    STORE[("SQLite<br/>业务数据与事件")]
    FILES[("文件存储<br/>文档版本、LLM 调用记录、任务工作区、日志")]
    DS["阿里云百炼<br/>OpenAI 兼容接口"]

    UI <--> API
    API --> STAGE
    API --> ORCH
    API --> CHG
    API --> LISTEN
    STAGE --> DISC
    STAGE --> DOCS
    STAGE --> ORCH
    CHG --> DOCS
    CHG --> ORCH
    LISTEN --> CHG
    DISC --> AGENT
    DOCS --> AGENT
    ORCH --> AGENT
    CHG --> AGENT
    LISTEN --> AGENT
    AGENT --> GW
    GW --> DS
    ORCH --> WS
    ORCH --> SBX
    AGENT --> SBX
    STAGE -.-> TRACE
    CHG -.-> TRACE
    ORCH -.-> TRACE
    CORE -.->|追加事件| EVT
    RUNTIME -.->|追加事件| EVT
    EVT --> STORE
    EVT --> API
    CORE --> STORE
    RUNTIME --> FILES
    CORE --> FILES
```

实线表示调用，虚线表示旁路的记录和读取。阶段引擎是主干：它按流程规则决定下一步调用哪个引擎，并在基线和人工关卡处停下等我。所有引擎通过同一套 Agent 运行时和 LLM 网关调用模型，通过同一个事件总线记录发生的事。

### 2.1 依赖方向

自上而下单向依赖，禁止反向：

1. `api` → 各引擎；
2. 各引擎（stage、discussion、docs、orchestrator、change、listening）→ `agents`、`trace`、`workspace`、`storage`、`events`；
3. `agents` → `llm`、`tools`；
4. `llm`、`tools`、`workspace`、`storage`、`events` 不依赖任何引擎。

各引擎之间只通过「产物」和「事件」交接：一个引擎的产物（文档版本、任务卡）写入存储后，另一个引擎再读取；引擎不直接调用另一个引擎内部的函数，只有阶段引擎和变更引擎可以调度其他引擎。

## 3. 后端模块

| 模块 | 职责 | 主要接口 | 不做什么 |
|---|---|---|---|
| `stage` | 步骤 0–8 的状态机；基线冻结；人工关卡；退回计数与分流 | `advance(run)`、`approve_gate()`、`reject_gate()` | 不写文档内容，不调用模型 |
| `discussion` | 想法卡片、三轮讨论、合并编号、发言人选择、结束判定、争议清单 | `run_discussion(run, round_cfg)`；纯函数 `select_speaker()`、`can_finish()`、`validate_utterance()` | 不判断谁对谁错 |
| `docs` | 建设方案、评审、需求规格、设计规格、任务图的生成与检查 | `produce(doc_type)`、`check(doc_type)`、`review(doc_type)` | 不决定退回到哪一步（交给 `stage`） |
| `orchestrator` | 载入任务图，调度，执行任务循环，校验，评审，合并，失败分类，局部重排，恢复 | `start(run)`、`pause()`、`retry()`、`skip()` 等控制接口 | 不修改任务图内容（局部重排通过 `docs` 与我确认） |
| `change` | 变更单生命周期、分级、影响分析、评价、增量更新 | `submit()`、`analyze()`、`decide()`、`apply()` | 不自己决定批准 |
| `listening` | 反馈导入、脱敏、聚类、提炼、已决策去重、评价、分流 | `import_feedback()`、`distill()`、`evaluate()`、`route()` | 不自动创建变更单（需我确认分流） |
| `trace` | 编号注册与关系；矩阵；影响范围查询；一致性检查 | `link()`、`impact(ids)`、`matrix()`、`check()` | 不由 Agent 写入 |
| `agents` | 角色注册表、提示词渲染、输出结构校验、信息边界过滤、调用记录 | `call_agent(role, inputs) -> typed_output` | 不决定流程 |
| `llm` | 槽位解析、百炼客户端、重试、备用模型、限流、令牌与费用统计、重放模式 | `complete(slot, messages, schema)` | 不知道角色和业务 |
| `tools` | Agent 可用的文件和命令工具，写集与命令白名单的强制 | `read_file`、`write_file`、`list_dir`、`search`、`run_command` | 不绕过写集 |
| `workspace` | 运行的 git 仓库、任务分支和工作区、合并、回滚 | `create_task_workspace()`、`merge()`、`diff()` | 不运行 Agent |
| `events` | 事件追加、订阅、按序号读取、状态重建 | `emit()`、`subscribe()`、`replay()` | 不做业务判断 |
| `storage` | 数据库访问、迁移、文档版本存储 | 各表的仓库类 | — |
| `api` | HTTP 路由、请求校验、SSE | — | 不含业务规则 |

## 4. 技术选型

| 层 | 选择 | 理由 |
|---|---|---|
| 后端语言与框架 | Python 3.11 及以上，FastAPI，Pydantic v2，asyncio | 类型清晰，异步调用模型和子进程方便，Pydantic 同时用于接口、数据库行和 Agent 输出的校验 |
| 数据库 | SQLite（WAL 模式），SQLAlchemy 2.x 异步接口，aiosqlite，Alembic 迁移 | 单机、零运维、可以直接用工具查看；事件表和业务表放在同一个库 |
| 模型调用 | `openai` Python SDK 指向百炼的兼容地址，`httpx` 做超时控制 | 百炼提供 OpenAI 兼容接口，换模型只改配置 |
| 子进程与 git | `asyncio.create_subprocess_exec` 调系统 git 和测试命令 | 不引入额外抽象 |
| 配置 | YAML（模型槽位、角色、上限、项目模板）加 `.env`（密钥） | 队友能直接改，密钥不入库 |
| 前端 | React 18、TypeScript、Vite；任务图用 `@xyflow/react`；服务端状态用 TanStack Query；界面库用 Ant Design 5；Markdown 渲染用 `react-markdown` | 任务图和表格是主要界面，成熟库最省事 |
| 实时推送 | Server-Sent Events | 单向推送足够，浏览器自动重连，比 WebSocket 简单 |
| 测试 | 后端 pytest、pytest-asyncio；前端 Vitest 加 React Testing Library；端到端 Playwright | 覆盖规则、接口和关键交互 |
| 包管理 | 后端 `uv`，前端 `npm` | 与之前作业的习惯一致，锁定版本 |

具体依赖版本在搭建阶段验证后锁定，并在 README 中记录 Python、Node 和包管理器版本。

## 5. 核心数据

### 5.1 实体

| 实体 | 关键字段 | 说明 |
|---|---|---|
| `project` | id, name, profile（项目模板名）, created_at | 一个产品想法对应一个项目 |
| `run` | id, project_id, status, current_stage, revision, limits_json, created_at | 一次完整流程；revision 用于控制操作的乐观锁 |
| `stage_run` | id, run_id, stage（0–8）, attempt_no, status, started_at, ended_at, reason | 每一步每次执行一条，退回会产生新的 attempt_no |
| `artifact` | id, run_id, type, version, parent_version, status, content_path, hash, created_by | 带版本的文档：想法卡片、争议清单、建设方案、评审表、SPEC、DESIGN、PLAN、检查报告、验收报告等；旧版本保留 |
| `baseline` | id, run_id, kind（SPEC/DESIGN/PLAN/BUILD）, version, artifact_id, approved_at, approved_note | 冻结的基线 |
| `gate` | id, run_id, kind, status（pending/approved/rejected）, payload_json | 人工关卡与待办的来源 |
| `discussion_msg` | id, run_id, round, seq, role, kind, refs_json, body, tags_json | 第一轮问题、第二轮发言、主持人汇总 |
| `issue` | id, run_id, code（I-xx）, sources_json, proposers_json, category, status, conclusion, supporters_json, opponents_json, basis_type, destination, history_json | 争议清单的行（字段见 Design.md 第 4.7 节） |
| `spec_item` | id, run_id, code（F1、N1…）, kind, title, priority, acceptance, source, version, status | 需求规格中的功能和非功能需求（结构化保存，便于追溯和验收） |
| `module` / `interface` | code（M/C）, name, responsibility, provider, consumers, fields_json, sources_json, version | 设计规格里的模块和接口 |
| `task` | id, run_id, code（T-xx）, card_json, state, revision, depends_json, write_set_json, points, locked_by, plan_version | 任务及其运行状态；card_json 保存任务卡全部字段 |
| `attempt` | id, task_id, code（A-xx）, role, model, started_at, ended_at, outcome, failure_signature, tokens_in, tokens_out, workspace_ref, commit_sha | 任务的一次执行尝试 |
| `evidence` | id, attempt_id, kind（command/review/merge/manual）, summary, path | 命令输出、评审结论、合并记录、人工通过的理由 |
| `llm_call` | id, run_id, attempt_id, role, slot, model, tokens_in, tokens_out, latency_ms, cost, request_path, response_path, status | 每次模型调用；请求和响应正文放文件，不放数据库 |
| `trace_link` | id, run_id, from_code, to_code, kind, version | 编号之间的关系 |
| `change_request` | id, run_id, code（CR-xx）, source, description, level, impact_json, evaluation_json, decision, decision_note, status, from_version, to_version | 变更单 |
| `raw_feedback` | id, run_id, batch_id, source, ts, text_masked, author_hash | 脱敏后的原始反馈 |
| `feedback_item` | id, run_id, code（FB-xx）, category, summary, quotes_json, count, scope_json, basis_type, status, route, linked_issue | 提炼后的反馈条目 |
| `event` | id（自增序号）, run_id, ts, actor, kind, subject, payload_json | 只追加的事件记录 |

### 5.2 版本与基线

文档以「类型加版本号」保存，不覆盖。基线记录指向某个具体版本。变更后同一个 `version`（如 `1.1`）同时用于 SPEC、DESIGN、PLAN，便于对应。任务图的小调整（局部重排）记为 PLAN 的补丁版本，如 `1.1.1`。

### 5.3 追溯关系

`trace_link` 记录有向关系，类型如下：

| 关系 | 含义 |
|---|---|
| `issue → spec_item` | 争议的结论落到某个功能或非功能需求 |
| `spec_item → module` | 模块承担某个需求 |
| `module → interface` | 模块提供或使用接口 |
| `spec_item、interface、module → task` | 任务来自它们 |
| `task → file` | 任务的产出文件（由合并时的实际改动确定，不由 Agent 自报） |
| `spec_item → acceptance_result` | 验收结果 |
| `feedback_item → issue / spec_item / change_request` | 反馈挂到的原条目或产生的变更单 |

关系由两个来源产生：文档里 Agent 填写的「来源」字段（经程序校验编号存在后写入），和程序在合并、验收时自动产生的关系。Agent 填写了不存在的编号，该文档检查失败。

## 6. 阶段引擎

### 6.1 状态机

阶段引擎对一个 run 维护「当前阶段」和每个阶段的状态，转换规则用一张表（代码里的字典）表示，不分散在各处判断：

| 当前阶段 | 事件 | 下一阶段 | 条件 |
|---|---|---|---|
| 0 想法检查 | 检查通过且我确认初步做法 | 1 | 用户、问题、初步做法齐全 |
| 0 想法检查 | 说不清 | 0 | 补充不超过 3 次，超过则 run 暂停等我 |
| 1 多体讨论 | 正常或强制结束且我查看 | 2 | 争议清单完整 |
| 2 建设方案 | 方案通过检查 | 3 | 章节齐全、估算不超容量 |
| 3 多方评价 | 评审通过且我确认 | 4 | 通过规则（Design.md 第 7.3 节） |
| 3 多方评价 | 不通过 | 1 / 2 / 4 / 停止 | 按意见类型分流，退回合计不超过 2 次 |
| 4 需求规格 | 规格检查通过且我确认 | 5 | SPEC 基线冻结 |
| 5 设计规格 | 评审通过且我确认 | 6 | DESIGN 基线冻结；设计类退回不超过 2 次；需求类意见转变更单 |
| 6 任务分解 | 分解检查通过且我确认 | 7 | PLAN 基线冻结 |
| 7 编排与执行 | 全部任务 done 或被跳过 | 8 | — |
| 8 集成验收 | 验收通过且我确认 | 完成 | BUILD 基线冻结；未通过则生成缺陷变更单，不超过 2 个循环 |

**每次转换都是一个事件**，记录原因和依据；不在表中的转换一律拒绝。

### 6.2 人工关卡

关卡是阶段引擎暂停自己的方式：产生 `gate` 记录和一条待办，然后把 run 置为 waiting。我在界面上批准、驳回或附带修改后，接口把结果写回并唤醒阶段引擎。关卡类型：想法补充、初步做法确认、争议清单查看与裁决、评审确认、SPEC/DESIGN/PLAN 基线确认、任务升级处理、验收确认。

### 6.3 阶段执行器接口

每个阶段是一个实现统一接口的执行器：

```text
run(ctx) -> StageOutcome
  ctx:     run 的只读快照、可用服务（agents、artifacts、trace、events）
  outcome: status ∈ {passed, failed, need_human, stopped}
           artifacts：本阶段产生的文档版本
           reason：原因（写入事件）
```

阶段执行器不决定下一阶段，只返回结果；转换由阶段引擎按 6.1 的表完成。这样规则集中，也便于对转换表单独做测试。

## 7. 多体讨论引擎

### 7.1 结构

```mermaid
sequenceDiagram
    participant S as 阶段引擎
    participant D as 讨论引擎
    participant M as 主持人 Agent
    participant R as 讨论角色 Agent（并行）
    participant V as 校验函数
    participant E as 事件总线

    S->>D: 开始第 1 步（想法卡片）
    par 第一轮：背靠背
        D->>R: 想法卡片（看不到他人问题）
        R-->>D: 2–3 个问题（结构化）
    end
    D->>V: 校验数量、字段
    D->>M: 合并问题并编号
    M-->>D: 合并表
    D->>V: 每个 Q 都有去处；争议不超过 8 条
    loop 第二轮，直到结束
        D->>D: select_speaker(state)
        D->>R: 争议清单、已有发言、被点名信息
        R-->>D: 发言（回应对象、观点、理由、标注）
        D->>V: validate_utterance()
        D->>E: 记录发言
        D->>D: can_finish(state)
    end
    D->>M: 第三轮：汇总状态和去向
    M-->>D: 争议清单
    D->>V: 判定条件复核
    D-->>S: 争议清单、合并表、讨论记录
```

### 7.2 规则用纯函数实现

以下函数**不调用模型**，输入是当前讨论状态，输出是确定的结果，必须有完整的单元测试：

| 函数 | 作用 | 对应规则 |
|---|---|---|
| `merge_valid(q_list, merge_table)` | 每个 Q 编号都出现在合并表；合并后不超过 8 条，超出者标「未讨论」 | Design.md 第 4.3 节 |
| `select_speaker(state)` | 按 6 条优先级选出下一位发言者 | 第 4.5 节 |
| `validate_utterance(u, state)` | 回应对象存在；涉及争议不超过 3 个；观点不为空；事实或假设已标注；不是同一角色连续发言；只说「同意」的无效 | 第 4.4 节 |
| `can_finish(state)` | 正常结束的前提 | 第 4.6 节 |
| `must_finish(state)` | 发言达到 20 条 | 第 4.6 节 |
| `finalize_status(issue, state)` | 采纳、撤回、待定、未讨论的判定条件；强制结束时的状态 | 第 4.7 节 |
| `rebuttal_check(issue)` | 依赖假设的结论是否可采纳 | 第 4.7 节「反问检验」 |

主持人 Agent 只做两类事：写文字（合并表的归并理由、追问、小结、汇总），以及在 `select_speaker` 选出的发言人之前**按规则 1** 插话。**选谁发言由函数决定**，Agent 不能自己点名其他人；主持人在追问时写的「请某某回应」会被解析为点名事件，之后由规则 2 处理。第三轮汇总中，Agent 给出的状态由 `finalize_status` 复核，不一致时以函数结果为准并记录差异。

### 7.3 信息边界

`agents` 模块在组装每个角色的输入时，按角色的「可见信息」白名单过滤（Design.md 第 3.3 节）。第一轮的角色拿不到他人的问题；评审角色拿不到讨论记录。**白名单写在配置里，由测试验证：对每个角色构造包含全部信息的输入，断言渲染后的提示词不含不该看到的内容。**

## 8. 文档流水线

建设方案、评审、需求规格、设计规格、任务图的流程相同，因此做成一个通用结构：

```text
produce  (撰写角色 Agent，输出结构化文档，Pydantic 校验)
  → check   (程序检查，确定性规则)
  → review  (评审角色 Agent 背靠背打分，规则判定通过)
  → human gate
```

| 文档 | 撰写角色 | 程序检查 | 评审 | 退回分流 |
|---|---|---|---|---|
| 建设方案 | 方案撰写人 | 章节齐全；估算不超容量；功能清单不超过 12 项；来源编号有效 | 四位评审 | 争议类 → 步骤 1；方案类 → 步骤 2；验证类 → 我决定 |
| 需求规格 | 规格撰写人 | Design.md 第 8.2 节三类检查 | 规格检查员 Agent（只给意见） | 重写，最多 2 次，仍不通过由我修改 |
| 设计规格 | 架构师 | Design.md 第 13.4 节三类检查 | 架构评审、质量评审 | 设计类 → 重写；需求类 → 变更单；验证类 → 探索任务 |
| 任务图 | 任务分解员 | Design.md 第 14.5 节程序检查（无环、覆盖、写集、点数、来源） | 分解检查员 Agent（语义） | 重写，最多 2 次，仍不通过由我修改 |

撰写角色的输出是**结构化数据**（Pydantic 模型），再由程序渲染成 Markdown 保存。这样检查可以直接在数据上做，比如「每个模块有来源」「任务图是否有环」，不需要从文字里解析。

## 9. 任务编排器

### 9.1 任务状态机

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> ready: 依赖全部完成
    ready --> running: 调度器选中
    running --> verifying: 编码完成
    verifying --> running: 缺陷，修复轮未超限
    verifying --> done: 验收通过 评审通过 合并成功
    verifying --> failed: 环境故障或冲突
    running --> failed: 环境故障
    failed --> running: 退避重试 或 换备用模型
    failed --> needs_human: 超过上限
    running --> needs_human: 预算耗尽 或 无进展
    verifying --> needs_human: 超过修复轮
    pending --> blocked: 上游 needs_human 或 failed 或 skipped
    blocked --> pending: 上游恢复
    needs_human --> running: 我重试
    needs_human --> skipped: 我跳过
    needs_human --> done: 我强制通过 证据标为人工
    pending --> cancelled: 终止运行 或 变更作废
    ready --> cancelled
    done --> stale: 变更影响
    stale --> ready: 变更批准后重做
    done --> [*]
    skipped --> [*]
    cancelled --> [*]
```

状态变化只能通过 `transition(task, event)` 一个函数完成，函数内部用转换表校验，非法转换抛错并记录事件；每次转换同时写入 `event`。数据库中的任务状态由该函数更新，**不允许在别处直接 UPDATE**。

### 9.2 调度器

调度器是一个循环（事件驱动加定时兜底），每次唤醒时执行：

```text
schedule_tick(run):
    if run.paused: return
    for task in ready_tasks(run):          # 状态 ready，且依赖都完成
        if task.paused or task.locked_by:        continue
        if conflicts_with_running(task):         continue    # 写集重叠
        if budget_exhausted(run, task):          to_needs_human(task); continue
        if running_count(run) >= run.limits.concurrency: break
        candidates.append(task)
    pick = sort(candidates, key=(-remaining_critical_path, priority, points, code))
    for task in pick until slots are full:
        start_execution(task)
```

关键路径剩余量在任务图载入和每次状态变化后重新计算（对任务图做一次逆拓扑遍历，节点权重为点数）。调度器本身是纯函数加少量状态，可以用构造的任务图直接测试：给定一张图和一组状态，断言选出的任务。

### 9.3 单个任务的执行

```mermaid
sequenceDiagram
    participant O as 编排器（执行器）
    participant W as 工作区管理
    participant A as 编码或测试 Agent
    participant T as 受限工具
    participant C as 校验器（程序）
    participant R as 代码评审 Agent
    participant I as 集成器
    participant E as 事件与证据

    O->>W: 从集成分支建任务分支和工作区
    O->>O: 打包上下文（任务卡、相关接口、依赖产出摘要）
    loop 最多 30 步工具调用
        O->>A: 上下文和上一步工具结果
        A->>T: read_file / write_file / list_dir / search / run_command
        T-->>A: 结果（写集和命令白名单在此强制）
    end
    A-->>O: 完成声明
    O->>W: 提交到任务分支
    O->>C: 运行任务卡里的验收命令
    C-->>O: 退出码、输出、失败特征
    alt 命令失败
        O->>E: 记录证据，进入失败分类
    else 命令通过
        O->>R: 任务卡、接口约定、改动对比、命令输出
        R-->>O: 通过或不通过，意见和是否阻断
        alt 评审不通过
            O->>E: 记录意见，进入失败分类
        else 评审通过
            O->>I: 合并到集成分支并跑回归
            I-->>O: 成功、失败或冲突
            O->>E: 记录合并证据，任务 done
        end
    end
```

要点：

- **上下文只含必要信息**：任务卡、该任务引用的接口约定、依赖任务的产出文件及摘要。不放讨论记录、不放其他任务的执行过程。
- **写集由工具强制**：`write_file` 在执行前检查目标路径是否在任务写集内（规范化路径后做前缀匹配，拒绝 `..`、符号链接逃逸），不在则拒绝并产生事件。命令执行后再用 `git diff --name-only` 复核实际改动，超出写集则本次尝试判为失败，改动丢弃。
- **命令白名单**：`run_command` 只允许项目模板（profile）里列出的命令前缀，如 `pytest`、`python -m`、`ruff`；不经 shell，参数用数组传递；有超时；环境变量清空后只放入必要的几项；工作目录固定为任务工作区。
- **评审 Agent 只读**：给它的是改动对比和命令输出，它没有写入工具。
- **完成由程序判定**：Agent 的「完成声明」只是触发校验的信号，不是结论。

### 9.4 失败分类

失败分类是一个纯函数 `classify(result) -> kind`，输入是命令结果、评审结果、模型调用错误、合并结果：

| 输入特征 | 分类 |
|---|---|
| 模型调用 429、超时、5xx、输出无法解析（重试后仍然） | 环境故障 |
| 命令退出码非 0 且有测试失败输出；评审有阻断意见 | 代码缺陷 |
| 零测试、全部跳过；评审指出验收标准矛盾或依赖缺失；失败特征值与上一轮相同 | 任务描述问题 |
| 合并冲突 | 合并冲突 |
| 上游任务为 needs_human、failed、skipped | 依赖失败 |

**失败特征值**：把命令输出中的时间、路径、内存地址、随机数等去掉（正则归一化），保留错误类型、断言信息和失败的测试名，取哈希。连续两轮相同表示没有进展。

### 9.5 工作区与合并

- 每个 run 有一个独立的 git 仓库：`data/runs/<run_id>/repo`，集成分支 `main`。
- 每次尝试建一个 `git worktree`：`data/runs/<run_id>/wt/<task>-<attempt>`，分支名 `task/<task>`。
- 合并使用 `git merge --no-ff`，**同一时间只有一个合并**（进程内加锁）；冲突时中止合并，生成冲突解决任务（写集为冲突文件，说明里带冲突内容）。
- 合并后在集成分支上运行已完成任务的回归测试；失败则回滚这次合并（`git reset --hard` 到合并前），任务回到失败分类。
- 任务完成后保留分支，不清理，方便回看和接管。

### 9.6 恢复

- 进程启动时扫描 run：状态为 running 或 verifying 的任务，标为 interrupted，写事件，然后回到 ready，使用新的尝试编号；上一次尝试遗留的工作区保留，新尝试从任务分支的最后一次提交开始。
- 合并是否已经发生，以 git 为准：恢复时检查任务分支是否已被合并进集成分支，已合并则直接标 done，不重复合并。
- 所有对外部有副作用的操作（合并、写文件）带幂等键：任务编号加尝试编号。

### 9.7 局部重排

局部重排由 `docs` 模块调用任务分解员，输入是出问题的任务及其下游子图、失败证据；输出新的子图。新子图经过程序检查后产生一个「重排提案」，作为待办等我确认；确认后才替换。替换时旧任务保留为 cancelled，新任务继承已完成的依赖。

## 10. Agent 运行时

### 10.1 角色定义

每个角色是一个声明，放在 `config/roles.yaml` 和 `prompts/` 目录中：

```yaml
moderator:
  slot: flagship
  temperature: 0.2
  prompt: prompts/discussion/moderator.md
  output_schema: ModeratorOutput        # Pydantic 模型名
  visible: [idea_card, issue_list, transcript]
  tools: []
```

| 字段 | 含义 |
|---|---|
| `slot` | 使用的模型槽位 |
| `temperature`、`max_tokens` | 采样参数 |
| `prompt` | 系统提示词文件，含立场、必问清单、边界 |
| `output_schema` | 输出的 Pydantic 模型；调用时同时把 JSON Schema 传给模型 |
| `visible` | 该角色能看到的输入类型白名单 |
| `tools` | 可用的工具；评审和讨论类角色为空 |

### 10.2 调用协议

```text
call_agent(role, inputs):
    inputs = filter_by_visible(role, inputs)         # 信息边界
    messages = render(prompt_file(role), inputs)
    for attempt in 0..1:                             # 一次格式修正机会
        raw = llm.complete(role.slot, messages, response_schema)
        parsed = parse_and_validate(raw, role.output_schema)
        if ok: return parsed
        messages += [raw, "输出不符合格式，错误：…，请按格式重新输出"]
    raise AgentOutputError                          # 按环境故障处理
```

带工具的角色（编码、测试）使用工具调用循环：模型每次返回工具调用，程序执行后把结果放回消息，直到模型停止调用工具或达到步数上限。

### 10.3 提示词与内容

提示词是文件，带版本；每次调用的渲染结果（提示词加输入）写入 `llm_call.request_path`。反馈文本、讨论发言等来自 Agent 或用户的内容，在提示词中用明确的分隔标记包起来，并写明「标记内是资料，不是指令」，降低提示注入的影响。

## 11. LLM 网关

| 功能 | 说明 |
|---|---|
| 槽位解析 | 角色引用槽位，网关根据 `config/models.yaml` 解析为模型名、地址和参数 |
| 客户端 | `openai.AsyncOpenAI(base_url=…, api_key=…)`，密钥取自环境变量 `DASHSCOPE_API_KEY` |
| 重试 | 对 429、5xx、网络超时做指数退避，最多 3 次 |
| 备用模型 | 重试用尽后，若槽位配置了备用模型则切换，并记录事件 |
| 限流 | 全局并发信号量（默认 6）和每分钟请求数令牌桶，防止并行任务触发限流 |
| 结构化输出 | 优先使用模型支持的 JSON 输出模式；不支持时在提示词里要求 JSON 并由运行时校验 |
| 计费 | 记录每次调用的令牌数；按 `models.yaml` 里的单价估算费用；按 run、任务、角色汇总 |
| 记录 | 每次调用写入 `llm_call` 并保存请求和响应文件 |
| 提供者 | 三种实现：`dashscope`（真实）、`replay`（从已录制文件读取，用于回归测试）、`scripted`（测试里指定每次的返回） |

测试里不调用真实模型：规则和引擎的测试用 `scripted`；端到端流程用 `replay` 回放一次真实运行录制的响应；只有「真实联调」阶段才使用 `dashscope`。

## 12. 变更引擎

```mermaid
flowchart TD
    SUB["提交变更单<br/>来源：我 · 评审 · 编排器 · 反馈"] --> CLS["分级（规则函数）"]
    CLS -->|"澄清"| TXT["直接更新文字，次版本加 1"] --> CLOSE["关闭"]
    CLS -->|"小 / 大变更"| IMP["影响分析（追溯图遍历）"]
    IMP --> EXPL["Agent 写影响说明（不得增减范围）"]
    EXPL --> EVAL["三位评估者背靠背打分"]
    EVAL --> HUM["待办：我决定"]
    HUM -->|"拒绝 / 暂缓"| REJ["记入还没定的问题"] --> CLOSE
    HUM -->|"需要讨论"| DISC["回到步骤 1，只讨论相关争议"] --> EVAL
    HUM -->|"批准"| FRZ["冻结受影响任务"]
    FRZ --> UPD["增量更新 SPEC → DESIGN → PLAN<br/>各自经过检查与确认"]
    UPD --> RE["编排器：stale 重做，新任务入队"]
    RE --> VER["追溯检查与受影响验收项重跑"] --> CLOSE
```

- **分级函数** `classify_cr(impact, change_kind)`：依据影响的模块数、是否改变 P0、是否增删功能、是否推翻已采纳争议，返回澄清、小变更或大变更（Design.md 第 18.3 节）。
- **影响分析** `impact(codes)`：在 `trace_link` 上从变更涉及的编号出发，向下游遍历到模块、接口、任务、文件，向上游遍历到争议；再按任务状态得出需重做、需暂停的任务集合，以及点数差值。纯函数，可用构造的追溯图测试。
- **增量更新**：`docs` 模块在原文档基础上只重写受影响的条目（输入是旧版本和变更说明，输出是新版本），然后做 diff；未受影响的条目内容必须与旧版本完全相同，由程序校验。更新后各文档重新做检查，并按顺序产生新的基线确认关卡。
- **并发限制**：同时打开的变更单不超过 3 张；影响范围重叠的提示合并。

## 13. 环境监听

```mermaid
flowchart LR
    IN["导入：粘贴 / 上传 txt、csv、json"] --> MASK["脱敏（规则：姓名、电话、邮箱、学号等）<br/>作者标识哈希"]
    MASK --> DEDUP["完全重复去重"]
    DEDUP --> CLU["聚类（embedding 余弦阈值）<br/>失败时用 fast 模型分批归类"]
    CLU --> DIS["提炼 Agent：每组一条 FB 条目"]
    DIS --> VAL["程序校验：引用存在、条数一致"]
    VAL -->|"不通过"| DIS
    VAL --> KNOWN["已决策去重<br/>对照本版不做、待定、已关闭 CR"]
    KNOWN -->|"已有结论"| LINK["挂到原条目，频次加一，提示我"]
    KNOWN -->|"新问题"| EV["三位评估者背靠背评价"]
    EV --> RT["分流（规则函数）"]
    RT --> HUM["待办：我确认"]
    HUM --> OUT["忽略 · 观察 · 小变更 · 大变更 · 新想法"]
```

**采集器接口**：`Collector.fetch() -> list[RawFeedback]`。首版实现 `ManualCollector`（接收粘贴和文件）；其他渠道只需新增实现，后面的流水线不变。

**提炼的校验**（程序）：条目引用的每个原文编号都必须存在于本批导入；条目的条数等于引用数；摘要不得含有引用原文里没有出现的专有名词（简单检查：摘要中的数字和引号内容必须能在原文中找到）。不通过让提炼 Agent 重写一次，仍不通过标为「需人工看」。

**分流函数** `route(item, scores)`：输入平均分、频次（按不同作者统计）、是否红线、是否已决策、类别，输出去向（Design.md 第 19.4 节）。红线标志来自评估者的结构化输出字段 `red_line: bool`，任何一位为真即升级。

## 14. 事件、实时推送与控制

### 14.1 事件

所有引擎通过 `events.emit(kind, subject, payload)` 记录发生的事。事件表只追加，序号自增，同一 run 内序号严格递增。事件类型按前缀分组：

| 前缀 | 例子 |
|---|---|
| `stage.` | `stage.started`、`stage.passed`、`stage.transition`、`gate.created`、`gate.resolved` |
| `discussion.` | `discussion.message`、`discussion.issue_updated` |
| `doc.` | `doc.produced`、`doc.checked`、`doc.reviewed`、`baseline.frozen` |
| `task.` | `task.state_changed`、`task.attempt_started`、`task.tool_called`、`task.evidence_added` |
| `control.` | `control.paused`、`control.retry`、`control.skip`、`control.takeover`、`control.force_pass`（含操作者、理由、前后版本） |
| `cr.` | `cr.submitted`、`cr.analyzed`、`cr.decided`、`cr.applied` |
| `feedback.` | `feedback.imported`、`feedback.distilled`、`feedback.routed` |
| `llm.` | `llm.call`（指向调用记录）、`llm.fallback` |
| `system.` | `system.recovered`、`system.limit_changed` |

状态重建：任务状态、关卡状态都能由事件序列推出；数据库中的状态字段是它的物化视图，进程启动时校验两者一致，不一致以事件为准并告警。

### 14.2 实时推送

`GET /api/runs/{id}/events` 是 SSE：每条消息的 `id` 是事件序号，浏览器断线重连时带 `Last-Event-ID`，服务端从该序号之后补发。前端先拉取快照（当前任务、关卡、预算），再订阅事件增量更新；收到序号不连续时重新拉取快照。

### 14.3 控制与乐观锁

所有控制接口都带 `expected_revision`（run 或任务的版本号）。服务端在同一个数据库事务里检查版本、执行状态转换、版本加一、写事件；版本不符返回 409，界面提示刷新。控制操作通过与调度器相同的 `transition()` 函数完成，没有旁路。

## 15. HTTP API 总览

| 分组 | 接口 | 说明 |
|---|---|---|
| 项目与运行 | `POST /api/projects`、`GET /api/projects`、`POST /api/projects/{id}/runs`、`GET /api/runs/{id}` | 创建项目和 run（带想法原文与配置覆盖） |
| 运行控制 | `POST /api/runs/{id}/pause`、`resume`、`terminate`；`PATCH /api/runs/{id}/limits` | 全局暂停、继续、终止、调整并发和预算 |
| 阶段与文档 | `GET /api/runs/{id}/stages`、`GET /api/runs/{id}/artifacts`、`GET /api/artifacts/{id}`、`POST /api/artifacts/{id}/edit` | 查看阶段、文档版本；人工修改产生新版本 |
| 讨论 | `GET /api/runs/{id}/discussion` | 第一轮问题表、合并表、发言、争议清单 |
| 待办与关卡 | `GET /api/runs/{id}/todos`、`POST /api/gates/{id}/resolve` | 待办列表；批准、驳回、裁决 |
| 任务 | `GET /api/runs/{id}/tasks`、`GET /api/tasks/{id}`、`GET /api/tasks/{id}/attempts`、`PATCH /api/tasks/{id}` | 任务图、详情、尝试、修改任务卡 |
| 任务控制 | `POST /api/tasks/{id}/pause`、`resume`、`retry`、`skip`、`takeover`、`submit-takeover`、`force-pass` | 见 Design.md 第 16.3 节 |
| 追溯 | `GET /api/runs/{id}/trace`、`GET /api/runs/{id}/trace/impact?codes=` | 追溯图与影响范围 |
| 变更 | `POST /api/runs/{id}/crs`、`GET /api/runs/{id}/crs`、`POST /api/crs/{id}/decision` | 变更单 |
| 反馈 | `POST /api/runs/{id}/feedback/import`、`GET /api/runs/{id}/feedback`、`POST /api/feedback/{id}/confirm-route` | 导入、清单、分流确认 |
| 预算 | `GET /api/runs/{id}/budget` | 令牌、费用、按角色和任务汇总 |
| 事件 | `GET /api/runs/{id}/events`（SSE）、`GET /api/runs/{id}/events/history?after=` | 实时和历史 |
| 模型调用 | `GET /api/llm-calls/{id}` | 查看某次调用的请求和响应 |
| 配置 | `GET /api/config/models`、`PUT /api/config/models`、`POST /api/config/models/test` | 查看和修改槽位、测试连通 |

接口的字段由 Pydantic 模型定义，FastAPI 自动生成的 OpenAPI 文档作为接口的权威说明；`docs/API.md` 只写使用约定和错误码。

## 16. 前端

### 16.1 页面

| 页面 | 内容 |
|---|---|
| 项目列表与新建 | 输入想法，选择项目模板，设置容量和预算 |
| 运行总览 | 步骤 0–8 的进度条、基线版本、待办摘要、预算摘要 |
| 讨论 | 第一轮问题、合并表、第二轮发言流（按序号）、争议清单（状态、去向、依据） |
| 文档 | 各类文档的版本列表、渲染和版本对比；在需要我确认的地方有批准和驳回按钮 |
| 追溯 | 追溯图和矩阵；输入编号查看上下游 |
| 任务图 | `@xyflow/react` 画出 DAG，节点按状态着色，边为依赖；关键路径高亮；侧边为任务详情 |
| 任务详情 | 任务卡、尝试列表、每次尝试的消息和工具调用、改动对比、命令输出、评审意见、令牌与耗时；控制按钮 |
| 时间线 | 事件流，可按类型和对象过滤 |
| 预算 | 总预算与各任务预算、各角色和模型的用量 |
| 变更与反馈 | 变更单列表与详情（含影响分析和评价）；导入反馈、反馈清单、分流确认 |
| 待办 | 所有等我处理的事项集中展示 |
| 设置 | 模型槽位、上限、项目模板；测试连通 |

### 16.2 数据流

```mermaid
flowchart LR
    SNAP["REST 快照<br/>TanStack Query"] --> STORE["本地状态"]
    SSE["SSE 事件流"] --> STORE
    STORE --> VIEW["页面组件"]
    VIEW -->|"控制操作带 expected_revision"| REST["REST 命令"]
    REST -->|"409 冲突：刷新快照"| SNAP
```

页面先拉取快照，再用事件增量更新；断线重连后从最后事件序号补齐。控制按钮按任务状态启用或禁用（可用状态见 Design.md 第 16.3 节），点击后以服务端返回为准，不做乐观更新。

## 17. 配置

```text
config/
├── models.yaml        # 槽位 → 模型、参数、单价、备用模型
├── roles.yaml         # 角色 → 槽位、温度、提示词、输出结构、可见信息、工具
├── limits.yaml        # 并发、轮数、预算、超时等默认上限
└── profiles/
    └── python-pytest.yaml   # 项目模板：语言、命令白名单、测试命令、目录结构
.env                   # DASHSCOPE_API_KEY（不入库）
```

`limits.yaml` 里和执行、验收有关的默认值以 Design.md 第 15.10、17.4 节为准：任务并发 6，每个任务修复 6 轮，每点 150 万令牌，P1 通过线 90%。完整键值见 ImplementationPlan.md 附录 D。

`models.yaml` 示例（槽位名固定，模型名和能力字段由队友核对后填写；完整字段见 ImplementationPlan.md 第 3.3 节）：

```yaml
provider: dashscope
base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
api_key_env: DASHSCOPE_API_KEY
limits: { max_concurrency: 6, requests_per_minute: 120 }
slots:
  flagship:     { model: qwen3-max,        temperature: 0.3, fallback: qwen-plus,  json_mode: true, tool_calls: true,  extra_body: {} }
  flagship_alt: { model: deepseek-v3.2,    temperature: 0.3, fallback: qwen3-max,  json_mode: true, tool_calls: true }
  coder:        { model: qwen3-coder-plus, temperature: 0.2, fallback: qwen3-max,  json_mode: true, tool_calls: true }
  balanced:     { model: qwen-plus,        temperature: 0.3, fallback: qwen-flash, json_mode: true, tool_calls: false }
  fast:         { model: qwen-flash,       temperature: 0.1, fallback: qwen-plus,  json_mode: true, tool_calls: false }
  embedding:    { model: text-embedding-v4, dimensions: 1024 }
```

`json_mode` 或 `tool_calls` 为 false 的槽位，网关自动降级为「提示词要求 JSON 加运行时校验」或「提示词内描述工具调用格式」；`extra_body` 原样透传给接口（例如关闭某些模型的思考模式）。

槽位和模型的对应原则见 Design.md 第 20 章；这里的模型名只是设计时的推荐，实际可用的名称以百炼控制台为准。

## 18. 目录结构

```text
Test3/
├── Design.md
├── Architecture.md
├── ImplementationPlan.md
├── README.md
├── Makefile
├── .env.example
├── config/                    # 第 17 节
├── prompts/                   # 各角色提示词，按阶段分目录
│   ├── discussion/ docs/ design/ tasks/ execute/ change/ listening/
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── settings.py
│   │   ├── api/               # 路由与 SSE
│   │   ├── stage/             # 阶段引擎与阶段执行器
│   │   ├── discussion/        # 讨论引擎与纯函数规则
│   │   ├── docs/              # 文档流水线、各类检查
│   │   ├── orchestrator/      # 调度器、执行器、校验器、集成器、失败分类
│   │   ├── change/            # 变更引擎
│   │   ├── listening/         # 采集器、脱敏、聚类、提炼、评价、分流
│   │   ├── trace/             # 追溯图服务
│   │   ├── agents/            # 角色注册、提示词渲染、调用协议
│   │   ├── llm/               # 网关与提供者（dashscope、replay、scripted）
│   │   ├── tools/             # 文件与命令工具
│   │   ├── workspace/         # git 仓库、worktree、合并
│   │   ├── events/            # 事件总线
│   │   ├── schemas/           # Pydantic 模型：文档结构、Agent 输出、接口
│   │   └── storage/           # 模型、仓库类、迁移
│   └── tests/
│       ├── unit/              # 纯函数规则：发言选择、通过判定、调度、分类等
│       ├── integration/       # 引擎与存储、git
│       └── e2e/               # 自习室示例整体流程（replay）
├── frontend/
│   ├── package.json
│   └── src/
│       ├── pages/ components/ api/ store/ hooks/
├── examples/
│   └── study-room/            # 自习室示例：想法、预期产物、录制响应、反馈样本
├── data/                      # 运行时数据（不入库）：数据库、文档版本、调用记录、工作区
└── docs/
    ├── API.md  Acceptance.md  Handoff.md
```

## 19. 安全与隐私

| 风险 | 措施 |
|---|---|
| 密钥泄露 | 只从环境变量读取；日志、事件、调用记录中对密钥脱敏；`.env` 在 `.gitignore` 中；提供 `.env.example` |
| Agent 越权写文件 | 路径规范化加写集白名单；拒绝 `..` 和符号链接逃逸；命令执行后用 git diff 再次复核 |
| Agent 执行危险命令 | 命令前缀白名单，不经 shell；清空环境变量；固定工作目录；超时和输出长度限制 |
| 提示注入 | 来自反馈、发言、代码的文本用分隔标记包起来，声明不是指令；这些内容不能触发工具以外的流程动作；流程动作只由程序规则决定 |
| 用户隐私 | 反馈导入时脱敏，作者标识不可逆哈希；Agent 只看到脱敏文本；调用记录中也是脱敏后的内容 |
| 网络访问 | 工作区命令不联网（不放代理变量、不配置网络工具）；依赖安装在项目模板准备阶段完成，不由 Agent 执行 |
| 成本失控 | 并发限制、每任务和总预算、接近 80% 告警、超限暂停 |

首版在本机运行，命令执行的隔离强度是「白名单加受限目录」，不是容器级别；如果要运行不可信的代码，需要增加容器隔离（见 Design.md 第 22 章）。

## 20. 测试策略

| 层级 | 内容 | 要求 |
|---|---|---|
| 单元（纯函数） | 发言人选择、发言校验、结束判定、争议状态判定、合并校验；调度选择、关键路径、失败分类、失败特征值；变更分级、影响分析；反馈分流；写集与命令白名单；转换表 | 每条规则至少一个正例和一个反例；转换表中的每条非法转换都有测试 |
| 集成 | 引擎加存储；工作区的 git 操作（冲突、回滚、恢复）；SSE 的断线补发；乐观锁冲突 | 使用 `scripted` 提供者和临时目录 |
| 端到端（回放） | 用自习室示例，从想法走到验收，再走一次变更和一次反馈；用 `replay` 提供者 | 每次提交可跑，不需要网络 |
| 真实联调 | 使用 `dashscope` 提供者，跑完整示例，保存报告 | 提交验收前至少成功一次，保留调用记录和费用 |
| 前端 | 关键组件（任务图、控制按钮的启用规则、待办）；Playwright 走一遍关键操作 | 暂停、重试、跳过、接管、批准基线都有用例 |

「信息边界」的测试单独列出：对每个角色断言它的提示词里不含不该看到的信息（第 7.3 节）。

## 21. 关键设计决策

| 决策 | 理由 | 代价 |
|---|---|---|
| 规则写成纯函数，Agent 不决定流向 | 可测试、可复现，规则变化只改一处 | Agent 的灵活性受限，需要把规则想清楚 |
| 不用 Agent 框架，自写阶段引擎和调度器 | 规则要逐条验证；框架抽象会把规则藏进图或对话里 | 要自己做恢复、事件、并发 |
| Agent 输出用结构化数据，再渲染成 Markdown | 检查直接在数据上进行；追溯关系可靠 | 提示词和输出模型需要精心设计 |
| 追溯关系由程序维护，编号需校验 | 防止 Agent 编造追溯 | 文档的「来源」字段必须填写 |
| 测试任务和实现任务分角色、分厂商 | 避免自己出题自己做 | 成本更高，需要接口桩先行 |
| 评审与被评审用不同厂商的模型 | 降低自评偏好和同质化附和 | 要同时开通多个厂商的模型额度 |
| 事件表只追加，状态可重建 | 恢复、回看、审计都靠它 | 事件类型多，需要约定 |
| 控制操作乐观锁，不强杀 | 避免基于过期信息操作和中途破坏状态 | 暂停有延迟 |
| SQLite 加文件存储 | 单机、可直接查看 | 不支持多进程写入；首版只单进程 |
| 首版不做外部反馈渠道和容器隔离 | 范围控制 | 见 Design.md 第 22 章，已列为后续 |

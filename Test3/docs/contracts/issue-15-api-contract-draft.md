# Issue #15 接口契约草稿：路径、参数、错误码与实时推送

> **状态**：Draft v0.1（待评审，未冻结）
>
> **起草**：郭婷婷（Issue #15）
>
> **日期**：2026-11-12
>
> **适用范围**：Test3 后端 `backend/app/api/routes.py` ↔ 前端 `frontend/src/api/client.ts`、`frontend/src/hooks/useRunEvents.ts`
>
> **关联真源**：运行中的代码与测试 > `Design.md` > `Architecture.md` > `ImplementationPlan.md` > `docs/contracts/test3-contract.md` > 本文
>
> **落地方式**：评审通过后，本文并入/替换 `docs/API.md` 的对应章节；`docs/API.md` 继续作为索引。

**给组员的 TL;DR**

1. 成功响应直接是 JSON 对象或数组，没有 `{code, data}` 信封；请求体一律 `application/json`。
2. 错误先看 HTTP 状态码（400/404/409/422/500），再看响应体 `code`；**不要解析 `detail` 文案**。乐观锁冲突固定 409。
3. 实时推送是 SSE：帧头 `id: <seq>`、`data` 是事件 JSON；重连由浏览器自动带 `Last-Event-ID`，服务端只回放 `seq > after`。客户端必须按 `seq` 去重、容忍最多 15s 延迟，并检测 `seq` 回退。

---

## 1. 范围

**本文约定**

- HTTP 路径、方法、路径/查询/请求头参数、请求体与成功响应结构。
- 错误码：HTTP 状态、机器码、触发条件、客户端处理建议。
- 实时推送：SSE 帧格式、事件对象、`seq` 语义、`Last-Event-ID` 重放规则。
- 乐观锁：`expected_revision` 比较对象与失败语义。

**本文不约定**

- 业务规则（阶段通过条件、预算上限、评审规则等）——见 `Design.md` 与 `config/limits.yaml`。
- LLM 提示词、模型槽位内容、数据库表结构、鉴权（当前无鉴权）。
- 前端组件结构与视觉。

**当前存储现状（重要）**

HTTP 主路径的运行态、事件都保存在进程内存，并追加写入 `data/runs/<run_id>/events.jsonl`、周期性 `snapshot.json`。SQLAlchemy/Alembic 表与 `EventBus` 有独立集成测试，但**不是**当前 HTTP 事件端点的数据来源。因此：进程重启后事件从 JSONL 恢复，`seq` 通常延续，但不保证连续。

---

## 2. 通用约定

### 2.1 传输与地址

| 项 | 约定 |
|---|---|
| 前缀 | `/api`（所有路径都含该前缀，例如 `/api/runs/{id}`） |
| 开发地址 | 后端 `http://127.0.0.1:8765`；前端 `http://127.0.0.1:5173`，Vite 将 `/api` 代理到后端 |
| CORS | 仅放行 `http://127.0.0.1:5173`、`http://localhost:5173`；其它来源不要依赖浏览器直连 |
| 请求头 | 写操作 `Content-Type: application/json`；SSE `Accept: text/event-stream` |
| 字符集 | UTF-8；中文不转义（`ensure_ascii=False`） |
| 鉴权 | 无。`actor` 由服务端写死为 `owner`/`system`，**客户端不能传、也不能伪造** |
| 时间 | 当前接口契约中没有服务端时间戳字段；不要依赖创建时间/更新时间（见 §9 A-9） |
| 幂等 | 仅 run 级 `pause`/`resume` 近似幂等（重复调用仍 200，但 `revision` 每次都 +1）；其余写操作按状态机拒绝重复 |

### 2.2 成功响应

- 不加 `{code, data}` 信封，直接返回对象/数组/标量。少数接口返回固定包装（如 `{run, result}`、`{started}`），见 §4。
- 成功一律 **HTTP 200**（当前没有 201/202/204）。
- 空集合返回 `[]`，不返回 `null`；可选字段可能缺失，客户端用 `?? 默认值` 兜底。

### 2.3 错误响应

**现状（代码事实）**：所有手工错误都通过 FastAPI `HTTPException` 抛出，响应体只有 `{"detail": "<文案>"}`；Pydantic 校验失败由框架返回 422，`detail` 是数组；未捕获异常返回 500。

**契约目标（v1，评审通过后生效）**

```json
{ "detail": "revision mismatch", "code": "REVISION_CONFLICT" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 稳定机器码，大写下划线；**客户端只依赖它和 HTTP 状态** |
| `detail` | string 或 array | 人类可读说明；422 时保留 FastAPI 的数组结构；**禁止据此做分支** |

兼容期规则：后端补齐 `code` 前，前端可用 `body?.code ?? fallbackByStatus(status)`；补齐后不得再按 `detail` 文案匹配。

**错误码总表**

| HTTP | `code` | 触发条件 | 客户端建议 |
|---|---|---|---|
| 400 | `VALIDATION_FAILED` | 语义不合法：关卡已裁决/重复推进、`force-pass`/`skip` 缺 `reason`、终止未 `confirm`、`limits` 未知键或类型错、变更单不存在（现为 400） | 展示 `detail`，不要自动重试 |
| 400 | `ILLEGAL_TRANSITION` | 当前状态不允许该动作：任务控制动作不在可用表、未知 `action`、阶段非法迁移 | 刷新任务/运行状态后重新判断按钮可用性 |
| 400 | `AGENT_OUTPUT_ERROR` | 模型输出不合约（创建运行、推进关卡时） | 展示，提示稍后重试或换模型槽位 |
| 400 | `FEEDBACK_HASH_KEY_REQUIRED` | 未配置环境变量 `FEEDBACK_HASH_KEY` 时导入反馈 | 提示配置后端环境变量 |
| 404 | `NOT_FOUND` | 项目/运行/关卡/任务/变更单不存在 | 提示资源不存在；可能需要刷新列表 |
| 409 | `REVISION_CONFLICT` | `expected_revision` 与当前 revision 不一致 | 重新 GET 拿最新 `revision`，用户确认后重试一次 |
| 422 | `REQUEST_INVALID` | 请求体/查询串不符合 schema：缺必填字段、类型错、`after` 非整数、缺 `codes` | 属于调用方 bug，修正请求 |
| 500 | `INTERNAL_ERROR` | 未预期异常 | 记日志并上报；不要自动重试写操作 |
| 405 | `METHOD_NOT_ALLOWED` | 方法不匹配 | 修正请求 |

说明：

- 当前没有 401/403（无鉴权），也没有 429（无限流）。
- `400` 的三种业务码在代码里已由 `Test3Error.code` 定义；404/422/500 的 `code` 是本次契约新增（见 §9 A-1）。

**后端领域错误与 HTTP 的映射（现状）**

`app/errors.py` 中的异常类并非都出网，避免误解：

| 异常类 | `code` | 是否出现在 HTTP 响应 |
|---|---|---|
| `ValidationFailed` | `VALIDATION_FAILED` | 是，400 |
| `IllegalTransition` | `ILLEGAL_TRANSITION` | 是，400 |
| `AgentOutputError` | `AGENT_OUTPUT_ERROR` | 是，400 |
| `RevisionConflict` | `REVISION_CONFLICT` | 是，409 |
| `ConfigError` | `CONFIG_ERROR` | 否（启动/配置加载期） |
| `WriteDenied` / `CommandDenied` | `WRITE_DENIED` / `COMMAND_DENIED` | 否（转为任务证据、`task.write_denied` 事件或任务失败） |
| `BudgetExceeded` | `BUDGET_EXCEEDED` | 否（通过 `budget.*` 事件与运行暂停体现） |
| `ReplayMissing` | `REPLAY_MISSING` | 否（离线回放） |

### 2.4 字段与命名

- 一律 `snake_case`；标识字段用 `id`，人类可读编号用 `code`。
- 数字为 JSON number；布尔为 JSON boolean；不要用 `"true"`/`"1"`。
- 业务枚举含中文时**原样传输**（例如变更决定 `"批准"`），客户端不要自行翻译后再回传。
- 未知枚举值必须容错：不认识的 `state`/`kind`/`gate.kind` 按“原样显示 + 不崩溃”处理，禁止 exhaustive switch 无 default。

### 2.5 标识符

| 资源 | 形态 | 生成方 | 备注 |
|---|---|---|---|
| `project_id` | UUID 字符串 | 服务端 | `POST /projects` 返回 |
| `run_id` | UUID 字符串 | 服务端 | `POST /projects/{id}/runs` 返回 |
| `gate_id` | UUID 字符串 | 服务端 | `run.gates[].id` |
| `task.id` | `"{run_id}:{task_code}"` | 服务端 | 全局唯一 |
| `task.code` | 如 `T-01` | PLAN 阶段 | **仅 run 内唯一** |
| `cr.code` | 如 `CR-1` | 服务端自增 | 目标全局唯一（见 §9 A-7） |
| `feedback.id` | 整数自增 | 服务端 | 仅 run 内唯一；跨 run 不可比 |

- `/tasks/{task_id}` 同时接受完整 `id` 或 `code`；由于 `code` 只在 run 内唯一，**客户端请始终传完整 `id`**。
- `/crs/{code}/decision` 目前在所有 run 中按 `code` 查找，存在跨 run 歧义（§9 A-7）；在修复前，前端只对本 run 的 CR 调用。
- 客户端不得自行构造或猜测 id。

---

## 3. 核心对象

### 3.1 `run_view`

`GET /runs`、`GET /runs/{id}`、run 控制接口返回的都是该视图（**不是**完整运行态）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | run id |
| `project_id` | string | 所属项目 |
| `status` | enum | `active` / `waiting` / `done` / `terminated` |
| `stage` | string | 当前阶段 `"0"`–`"8"`，或 `"done"` / `"stopped"` / `"paused"` |
| `revision` | int ≥ 1 | run 级乐观锁版本 |
| `paused` | bool | 运行是否暂停 |
| `idea` | string | 原始想法（可能被“想法补充”追加过文本） |
| `gates` | Gate[] | 全量关卡（含已裁决） |
| `event_count` | int | `len(events)`，**不是**最大 `seq`，不能当游标 |

注意：`run_view` **不包含** `pending_human`、`tokens_used`、创建时间。需要预算调 `/budget`；需要待办调 `/todos`。

`status` 语义：

| 值 | 含义 |
|---|---|
| `active` | 初始运行中，尚未创建过任何关卡 |
| `waiting` | 创建过关卡后进入（现状**不会回落到 `active`**）；是否仍有待办不要看它，看 `gates`/`todos` |
| `done` | 验收通过并已导出交付物 |
| `terminated` | 人工终止；所有未完成任务被取消 |

### 3.2 阶段（stage）

| 值 | 名称 | 值 | 名称 |
|---|---|---|---|
| `"0"` | 想法 | `"5"` | DESIGN |
| `"1"` | 讨论 | `"6"` | PLAN |
| `"2"` | 方案 | `"7"` | 执行 |
| `"3"` | 评审 | `"8"` | 验收 |
| `"4"` | SPEC | `done` / `stopped` / `paused` | 结束 / 中止 / 补充轮次耗尽 |

`GET /runs/{id}/stages` 返回 `{"current": "<阶段>", "history": [{"from","event","to"}]}`；`history` 只记录真正发生的阶段迁移。

### 3.3 任务（task）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | `"{run_id}:{code}"` |
| `code` | string | 任务编号，run 内唯一 |
| `state` | enum | 见下表 |
| `revision` | int ≥ 1 | **任务级**乐观锁版本；控制接口比较它 |
| `card` | TaskCard | 任务卡：`code,title,kind,module,sources,description,inputs,write_set,outputs,acceptance,depends_on,points,priority,role,budget` |
| `repair_rounds` | int | 已修复轮次（上限 6） |
| `signatures` | string[] | 失败签名，用于判定“任务描述问题” |
| `evidence` | Evidence[] | `{kind: command/review/merge/manual, summary, path}` |
| `paused` | bool | 任务级暂停 |
| `locked_by` | string | 接管者；空串表示未接管 |
| `tokens_used` | int | 该任务累计令牌 |
| `prev_output` | string | 上次模型输出摘要 |
| `review_issues` | array | 代码评审问题 |
| `takeover_workspace` | string? | 仅接管后出现，工作树绝对路径 |

`state` 取值（11 个）：

| 值 | 含义 |
|---|---|
| `pending` | 未满足依赖 |
| `ready` | 依赖满足、可调度 |
| `running` | 执行中 |
| `verifying` | 评审/验证中 |
| `done` | 完成 |
| `failed` | 环境/冲突失败 |
| `needs_human` | 需人工介入 |
| `blocked` | 上游异常或合并冲突 |
| `skipped` | 人工跳过 |
| `cancelled` | 运行终止时取消 |
| `stale` | 变更影响导致基线过期，待重跑 |

### 3.4 关卡（gate）

```json
{ "id": "<uuid>", "kind": "SPEC基线确认", "status": "pending", "payload": {} }
```

`status`：`pending` / `approved` / `rejected`。

当前会创建的 `kind` 及 `payload` 关键字段：

| `kind` | `payload` 关键字段 | 说明 |
|---|---|---|
| `想法补充` | `missing` (string[]), `card` | 想法信息不足 |
| `初步做法确认` | `card` | 初稿确认 |
| `争议清单查看与裁决` | `issues` (array), `reopen` (bool) | 讨论争议清单 |
| `评审确认` | `pass` (bool), `reviews` (array) | 四角色评审汇总 |
| `SPEC基线确认` | `spec` | 规格冻结前确认 |
| `DESIGN基线确认` | `design`, `reviews` | 设计冻结前确认 |
| `PLAN基线确认` | `plan` | 任务图冻结前确认 |
| `验收确认` | `pass` (bool), `report` | 验收报告确认 |
| `文档检查失败` | `retry` (`proposal`/`spec`/`design`/`plan`), `errors` | 文档校验失败重试 |
| `重排提案` | `task` (code), `kind` | 任务描述问题重排 |
| `变更决定` | `cr` | 变更单裁决 |
| `反馈分流确认` | — | 代码已分支处理，当前不会创建（预留） |

裁决值：

| 场景 | 允许的 `decision` | 备注 |
|---|---|---|
| 普通关卡 | `"approve"` / `"reject"` | 任何非 `"approve"` 值都按驳回处理 |
| `评审确认` | `"approve"` / `"reject"` / `"override"` | `override` 可携带 `payload.pass` 覆盖评审结论；现状关卡 `status` 会记为 `rejected`（§9 A-13） |
| 变更决定 | 用 `POST /crs/{code}/decision` 传 `"批准"` / `"驳回"` | 两种裁决入口并存：`resolve` 用 `approve`/其它（映射为 批准/驳回），独立接口用中文；**语言与关卡裁决不同，勿混用** |

### 3.5 变更单（CR）

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | `CR-1` |
| `description` | string | 变更描述 |
| `impact` | object | `{codes[], downstream[], upstream[]}` 及调用方传入的 flags |
| `level` | enum | `澄清` / `小变更` / `大变更` |
| `kind` | string | 变更类型 |
| `source` | string | 来源 |
| `status` | enum | `analyzed` / `decided` / `rejected` / `applied` / `rewrite_failed` |
| `eval_ok` | bool | 评估是否通过 |
| `eval_flags` | object | `{red_line: bool, blocking: bool}` |
| `scores` | int[] | 三个评估维度分 |
| `decision` | string? | 裁决后出现：`批准` 或 `驳回` |

### 3.6 待办（todo）联合类型

`GET /runs/{id}/todos` 返回异质数组，用字段区分：

| 形态 | 判别 | 示例 |
|---|---|---|
| 待裁决关卡 | 有 `id` + `status` + `kind` | `{"id":"...","kind":"验收确认","status":"pending","payload":{...}}` |
| 待人工任务 | 有 `task` 字段 | `{"kind":"needs_human","task":"T-03"}` |
| 运行级待人工 | 有 `revision` 字段 | `{"kind":"pending_human","revision":12}` |

### 3.7 预算（budget）

`GET /runs/{id}/budget`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | bool | `used < limit` |
| `warn` | bool | `ratio >= warn_ratio`（默认 0.8） |
| `exceeded` | bool | `used >= limit` |
| `ratio` | number | `used / limit`；`limit <= 0` 时为 0 |
| `used` | int | 已用令牌 |
| `limit` | int | 运行上限（默认 20,000,000） |
| `per_point` | int | 每点令牌（默认 1,500,000） |

---

## 4. 接口清单

> 所有路径都省略统一前缀 `/api`。错误码只列“特有错误”，未列出的按 §2.3 通用表处理。

### 4.1 总表

| 方法 | 路径 | 请求 | 成功响应 |
|---|---|---|---|
| GET | `/health` | — | `{"status":"ok"}` |
| POST | `/projects` | `{name, profile?}` | Project |
| GET | `/projects` | — | Project[] |
| POST | `/projects/{project_id}/runs` | `{idea}` | `{run, result}` |
| GET | `/runs` | — | run_view[] |
| GET | `/runs/{run_id}` | — | run_view |
| GET | `/runs/{run_id}/stages` | — | `{current, history}` |
| GET | `/runs/{run_id}/artifacts` | — | artifact map |
| GET | `/runs/{run_id}/discussion` | — | `{questions, merge, utterances, issues}` |
| GET | `/runs/{run_id}/todos` | — | todo[] |
| POST | `/gates/{gate_id}/resolve` | `{decision, payload?, expected_revision?}` | 见 §4.3 |
| GET | `/runs/{run_id}/tasks` | — | task[] |
| GET | `/tasks/{task_id}` | — | task |
| POST | `/tasks/{task_id}/{action}` | `{expected_revision, reason?, payload?}` | task 或执行结果 |
| POST | `/runs/{run_id}/pause` | — | run_view |
| POST | `/runs/{run_id}/resume` | — | run_view |
| POST | `/runs/{run_id}/terminate` | `{confirm:true}` | run_view |
| GET | `/runs/{run_id}/budget` | — | budget |
| PATCH | `/runs/{run_id}/limits` | limits 片段 | 完整 limits |
| GET | `/runs/{run_id}/trace` | — | link[] |
| GET | `/runs/{run_id}/trace/impact` | `?codes=A,B` | `{codes, downstream, upstream}` |
| POST | `/runs/{run_id}/crs` | `{description?, codes?, flags...}` | gate 或 `{queued, queue_size}` |
| GET | `/runs/{run_id}/crs` | — | CR[] |
| POST | `/crs/{code}/decision` | `{decision, reason?}` | CR |
| POST | `/runs/{run_id}/feedback/import` | `{rows:[]}` | raw feedback[] |
| GET | `/runs/{run_id}/feedback` | — | `{raw, items}` |
| GET | `/runs/{run_id}/events/history` | `?after=<int>` | event[] |
| GET | `/runs/{run_id}/events` | 头 `Last-Event-ID` | SSE，见 §6 |
| GET | `/config/models` | — | ModelsFile |
| PUT | `/config/models` | 完整 ModelsFile | `{"ok":true}` |
| POST | `/config/models/test` | — | `{"ok":true,"note":"..."}` |
| POST | `/runs/{run_id}/schedule` | — | `{"started":["T-01"]}` |
| POST | `/runs/{run_id}/accept` | — | gate 或验收结果 |

> `POST /runs/{run_id}/accept` 在 `docs/API.md` 中漏登记，本契约补上（§9 A-5）。

### 4.2 项目与创建运行

**`POST /projects`**

```json
{ "name": "自习室小程序", "profile": "python-pytest" }
```

- `name` 必填，`profile` 可选，默认 `"python-pytest"`。
- 响应 200：`{"id":"<uuid>","name":"...","profile":"python-pytest"}`。
- 缺 `name` → 422。

**`POST /projects/{project_id}/runs`**

```json
{ "idea": "做一个帮同学找自习室空位的小程序" }
```

- `idea` 必填字符串。
- 响应 200：

```json
{
  "run": {
    "id": "<uuid>", "project_id": "<uuid>", "status": "waiting", "stage": "0",
    "revision": 1, "paused": false, "idea": "...", "gates": [{"id":"...","kind":"初步做法确认","status":"pending","payload":{}}],
    "event_count": 2
  },
  "result": {"status": "need_human", "gate": {"id":"<uuid>","kind":"初步做法确认","status":"pending","payload":{"card":{}}}, "stage": "0", "state": "needs_human"}
}
```

- 错误：404 `NOT_FOUND`（项目不存在）；400 `AGENT_OUTPUT_ERROR`（模型输出不合约）；422（缺 `idea`）。
- `result` 是“本次推进结果”，形态见 §4.3 结果表，不要假设固定字段。

### 4.3 关卡裁决

**`POST /gates/{gate_id}/resolve`**

```json
{ "decision": "approve", "payload": {}, "expected_revision": 7 }
```

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `decision` | 是 | — | `approve` / `reject`；`评审确认` 额外支持 `override` |
| `payload` | 否 | `{}` | 关卡相关附加数据：`reason`、`verdicts`、`text`、`pass`、`route` 等 |
| `expected_revision` | 否 | `null` | 传了就比较 **run.revision**；不传跳过检查 |

- 成功 200：结果形态随关卡与决策而变。
- 错误：404 `NOT_FOUND`（关卡不存在）；409 `REVISION_CONFLICT`；400 `VALIDATION_FAILED`（已裁决/重复推进、验收未通过但未写理由）；400 `AGENT_OUTPUT_ERROR`。

结果形态：

| `status` | 出现场景 | 关键字段 |
|---|---|---|
| `need_human` | 需要下一道人工关卡 | `gate`, `stage`, `state:"needs_human"` |
| `executing` | PLAN 批准，进入执行 | `stage:"7"` |
| `done` | 验收批准 | `pass`, `manual`, `reason`, `release`, `tag` |
| `rejected` | 驳回且流程结束（验收/重排/文档检查失败） | `pass` 或 `kind` |
| `stopped` | 退回超限、只有验证类意见等 | `reason` |
| `routed` | 反馈分流确认 | — |
| `replanned` / `replan_failed` | 重排提案 | `tasks` / `errors` |
| CR 对象 | 变更决定 | 见 §3.5 |
| `{status: <gate.status>}` | 兜底 | — |

补充规则：

- `评审确认` 用 `override` 时，`payload.pass` 可覆盖评审结论；现状 gate.status 记 `rejected`（§9 A-13）。
- `验收确认`：`pass=false` 时必须带非空 `reason`，否则 400 且关卡保持 `pending`。
- 成功裁决后 `run.revision` +1；响应里不返回新 revision，需要就再 GET run。

### 4.4 任务控制

**`POST /tasks/{task_id}/{action}`**

```json
{ "expected_revision": 3, "reason": "用户确认跳过", "payload": {} }
```

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `expected_revision` | **是** | — | 比较 **task.revision**；缺失 → 422 |
| `reason` | 否 | `""` | `force-pass`、`skip` 必填；其它动作可空 |
| `payload` | 否 | `{}` | `skip` 可带 `{"downstream":"stop"}`，默认 `"continue"` |

- 响应 200：`pause`/`resume`/`skip`/`takeover`/`force-pass` 返回完整 task；`retry`、`submit-takeover` 返回**执行结果摘要**（至少含 `state`，可能含 `kind`），不是完整 task；需要完整字段请再 `GET /tasks/{id}`。
- 错误：404 `NOT_FOUND`；409 `REVISION_CONFLICT`；400 `ILLEGAL_TRANSITION`（动作在该状态不可用、未知 action）；400 `VALIDATION_FAILED`（缺理由、`patch` 未实现、强制通过时集成回归失败）。
- revision 推进：已实现的动作都会推进 `run.revision`；除 `retry` 外也都会推进 `task.revision`（`retry` 保持 task.revision 不变），详见 §5.2。

动作与使用场景见 §7。

### 4.5 运行控制、预算与限制

**`POST /runs/{run_id}/pause` / `resume`**：无请求体，返回 run_view。重复调用返回 200，但 `run.revision` 每次 +1。

**`POST /runs/{run_id}/terminate`**：

```json
{ "confirm": true }
```

- **无请求体** → 422；有 body 但 `confirm` 不是 `true`（缺省按 `false`）→ 400 `VALIDATION_FAILED`。
- 成功返回 run_view；`status="terminated"`、`paused=true`，未完成任务被取消。
- 这三个运行级控制**没有**乐观锁字段（§9 A-12）。

**`PATCH /runs/{run_id}/limits`**：请求体是 limits 的片段（嵌套深度合并），例如：

```json
{ "orchestrator": { "concurrency": 4 }, "acceptance": { "p1_pass_ratio": 0.95 } }
```

- 响应 200：合并后的完整 limits。
- 错误：404；400 `VALIDATION_FAILED`（未知键、非对象、`limits patch 必须是对象`）。
- 会写事件 `system.limit_changed`，但**不增加** `run.revision`。可覆盖 `config/limits.yaml` 中的硬上限（§9 A-6）。

**`POST /runs/{run_id}/schedule`**：触发一轮调度，返回 `{"started": ["T-01", "T-02"]}`（本次启动的任务 code）；运行暂停时返回 `{"started": []}`。

**`POST /runs/{run_id}/accept`**：生成验收报告并创建 `验收确认` 关卡，返回关卡结果（`need_human` 形态）或验收结果。缺少 SPEC/PLAN 产物时现状会 500（§9 A-8）。

### 4.6 查询类响应形状

| 接口 | 形状 |
|---|---|
| `GET /runs/{id}/stages` | `{"current":"3","history":[{"from":"2","event":"proposal_checked","to":"3"}]}` |
| `GET /runs/{id}/artifacts` | 以产物名为键的字典：`idea_raw`、`idea_card`、`questions`、`merge_rows`、`utterances`、`issues`、`proposal`、`reviews`、`spec`、`design`、`plan`、`baseline_SPEC`、`baseline_DESIGN`、`baseline_PLAN`、`baseline_BUILD`、`acceptance`、`release_dir`、`build_tag`、`cr_queue` 等。缺失键表示尚未生成；客户端必须容忍未知键 |
| `GET /runs/{id}/discussion` | `{"questions":[],"merge":[],"utterances":[],"issues":[]}`（`merge` 对应 `merge_rows`） |
| `GET /runs/{id}/trace` | `[{"from":"S-1","to":"T-01","kind":"spec_item → task","version":"1.0"}]` |
| `GET /runs/{id}/trace/impact?codes=F-1,F-2` | `{"codes":[],"downstream":[],"upstream":[]}`；`codes` 必填，逗号分隔，缺省 422 |
| `GET /runs/{id}/feedback` | `{"raw":[{"id":1,"text":"...","text_masked":"...","author_hash":"...","source":"manual"}],"items":[{"code":"FB-1","category":"缺陷","summary":"...","quotes":[1],"count":1,"basis":"归纳","unique_authors":1,"red_line":false,"known":false,"new_direction":false,"linked_issue":"","distill_errors":[],"route":"..."}]}` |

说明：`discussion` 的四个字段总是存在（可能为空数组）；`artifacts` 是动态字典，不要生成严格 TS 联合类型后假设键固定。

### 4.7 变更单

**`POST /runs/{run_id}/crs`**

```json
{
  "description": "增加课表导入",
  "codes": ["F-3"],
  "kind": "clarify",
  "source": "user",
  "red_line": false,
  "blocking": false
}
```

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `description` | 否 | `""` | 变更描述 |
| `codes` | 否 | `[]` | 受影响编号（功能/模块/任务等），用于计算影响域 |
| `kind` | 否 | `""` | 变更类型，参与分级（`clarify`/`澄清` 等） |
| `source` | 否 | `""` | 来源 |
| 其它 flags | 否 | — | `add_or_remove_feature`、`changes_p0`、`overturns_issue`、`red_line`、`blocking` 等，参与分级/评估 |

- 未达开放上限（默认 3）→ 返回 `变更决定` 关卡（`need_human` 形态）。
- 达到上限 → `{"queued": true, "queue_size": 1}`，不创建关卡。
- 错误：404（run 不存在）；422（body 非对象）。

**`POST /crs/{code}/decision`**

```json
{ "decision": "批准" }
```

- `decision` 使用 `"批准"` / `"驳回"`；其它值按驳回处理。
- 响应 200：更新后的 CR。
- 当前 `reason` 等附加字段不落库，仅随请求传入（如后续需要 `decision_note`，按新增可选字段处理）。
- 错误：400 `VALIDATION_FAILED`（变更单不存在）；注意：**未知 code 现状返回 500**（§9 A-4），修复后应为 404 `NOT_FOUND`。
- 批准会计算影响域、可能把下游任务置为 `stale`/暂停，并写 `baseline.frozen` 等事件。

### 4.8 反馈导入

**`POST /runs/{run_id}/feedback/import`**

```json
{ "rows": [ { "text": "晚上找不到空教室", "author": "u1", "source": "manual" } ] }
```

- `rows` 为对象数组；`text` 会被脱敏（手机号/邮箱/证件/学号/姓名）；`author` 只保留 HMAC-SHA256 哈希（`author_hash`），不存原文。
- 需要后端环境变量 `FEEDBACK_HASH_KEY`，否则 400 `FEEDBACK_HASH_KEY_REQUIRED`。
- 响应 200：本次导入的原始条目数组 `[{id, text, text_masked, author_hash, source}]`；蒸馏/分诊结果写入 `GET /feedback` 的 `items`。

### 4.9 配置（进程内）

**`GET /config/models`** 返回模型配置（`ModelsFile`）：

```json
{
  "provider": "dashscope",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key_env": "DASHSCOPE_API_KEY",
  "limits": {"max_concurrency": 6, "requests_per_minute": 120},
  "slots": {"flagship": {"model": "qwen3-max", "temperature": 0.3, "max_tokens": 8192, "fallback": "qwen-plus", "json_mode": true, "tool_calls": true, "context_window": 32768, "price_per_1k_in": 0, "price_per_1k_out": 0, "extra_body": {}, "dimensions": null}}
}
```

- `api_key_env` 是**环境变量名**，不是密钥；接口不得返回密钥明文。
- `PUT /config/models` 需要**完整** `ModelsFile`（不是 PATCH），成功 `{"ok":true}`；结构不合法 → 422。改动仅存进程内存，不写 `config/models.yaml`，重启失效。
- `POST /config/models/test` 是占位接口，固定返回 `{"ok":true,"note":"use make check-models for live probe"}`，不做真实探测。

### 4.10 缺失资源与错误文案

404 的 `detail` 当前为下列固定英文（仅用于排查，不得编码依赖）：

| 场景 | `detail` |
|---|---|
| 项目 | `project not found` |
| 运行 | `run not found` |
| 关卡 | `gate not found` |
| 任务 | `task not found` |

---

## 5. 乐观锁（`expected_revision`）

### 5.1 版本语义

| 版本字段 | 归属 | 何时 +1 |
|---|---|---|
| `run.revision` | 运行 | 关卡裁决、任务控制、运行控制、变更应用等流程推进 |
| `task.revision` | 任务 | 任务状态变化、任务控制 |

两者独立：任务控制比较的是 **task.revision**，不是 run.revision；关卡裁决比较 **run.revision**。

### 5.2 接口对照

| 接口 | 版本字段 | 必填 | 比较对象 | 冲突响应 | 成功后 |
|---|---|---|---|---|---|
| `POST /gates/{gate_id}/resolve` | `expected_revision` | 否 | `run.revision` | 409 | `run.revision` +1 |
| `POST /tasks/{task_id}/{action}` | `expected_revision` | **是**（缺失 422） | `task.revision` | 409 | `task.revision` +1、`run.revision` +1（`retry` 例外：task.revision 不变，见下） |
| `POST /runs/{id}/pause` | 无 | — | — | — | `run.revision` +1 |
| `POST /runs/{id}/resume` | 无 | — | — | — | `run.revision` +1 |
| `POST /runs/{id}/terminate` | 无 | — | — | — | `run.revision` +1 |
| `PATCH /runs/{id}/limits` | 无 | — | — | — | 不变 |

任务动作的 revision 细节（现状）：

| 动作 | `task.revision` | `run.revision` | 备注 |
|---|---|---|---|
| `pause` / `resume` | +1 | +1 | 只改 `paused` 标记，`state` 不变 |
| `takeover` | +1 | +1 | 只写 `locked_by` / `takeover_workspace` |
| `skip` / `force-pass` | +1 | +1 | 状态机迁移 |
| `submit-takeover` | +1 | +1 | 先加版本，再走评审合并 |
| `retry` | **不变** | +1 | 随后同步执行任务；任务执行分支不再显式加 task.revision |
| `patch` | — | — | 直接 400，不会产生版本变化 |

> `takeover` 只改标记位却仍 +1，是为了让“接管中”的并发控制也走 409 保护；客户端拿到 409 属正常。

### 5.3 冲突处理约定

1. 收到 409 后**不要原样重试**；先 `GET` 最新 `run.revision` / `task.revision`，并把最新状态展示给用户。
2. 用户确认后，用新 revision 重试一次；仍 409 则停止并提示“状态已被其他操作修改”。
3. 409 响应体不包含当前 revision（现状），客户端必须重新拉取（§9 A-1 修复后可考虑附加 `current_revision`，属于新增字段，向后兼容）。

---

## 6. 实时推送（SSE）

### 6.1 连接

```
GET /api/runs/{run_id}/events
Accept: text/event-stream
Last-Event-ID: 42        # 可选；通常由浏览器 EventSource 在重连时自动携带
```

- 成功：`200`，`Content-Type: text/event-stream`（UTF-8）。
- 运行不存在：在建立流之前返回 404 `NOT_FOUND`。
- 无鉴权、无 cookie 要求；经 Vite 代理时同源。
- 浏览器 `EventSource` **不允许自定义请求头**，所以首次连接无法手动指定游标；需要指定起点时先调 `GET /events/history?after=`，再用 `EventSource` 接续。

### 6.2 帧格式

事件帧（每条事件一帧，字段顺序固定为 `id` → `event` → `data`）：

```
id: 42
event: message
data: {"seq":42,"kind":"task.state_changed","subject":"T-01","payload":{"code":"T-01","from":"ready","to":"running","event":"scheduled","reason":""},"actor":"system"}

```

心跳帧（无 `id`、无 `event`，**不推进游标**）：

```
: ping

```

- 心跳每 15 秒一次，即使没有事件也会发送。
- 没有 `retry:` 字段，重连间隔由浏览器默认策略决定。
- 没有“结束帧”：运行 `done`/`terminated` 后连接不会自动关闭，客户端应结合 `GET /runs/{id}` 的 `status` 主动关闭。
- `data` 是单行 JSON（`ensure_ascii=False`），客户端按 JSON 解析，不要按分隔符切分。

### 6.3 事件对象

| 字段 | 类型 | 必有 | 说明 |
|---|---|---|---|
| `seq` | int | 是 | 该 run 内严格递增的事件序号，见 §6.4 |
| `kind` | string | 是 | 事件类型，见 §6.7 |
| `subject` | string | 是（可为 `""`） | 主体：任务 code / gate id / 阶段号 / 模型槽位 / 发言序号 |
| `payload` | object | 是（可为 `{}`） | 事件负载，按 `kind` 定义 |
| `actor` | string | 是 | `system` / `owner`（服务端写入） |

**注意**：

- 推送数据中**没有** `run_id` 和 `ts`。`run_id` 由 URL 确定；`schemas/common.py` 里的 `Event` 模型包含这两个字段，但当前事件端点不使用它（§9 A-9 建议补 `ts`，属新增字段）。
- 事件对象就是 `data` 的全部内容，不要再包一层 `{event: ...}`。

### 6.4 `seq` 语义

- 每个 run 独立计数，正常从 `1` 开始，单调递增。
- **不保证连续**：异常恢复可能写入 `seq=0` 的 `runtime.recovery_failed` 记录，导致后续出现空号；客户端不得假设 `seq` 连续。
- `seq=0` 是保留值：只用于恢复失败标记，`after=0` 时不会被回放，客户端应忽略。
- `run_view.event_count` 是数组长度，不是最大 `seq`，**不能**作为游标。
- `seq == 本地游标`：视为重连回放的重复，直接忽略。
- 若收到 `seq` **明显小于**本地游标（例如进程重启后从 1 重新计数），视为序号回退：清空本地事件并按 `after=0` 全量重载。
- 同一条事件可能因重连回放重叠而重复到达：按 `seq` 去重即可。

### 6.5 `Last-Event-ID` 与重放

服务端对每个连接执行：

1. 读取请求头 `Last-Event-ID`，转成整数，缺省或空串视为 `0`。
2. 按 `run.events` 顺序回放所有 `seq > after` 的事件，逐帧发送。
3. 进入循环：再扫一遍新事件 → 发 `: ping` → 睡 15 秒。

由此得到：

| 行为 | 现状 |
|---|---|
| 回放起点 | 严格大于 `Last-Event-ID`（不含等于） |
| 回放数据源 | 进程内 `run.events`（启动时从 `events.jsonl` 恢复），**不是**持久化 `EventBus` 订阅 |
| 新事件延迟 | 最坏约 15 秒（循环每轮睡 15 秒）；不是实时推送（§9 A-2） |
| 无效 `Last-Event-ID`（非整数） | 现状 500；契约目标：按 `0` 处理（§9 A-3） |
| 断线重连 | 浏览器自动带最后收到的 `id`；服务端据此续传 |
| 历史补偿 | `GET /runs/{id}/events/history?after=<cursor>`，返回 `seq > after` 的数组 |

运维注意：部署在反向代理后时，需关闭响应缓冲并放宽读超时（心跳间隔 15s 是下限），否则会表现为“连接建立但收不到事件”。

### 6.6 客户端接入算法（参考）

```ts
let cursor = 0;

async function resync() {
  const missed = await api.events(runId, cursor); // 返回 seq > cursor
  render(missed);
  cursor = missed.at(-1)?.seq ?? cursor;
}

// 1) 首次全量
await resync();

// 2) 接续 SSE（onmessage 内的异步要串行化，避免并发补拉）
const es = new EventSource(`/api/runs/${runId}/events`);
es.onmessage = async (msg) => {
  const ev = JSON.parse(msg.data);
  if (ev.seq <= cursor) return;                    // 重放重叠 / 回退：忽略
  if (ev.seq > cursor + 1) {
    await resync();                                // 疑似缺号：先补拉
    if (ev.seq <= cursor) return;                  // 已被补拉覆盖
  }
  renderOne(ev);
  cursor = ev.seq;
};
```

> 说明：`seq > cursor + 1` 只是“疑似缺号”的启发式；由于 §6.4 允许空号，生产实现应把它当作提示，并在补拉失败时仍允许直接接收更大的 `seq`。

### 6.7 事件目录

| `kind` | `subject` | `payload` 关键字段 | 触发时机 |
|---|---|---|---|
| `stage.started` | 阶段号（`"0"`） | `idea` | 创建运行 |
| `stage.changed` | 新阶段号 | `event` | 阶段推进；当前仅 `7→8`（`tasks_complete`）会发（§9 A-10） |
| `task.state_changed` | 任务 code | 至少含 `code`, `to`, `event`；多数含 `from`, `reason`，并可能带 `kind`/预算等附加字段 | 任务状态机每次迁移 |
| `task.spawned` | 新任务 code | `kind`（冲突解决）, `of`, `write_set` | 合并冲突派生任务 |
| `task.write_denied` | 任务 code | `path` 或 `paths` | 越界写入被沙箱拒绝 |
| `gate.created` | gate id | `kind` | 新关卡 |
| `gate.resolved` | gate id | `decision` + 裁决 payload 展开 | 关卡裁决 |
| `discussion.message` | 发言序号 | `role`, `rule` | 每轮讨论发言 |
| `discussion.status_overridden` | `""` | `items` | 讨论规则覆盖状态 |
| `review.overridden` | `""` | `reason` | 人工覆盖评审结论 |
| `baseline.frozen` | `SPEC`/`DESIGN`/`PLAN`/`BUILD` | `version`，变更触发时含 `cr` | 基线冻结 |
| `budget.warn` | `""` | `ok`, `warn`, `exceeded`, `ratio` | 首次达到预警线 |
| `budget.exceeded` | `""` 或任务 code | `ok`, `warn`, `exceeded`, `ratio`；任务级可能只有 `used` | 超预算 |
| `system.limit_changed` | `""` | `before`, `after`（完整 limits） | `PATCH /limits` |
| `llm.fallback` | 模型槽位 | 网关事件（至少含 `kind`、`slot`、`fallback`） | 模型降级/重试 |
| `orchestrator.illegal_transition` | 任务 code | `from`, `event`, `reason` | 非法迁移被拒 |
| `control.pause` / `control.resume` / `control.retry` / `control.skip` / `control.takeover` / `control.submit-takeover` / `control.force-pass` | 任务 code；运行级为 `""` | 任务级：`from`, `to`, `reason`, `rev`；运行级：`status`, `paused` | 控制动作成功（`control.patch` 当前不会产生，因 patch 直接 400） |
| `runtime.recovery_failed` | run id | `reason` | 恢复失败；`seq=0`，不推送 |

客户端处理原则：

- 未知 `kind`：记录并忽略，不得抛错中断流。
- `payload` 只保证是对象，不要对未知附加字段做严格校验。
- 事件是“状态变化的通知”，不是唯一事实源；刷新页面后应以 REST 查询结果为准。

---

## 7. 控制动作可用矩阵

### 7.1 动作 × 任务状态

| 动作 | 允许的 `state` | 额外约束 |
|---|---|---|
| `pause` | `pending`、`ready`、`running`、`verifying`、`failed`、`needs_human`、`blocked` | 无 |
| `resume` | 同上 | 无 |
| `retry` | `needs_human`、`failed` | 同步触发任务执行 |
| `skip` | `pending`、`ready`、`running`、`verifying`、`failed`、`needs_human`、`blocked` | **必须** `reason`；`payload.downstream` 默认 `"continue"` |
| `takeover` | `pending`、`ready`、`running`、`verifying`、`failed`、`needs_human`、`blocked` | 创建/复用工作树，返回 `takeover_workspace` |
| `submit-takeover` | 非终态（非 `done`/`skipped`/`cancelled`） | 提交后走评审合并 |
| `force-pass` | `needs_human`、`failed` | **必须** `reason`；有 repo 时先跑集成回归，失败则 400 |
| `patch` | `pending`、`ready`、`needs_human` | 状态允许时直接 400 `VALIDATION_FAILED`（未实现）；状态不允许则 400 `ILLEGAL_TRANSITION` |

- 不在表中的 `action` 一律 400 `ILLEGAL_TRANSITION`（不是 404）。
- `done`/`skipped`/`cancelled` 为终态，除 `submit-takeover` 的“非终态”判断外均不可控制。
- 后端 `CONTROL_TABLE` 与前端 `CONTROL_ENABLED` 必须保持同源，前端按钮置灰只做体验，**最终以服务端校验为准**。

### 7.2 关卡裁决的附带行为

| `gate.kind` | `approve` | `reject` |
|---|---|---|
| `想法补充` | 把 `payload.text` 追加到 idea，重新走想法检查与初稿 | 同 approve（都会重新推进） |
| `初步做法确认` | 进入讨论 | 重新走想法检查/初稿 |
| `争议清单查看与裁决` | 应用 `payload.verdicts`，进入方案 | 重新开争议清单（带 `reason`） |
| `评审确认` | 通过则生成 SPEC；否则按 `payload.route` 退回讨论/方案 | 同左（按 route 或评审意见决定） |
| `SPEC` / `DESIGN` / `PLAN` 基线确认 | 冻结基线并推进 | 带 `reason` 重写该文档 |
| `验收确认` | `payload.pass` 为真则 `done` 并导出交付；为假时必须带 `reason` 才可人工放行 | 驳回 |
| `文档检查失败` | 按 `payload.retry` 重跑对应文档 | 结束（`rejected`） |
| `重排提案` | 应用重排 | 结束（`rejected`） |
| `变更决定` | 交由 `decide_cr` 处理（`payload.decision` 可覆盖） | 驳回该 CR |

---

## 8. 兼容性与版本策略

1. 当前只有 `/api` 一个版本段；**新增字段、新增枚举值、新增事件 `kind` 视为兼容变更**，客户端必须容错。
2. **删除/改名字段、改变类型、改变语义、改变状态码**视为破坏性变更，需要 `/api/v2` 或前后端同批发布。
3. 客户端对 `state`、`gate.kind`、`event.kind`、`status` 的 switch 必须有 default 分支。
4. 服务端新增必填请求字段属于破坏性变更；只允许新增可选字段。
5. 契约变更需更新本文与 `docs/API.md`，并在 PR 描述中标注“契约变更”。

---

## 9. 现状差异与落地任务

> A 项是“契约目标与当前代码的差距”。A 项完成前，前后端按现状联调，但**不要把现状写死进类型或测试**。

| ID | 差距 | 影响 | 责任方 | 验收标准 |
|---|---|---|---|---|
| A-1 | 错误响应没有 `code` 字段，只有 `detail` | 前端无法稳定分支；只能靠状态码 | 后端 | 400/404/409/422/500 均返回 `{detail, code}`；新增契约测试 |
| A-2 | SSE 每 15 秒轮询内存数组，事件延迟最坏约 15s | “实时”体验不达标 | 后端 | 接入 `EventBus` 订阅或缩短轮询；P95 延迟有明确指标 |
| A-3 | 非法 `Last-Event-ID`（非数字）导致 500 | 代理/手工调用可能打断连接 | 后端 | 解析失败按 `0` 处理，返回 200 流 |
| A-4 | `POST /crs/{code}/decision` 未知 code 触发 `StopIteration` → 500 | 错误地表现为服务故障 | 后端 | 返回 404 `NOT_FOUND` |
| A-5 | `docs/API.md` 漏登记 `POST /runs/{id}/accept` | 文档与实现不一致 | 文档 | 本文评审后同步更新 API.md |
| A-6 | `PATCH /limits` 可覆盖 `concurrency` 等硬上限 | 可能绕过 Design 的硬约束 | 双方确认 | 明确“可覆盖/不可覆盖”清单并加校验 |
| A-7 | `/tasks/{id}` 按 code 跨 run 查找；`/crs/{code}` 跨 run 查找 | 多 run 时可能命中错误资源 | 后端 | 优先完整 id；CR code 全局唯一或路径带 run_id |
| A-8 | `POST /runs/{id}/accept` 缺 SPEC/PLAN 时 KeyError → 500 | 前端调用顺序错误时像服务故障 | 后端 | 返回 400 `VALIDATION_FAILED` 并说明前置条件 |
| A-9 | 事件无 `ts`、无 `run_id` | 跨 run 归档/排序困难 | 后端 | 事件新增 `ts`（ISO-8601 UTC，可选兼容）；`run_id` 仍由 URL 确定 |
| A-10 | 仅 `7→8` 发 `stage.changed`，其它阶段迁移无事件 | 前端阶段条只能轮询 | 后端 | 所有 `engine.apply` 发 `stage.changed`，或明文约定只轮询 |
| A-11 | `PATCH /limits` 不增加 `run.revision` | 并发修改限制无冲突检测 | 双方确认 | 要么纳入乐观锁，要么文档明确“最后写入胜出” |
| A-12 | run 级 pause/resume/terminate 无 `expected_revision` | 并发控制可能覆盖 | 双方确认 | 增加可选 `expected_revision`（兼容）或明确接受覆盖 |
| A-13 | `评审确认` 用 `override` 时 gate.status 记为 `rejected` | 前端展示“已驳回”但流程继续 | 后端 | 新增 `overridden` 状态或文档说明 |
| A-14 | `config/models` 校验失败返回 422 而非 400 | 错误码分类不一致 | 后端 | 统一为 400 `VALIDATION_FAILED` 或文档固定 422 |
| A-15 | 无契约测试覆盖 SSE 帧与错误码 | 回归无保护 | 后端+测试 | 新增 `tests/integration/test_api_contract.py`：状态码、`code`、`id:` 帧、`Last-Event-ID` 回放 |

---

## 10. 待确认问题（评审时逐条拍板）

| 编号 | 问题 | 建议默认 |
|---|---|---|
| Q1 | 错误 `code` 的落地时间与兼容期？ | 先加 `code`，前端两个版本内兼容 `detail` |
| Q2 | SSE 延迟目标？ | 交互可感知 ≤ 1s；15s 仅作兜底 |
| Q3 | `task.code` 是否允许作为 `/tasks/{id}` 的入口？ | 允许但文档标注“仅单 run 场景”，长期只认完整 id |
| Q4 | run 级控制是否引入 `expected_revision`？ | 引入可选字段，缺失时保持旧行为 |
| Q5 | `PATCH /limits` 是否允许改硬上限？ | 不允许改 `concurrency`/`max_repair_rounds`/`tokens_per_point` 等硬约束 |
| Q6 | 运行 `done`/`terminated` 后 SSE 是否主动关闭？ | 关闭并发送一条最终事件（新增，兼容） |
| Q7 | 关卡裁决与 CR 裁决的决策词是否统一？ | 保持现状：关卡 `approve/reject`，CR `批准/驳回`，文档写清 |
| Q8 | 事件是否补 `ts`？ | 补，ISO-8601 UTC，新增字段 |

---

## 11. 附录

### 11.1 curl 快速验证

```bash
# 健康检查
curl -s http://127.0.0.1:8765/api/health

# 建项目
PROJECT=$(curl -s -X POST http://127.0.0.1:8765/api/projects \
  -H 'Content-Type: application/json' -d '{"name":"demo"}')
echo "$PROJECT"

# 建运行（需要项目 id）
curl -s -X POST http://127.0.0.1:8765/api/projects/<project_id>/runs \
  -H 'Content-Type: application/json' \
  -d '{"idea":"做一个帮同学找自习室空位的小程序"}'

# 历史事件
curl -s "http://127.0.0.1:8765/api/runs/<run_id>/events/history?after=0"

# SSE：从头收 3 条事件后断开
curl -N --max-time 5 "http://127.0.0.1:8765/api/runs/<run_id>/events"

# SSE：从 seq=5 之后续传
curl -N --max-time 5 -H 'Last-Event-ID: 5' \
  "http://127.0.0.1:8765/api/runs/<run_id>/events"
```

### 11.2 前端接入 checklist

- [ ] 只依赖 HTTP 状态码 + `code`，不匹配中文/英文 `detail` 文案。
- [ ] 任务控制始终传完整 `task.id` 与最新 `task.revision`。
- [ ] 409 后先刷新再让用户确认，不盲重试。
- [ ] SSE 按 `seq` 去重；维护 per-run 游标；检测 `seq` 回退触发全量重载。
- [ ] 未知 `kind`/`state`/`gate.kind` 有 default 分支。
- [ ] `run_view.event_count` 不当作游标。
- [ ] 运行进入 `done`/`terminated` 后主动关闭 `EventSource`。
- [ ] 页面刷新后以 REST 查询为准，SSE 只做增量。

### 11.3 后端错误码补丁草图（供 Owner 参考）

目标是把响应体统一成顶层 `{detail, code}`，且不改变现有异常类：

```python
# app/api/errors.py（示意）
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        self.status, self.code, self.detail = status, code, detail

def register(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "code": exc.code})
```

注意：不能简单写 `HTTPException(status_code=..., detail={"detail": ..., "code": ...})`，FastAPI 会把整个 dict 嵌到 `detail` 下，得到 `{"detail":{"detail":...,"code":...}}`。另外需要给 `RequestValidationError` 注册处理器，把 422 统一成 `{"detail": <原数组>, "code": "REQUEST_INVALID"}`；`Test3Error` 建议用一个处理器按 `exc.code` 映射状态码（`RevisionConflict→409`，其余→400）。落地时覆盖 `routes.py` 中所有手工 `HTTPException(...)` 调用，并补 §9 A-1 的契约测试。

### 11.4 并行开发切分建议

| 工作流 | 内容 | 依赖 |
|---|---|---|
| 后端契约层 | A-1 error `code`、A-3 Last-Event-ID 容错、A-4/A-8 缺失资源返回 404/400 | 本文 §2.3、§6 |
| 后端实时层 | A-2 SSE 延迟、A-9 `ts`、A-10 阶段事件、A-15 契约测试 | 本文 §6、§9 |
| 前端接入层 | 错误码分支、任务 id/revision、SSE 游标与去重、未知枚举容错 | 本文 §2、§5、§6.6 |
| 文档/测试 | 更新 `docs/API.md`、补契约测试用例 | 本文评审定稿后 |

---

## 12. 变更记录

| 版本 | 日期 | 作者 | 说明 |
|---|---|---|---|
| v0.1 | 2026-11-12 | 郭婷婷 | 首版草稿：路径/参数/错误码/SSE 与 seq、Last-Event-ID 约定 |

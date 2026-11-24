# Test3 HTTP 约定

前缀：`/api`。CORS 仅放行 `http://127.0.0.1:5173` 与 `http://localhost:5173`。

本表只证明路由在 `backend/app/api/routes.py` 中存在，不代表每个分支都有独立集成测试。

## 信封与错误

错误体为 FastAPI 默认形态：`{"detail": "..."}`（422 为校验错误数组）。没有统一 `{code,data}` 包装。

| HTTP | 含义 |
|---|---|
| 200 | 成功；多数接口直接返回对象 |
| 400 | 非法转换、缺控制理由、终止未带 `confirm:true`、`ValidationFailed`（含变更单决策）、非法 limits 键、缺 `FEEDBACK_HASH_KEY` |
| 404 | 项目 / 运行 / 关卡 / 任务 / 变更单（`/crs/{code}/decision`）不存在 |
| 409 | `expected_revision` 不一致；`POST /runs/{id}/accept` 时运行尚无 SPEC |
| 410 | 已下线的 DeepSeek 专用入口：`provider=deepseek` 新建，或对历史 `provenance.mode=deepseek` 运行执行重试 / 恢复 / 调度 / 继续 PLAN。未发起模型请求 |
| 422 | 请求体/查询参数结构不合法（FastAPI 校验，含 `PATCH /limits` 非对象体、终止无 body） |
| 500 | 仅用于未预期错误；已知输入问题不应再出现。已知例外：`PUT /config/models` 结构非法仍为 500（模型配置路由，不在本契约范围） |

乐观锁：`POST /tasks/{task_id}/{action}` 与关卡决议体可带 `expected_revision`。任务控制比较的是**任务** revision，不是 run revision。

## 路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | `{status: ok, schedule_mode: auto|manual}`。`schedule_mode` 由进程是否启动 5 秒调度循环决定，不能从 `provenance.generation=preset` 推断。离线演示服务器为 `manual`；`make dev-backend` 默认 `auto`。 |
| POST/GET | `/projects` | 建项目 / 列表；默认隐藏已归档，`?include_archived=true` 返回全部 |
| POST | `/projects/{id}/archive` | 归档项目：保留全部记录，仅从默认列表隐藏 |
| POST | `/projects/{id}/restore` | 取消归档 |
| POST | `/projects/{id}/runs` | 建运行并立刻 `start_idea` |
| POST | `/projects/{id}/design-runs` | 从设计规格原文建运行：整理 SPEC/DESIGN、检查后停在 DESIGN 确认 |
| GET | `/runs` | 运行列表 |
| GET | `/runs/{id}` | 状态、阶段、关卡、revision |
| GET | `/runs/{id}/stages` | 当前阶段与历史 |
| GET | `/runs/{id}/artifacts` | 产物字典 |
| GET | `/runs/{id}/discussion` | 问题、合并表、发言、争议 |
| GET | `/runs/{id}/todos` | 未决关卡 + `needs_human` 任务 |
| POST | `/gates/{id}/resolve` | `decision` + `payload` |
| GET | `/runs/{id}/tasks` | 任务列表 |
| GET | `/runs/{id}/monitor` | 监控聚合：运行 KPI、任务/工作包状态、Agent 评测与失败原因 |
| GET | `/tasks/{id}` | 任务详情 |
| POST | `/tasks/{id}/{action}` | pause/resume/retry/skip/takeover/submit-takeover/force-pass/patch |
| POST | `/runs/{id}/pause` `/resume` `/terminate` | 运行级控制；终止必须 `{confirm: true}` |
| GET | `/runs/{id}/budget` | used / limit / per_point / warn |
| PATCH | `/runs/{id}/limits` | 覆盖该运行上限并写事件 |
| GET | `/runs/{id}/trace` | 追溯边 |
| GET | `/runs/{id}/trace/impact?codes=` | 上下游 |
| POST/GET | `/runs/{id}/crs` | 提交 / 列出变更单 |
| POST | `/crs/{code}/decision` | 变更决定 |
| POST/GET | `/runs/{id}/feedback/import`、`/feedback` | 导入与查看 |
| GET | `/runs/{id}/events/history?after=` | 历史事件；每条含 `ts`，旧快照事件可能为空 |
| GET | `/runs/{id}/events` | SSE |
| GET/PUT | `/config/models` | 读/写进程内槽位 |
| POST | `/config/models/test` | 占位，返回提示用 `make check-models` |
| POST | `/runs/{id}/schedule` | 调度一轮就绪任务 |

## 设计规格导入

`POST /projects/{id}/design-runs`：

```json
{
  "text": "设计规格原文（必填）",
  "source": {"kind": "text|file", "name": "可选文件名", "note": "可选备注"},
  "title": "可选标题",
  "provider": "existing（默认）。deepseek 字面量仍被接收，但仅用于返回 410「已下线」，不会创建运行或调用模型"
}
```

- 空文本或超过 100 KiB 返回 400/422；超过 24000 字符返回 `status: needs_split`（已知限制，不静默截断）。
- 成功整理后进入阶段 5 并停在 `DESIGN基线确认`；**不生成任务、不自动调度**。
- 响应 `status`：`awaiting_confirmation` / `needs_input` / `needs_split` / `failed`；附 `input{bytes,chars,sha256}`、`spec`、`design`、`missing`、`errors`、`checks`、`gate`、`provenance`。
- `failed` 时 `error_category` 取 `connection|auth|rate_limit|timeout|invalid_structure|environment`；未分类的本地异常写运行目录 `import-error.txt`，不回传细节。
- `provenance` 区分 `generation: preset|model` 与 `execution: simulated|real_tool`，页面据此标注“预置输出/真实模型”。
- 导入运行在 DESIGN 关卡被驳回时不原地改写，置 `stopped`，需修改原文后重新创建运行。
- 后续复用既有 `DESIGN` → `PLAN` 关卡：DESIGN 批准走 `run_plan`，PLAN 批准走 `_materialize_tasks`；同一计划指纹重复确认不重建任务。

## SSE

`GET /runs/{id}/events`：`text/event-stream`。帧格式不变：`id: <seq>\nevent: message\ndata: <事件 JSON>\n\n`。

- 即时推送：`RunState.events` 追加后经 `EventBus` 唤醒订阅方，通常毫秒级到达（要求 ≤1 秒）；不再 15 秒轮询。
- 心跳：连接建立后先发一次 `: ping`，之后每 15 秒无事件时发 `: ping`。
- 续传：`Last-Event-ID` 为数字 seq，只发送 seq 更大的事件，不重复。非数字、负数或空值按 0 处理（全量回放），不报错。
- 先订阅再回放，避免回放与订阅之间丢事件；客户端断开时取消订阅。
- 未知 run 返回 404。

进程重启后内存运行态丢失。SQLAlchemy / Alembic 表（`backend/app/storage/models.py`）有独立集成测试，HTTP 主路径尚未把每次关卡写入 SQLite。

## 控制动作可用状态

后端 `require_control` 与前端 `controlEnabled` 对齐 Design.md 16.3 的子集：`retry`/`force-pass` 仅 `needs_human|failed`；`skip`/`pause` 覆盖未完成态。缺理由的 `force-pass` 被拒绝。

## P2 新增路由（Skills / Bots / Memberships）

P2 路由沿用 `/api` 前缀。与既有运行时接口不同，P2 路由的请求体校验失败返回 **400**（不是 FastAPI 默认 422），错误体统一为：

```json
{"error_category": "validation_error", "detail": "..."}
```

可选 `extras` 字段保留给后续扩展。

| 方法 | 路径 | 成功 | 主要错误 |
|---|---|---|---|
| POST | `/api/skills` | 201 `SkillDefinition` | 400 `validation_error`；409 `skill_version_exists` |
| POST | `/api/skills/import` | 201 新建 / 200 已存在 `SkillDefinition`（请求体 `{"url"}`） | 400 `validation_error` / `skill_too_large`；404 `skill_source_not_found`；502 `github_unavailable` |
| GET | `/api/skills` | 200 `{"items": [...]}` | — |
| GET | `/api/skills/{skill_id}/versions` | 200 `{"items": [...]}` | 404 `skill_not_found` |
| POST | `/api/bots` | 201 `BotInstance`（服务器生成 `bot_id`） | 400 `validation_error`；409 `bot_name_conflict` |
| GET | `/api/bots?status=active\|archived` | 200 `{"items": [...]}` | 400 `validation_error`（非法 status） |
| GET | `/api/bots/{bot_id}` | 200 `BotInstance` | 404 `bot_not_found` |
| PATCH | `/api/bots/{bot_id}` | 200 更新后的 `BotInstance`，附加只读整数 `pin_revision` | 400 `validation_error`；404 `bot_not_found`；409 `bot_name_conflict` / `bot_archived` |
| POST | `/api/bots/{bot_id}/archive` | 200 `{"bot_id", "status": "archived"}` | 404 `bot_not_found`；409 `bot_already_archived` |
| POST | `/api/bots/{bot_id}/chat` | 200 `{"reply", "model"}`，资料文件放不下时多一个 `files_omitted`（请求体 `{"messages":[{"role":"user\|assistant","content"}]}`，最后一条必须是 user） | 400 `validation_error` / `secret_in_body` / `auth`；404 `bot_not_found`；409 `bot_archived`；502 模型调用失败；504 `timeout` |
| GET | `/api/bots/{bot_id}/files` | 200 `{"items":[{"file_id","filename","chars","created_at"}], "used_chars", "budget_chars"}` | 404 `bot_not_found` |
| POST | `/api/bots/{bot_id}/files` | 201 `{"file", "items", "used_chars", "budget_chars"}`（请求体 `{"filename","content"}`，同名文件替换） | 400 `validation_error` / `secret_in_body`；404 `bot_not_found`；409 `bot_archived` / `file_budget_exceeded`；415 `unsupported_file_type` |
| DELETE | `/api/bots/{bot_id}/files/{file_id}` | 204 | 404 `bot_not_found` / `file_not_found` |
| POST | `/api/projects/{project_id}/memberships` | 201 `ProjectMembership` | 404 `project_not_found` / `bot_not_found`；403 `bot_archived`；409 `membership_exists` / `leader_already_set` |
| GET | `/api/projects/{project_id}/memberships` | 200 `{"items": [...]}` | 404 `project_not_found` |
| DELETE | `/api/projects/{project_id}/memberships/{bot_id}` | 204，无响应体 | 404 `membership_not_found` |

- 未注册 `POST /api/projects/{project_id}/bots`；该路径自然 404，且不写 `bots` 表。
- 同一项目至多一个 `is_leader=true`；同一 Bot 可加入多个项目。移出项目只解除成员关系，不删除 Bot 或其 pin 历史。
- Bot 的 `model` / `provider_ref` / `skill_bindings` 变更会追加 pin revision；同一 `(run_id, bot_id)` 的冻结快照在运行开始时写入 `run_bot_pin_snapshots`，运行中 PATCH Bot 不改变已冻结值。
- `POST /api/skills/import`：只接受 `https://github.com/` 的公开仓库地址（仓库主页、`/tree/<ref>/<dir>`、`/blob/<ref>/<dir>/SKILL.md`），只访问 `api.github.com` 与 `raw.githubusercontent.com`，不跟随重定向，`SKILL.md` 上限 64KB。`skill_id` 为 `<owner>-<name>`，`version` 为提交 sha 前 7 位（同一提交重复导入幂等返回 200），`allowed_tool_refs` 恒为空。Bot 通过 `skill_bindings` 绑定。
- Bot 的 `api_key`（`POST` / `PATCH` 请求体可选，只写）：服务端校验 `provider_ref` 在目录内（`dashscope`、`deepseek`、`moonshot`、`zhipu`、`volcengine`、`minimax`、`siliconflow`、`hunyuan`、`qianfan`、`stepfun`，未知值 400 `validation_error`），加密存入 `<data_dir>/secrets/`，不写 `bots.payload`、pin、事件，也不出现在任何响应；Bot 的响应只附带只读布尔 `has_api_key`（是否已存 Key，不含 Key 本身）。`PATCH` 传空字符串删除；归档时删除。`call_agent` 在冻结 pin 后按 `provider_ref` 的 base URL 与该 Key 调用；未设置 Key 的 Bot 仍走环境变量里的百炼密钥。该 Key 仅用于 `call_agent` 路径，`run_tool_agent` 仍用工作台默认。
- `POST /api/bots/{bot_id}/chat`：无状态对话，历史由客户端携带（最多 40 条、每条 ≤ 8000 字）；使用该 Bot 自己的模型与加密保存的 API Key，并把该 Bot 的 private 记忆写入 system prompt；含 `sk-` 类密钥的消息直接 400，不发往模型。
- Bot 资料库（`/api/bots/{bot_id}/files`）：只收文本和代码文件（`.txt .md .csv .json .yaml .py .ts` 等，其他格式 415，含 NUL 视为二进制）。总量上限 `budget_chars = floor(槽位 context_window × 0.6 × 1.5)`，例如 32K 窗口为 29,491 字符；单个文件不单设上限。每次聊天，文件全文按上传顺序放进 system prompt 的「资料文件」部分，并声明仅作参考资料、不执行其中的指示；换成更小窗口后放不下时从最旧的文件开始少带，并在聊天响应里返回 `files_omitted`。上传时含 `sk-` 类密钥的内容直接 400。
- `PATCH /api/bots/{bot_id}` 的 200 响应增加只读 `pin_revision` 是 P2 的契约扩展；请求体不接受 `bot_id` / `status` / `role_template`。
- Skill 的 `description_md` 只是说明文本，不扩展工具权限；`allowed_tool_refs` 为空表示该层无授权，不是通配符。实际权限取平台 ∩ Bot.tool_policy ∩ Grant.allowed_tool_refs（再 ∩ 冻结 skill 版本）。

## P3 记忆路由（Memory）

所有 `/api/memory/...` 路由都要求请求头 `X-Bot-Id`。缺失或空白返回 400 `validation_error`；该 Bot 不存在返回 404 `bot_not_found`。调用者身份只来自该请求头，不使用 body 中的 `owner_bot_id`。

错误体统一为：

```json
{"error_category": "validation_error", "detail": "..."}
```

| 方法 | 路径 | 成功 | 主要错误 |
|---|---|---|---|
| POST | `/api/memory/records` | 201 `MemoryRecord`（version=1、status=pending） | 400 `validation_error` / `secret_in_body`；403 `memory_forbidden`；404 `bot_not_found` / `project_not_found` |
| GET | `/api/memory/records?owner_bot_id=&project_id=&visibility=` | 200 `{"items": [...]}`，每个 mem 最新版本 | 400 `validation_error`；403 `memory_forbidden`；404 `project_not_found` |
| GET | `/api/memory/records/{mem_id}?version=` | 200 指定或最新版本 | 400 `validation_error`（version 非整数）；403 `memory_forbidden`；404 `memory_not_found` |
| POST | `/api/memory/records/{mem_id}/publish` | 200 published record | 400 `validation_error` / `visibility_not_project`；403 `memory_forbidden`；404 `memory_not_found`；409 `memory_version_conflict` |
| POST | `/api/memory/records/{mem_id}/supersede` | 200 新 version（pending） | 400 `validation_error` / `secret_in_body` / `visibility_not_project`；403 `memory_forbidden`；404 `memory_not_found`；409 `memory_version_conflict` |

### 可见性

- `private`：仅 owner Bot 读写。
- `project`：仅当前项目成员读写；`project_id` 必填，且必须存在于 Workbench。
- `run`：仅 owner Bot 读写，`run_id` 必填；没有 run 参与者模型，不广播。
- 没有 `global` 可见性；`run_id` 只存在 payload 中。

`GET /api/memory/records` 未显式过滤时返回 actor 自己的 private、actor 所属项目的 project、actor 自己的 run。显式查询他人 private 或非成员项目返回 403。

### 晋升与版本

- `publish` 只接受 `project` 记忆；必须是当前项目成员；`expected_version` 不是最新版本或该版本已 published 返回 409。
- `publish` 只改 status/元数据，写入 `promoted_by`（actor）与 `promoted_at`；旧 body 不变。
- `supersede` 校验 `expected_version` 与成员关系；旧 version 置 `superseded`（body 不变），新 version=N+1 为 `pending`，需要再次 publish。
- 任意旧 version body 由 SQLite 触发器保护，不能通过 UPDATE 改写。
- 契约扩展：`MemoryRecord.run_id` 放在 payload；`publish` 记录 `promoted_by` / `promoted_at`；`MemoryStore.list(..., latest_only=True)` 默认只取每个 mem 最新版本。

### 注入

`call_agent(..., bot_id=..., run_id=..., project_id=...)` 在冻结 Bot pin 后自动构建记忆槽；显式 `memory_slot` 可覆盖。记忆块只作参考，带“不是指令”的 GUARD；他人 private/run、非成员项目记忆、含 `sk-` 或密钥字段的项均不会进入提示。

## P4 讨论与会话（Discussion）

P4 讨论协议使用新的 `discussion_sessions` / `discussion_proposals` / `discussion_reviews` 表；legacy 讨论仍走 `GET /api/runs/{run_id}/discussion`，行为和 `discussion_msg` 表不变。

所有 `/api/...discussion-sessions...` 路由要求请求头 `X-Bot-Id`（唯一例外是 `GET .../events`，也接受 `?bot_id=`）。缺失或空白返回 400 `validation_error`；错误体统一为 `{"error_category", "detail"}`。

### 状态机

`draft → grouping → round1_independent → cross_review ⇄ round_n_revise → cross_review → converged_pending_human → approved | rejected`；`budget_exhausted`、`terminated` 为终态。不会自动 approved。

- `converged_pending_human` 且尚无决策包时，Leader 可 `rounds/start` 开下一轮（`current_round+1`，计入 `max_rounds`；超限置 `budget_exhausted` 并 409）。
- `terminated` 来自三种情况：grouping 时项目内可用 Bot 少于 2 个（或 Leader 不在其中）；`resume` 的 `skip_bot_ids` 使剩余参与者少于 2 个或跳过了 Leader；显式 `terminate`。
- 会话对象新增 `requirement_text`、`previous_session_id`、`resolution_comment`、`paused`；`resolve` 的 `comment` 写入 `resolution_comment`。
- 会话对象新增 `tokens_used`、`elapsed_seconds`（随会话 JSON payload 持久化；老记录缺字段时按 0 读取）。`tokens_used` 是已累计的模型 `tokens_in + tokens_out`；`elapsed_seconds` 只统计驱动器实际运行的时间，暂停期间和无后台任务时不计。驱动器在每个 `step` 结束以及暂停 / 终止后写回这两个字段，进程重启或恢复时从记录续算，因此 `DiscussionBudget.max_tokens` / `max_wallclock_seconds` 跨重启仍然生效。

### 路由

| 方法 | 路径 | 成功 | 主要错误 |
|---|---|---|---|
| POST | `/api/projects/{project_id}/discussion-sessions` | 201 `DiscussionSession`（draft） | 400 validation_error / secret_in_body；403 forbidden；404 project_not_found；409 leader_not_in_project |
| POST | `/api/discussion-sessions/{sid}/group` | 200 `DiscussionSession`（grouping） | 403 forbidden；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/rounds/start` | 200 `DiscussionSession` | 403 forbidden；409 invalid_status / budget_exhausted |
| POST | `/api/discussion-sessions/{sid}/proposals` | 201 `{proposal_id, sealed}` | 403 forbidden / not_participant；409 invalid_status / duplicate_proposal |
| GET | `/api/discussion-sessions/{sid}/proposals` | 200 `{"items": [...]}` | 403 not_participant；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/reviews` | 201 票 | 400 validation_error；403 forbidden / not_participant；404 proposal_not_found；409 invalid_status / self_review_forbidden / duplicate_review |
| POST | `/api/discussion-sessions/{sid}/converge` | 200 `{action, reason, session, dissent_items}` | 403 forbidden；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/submit-decision` | 201 `DecisionPackage` | 403 forbidden；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/resolve` | 200 `DiscussionSession` | 400 validation_error；403 forbidden；404 session_not_found / run_not_found；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/run` | 200 `{running, session}`（幂等） | 400 validation_error；403 forbidden；404 session_not_found；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/pause` | 200 `DiscussionSession` | 400 validation_error；403 forbidden；404 session_not_found；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/resume` | 200 `DiscussionSession`（可选 `{skip_bot_ids}`） | 400 validation_error；403 forbidden；404 session_not_found；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/terminate` | 200 `DiscussionSession`（必须 `{"confirm": true}`） | 400 validation_error；403 forbidden；404 session_not_found；409 invalid_status |
| GET | `/api/discussion-sessions/{sid}/messages?after=<seq>` | 200 `{"items": [...]}` | 400 validation_error；403 not_participant；404 session_not_found |
| GET | `/api/discussion-sessions/{sid}/events` | SSE（允许 `?bot_id=`） | 400 validation_error；403 not_participant；404 session_not_found |

### 盲首轮与密封形状

- `rounds/start`：仅 Leader。grouping → round1_independent；cross_review / round_n_revise 进入下一轮 round_n_revise；`converged_pending_human` 且尚无决策包时也可开下一轮（`current_round+1`，计入 `max_rounds`）。超过 `budget.max_rounds` 返回 409 budget_exhausted。
- 全员本轮交齐后自动把本轮 proposal 置 `sealed=0` 并 open cross_review；最后一票返回 `sealed=false`。
- `GET proposals` 密封期对非作者返回 `{"sealed": true, "body_md": null}`；作者本人可见正文；解封后所有 participant 可见正文。
- 同一 (session, author, round) 重复提交返回 409 duplicate_proposal。

### 交叉评审

- reviewer 必须是 participant；proposal 必须属于本 session。
- 自评返回 409 self_review_forbidden，且不落票；重复票 409 duplicate_review。
- 硬门槛只统计 `coverage` / `conflicts_closed_or_recorded` / `evidence_complete` 布尔值；分数按方案汇总（`proposal_totals` / `proposal_spread`），只在 `score_gap_threshold` 模式下参与收敛判断，不用于挑选优胜方案。
- `converge` 可选 body（扩展）：`{tokens_used?, elapsed_seconds?, dissent_items?}`；返回的 `dissent_items` 原样保留。

### 收敛决策表

`score_gap_threshold` 有值（新建会话默认 2.0）时，按方案分数差收敛：

| 顺序 | 条件 | action |
|---|---|---|
| 1 | token 或 wallclock 预算耗尽 | budget_exhausted |
| 2 | 全部硬门槛通过，且方案平均总分差 ≤ `score_gap_threshold` | submit_human（正常收敛） |
| 3 | 当前轮 >= max_rounds（仍未达成条件 2） | submit_human（到顶强制交 Leader） |
| 4 | 其他 | revise |

阈值模式**不返回** `no_improvement`：未到轮次上限时一律再来一轮，只有满足条件 2 或轮次到顶才交 Leader。

- 到顶强制（顺序 3）在消息流里发 system `forced_submit`，文案写明轮次上限、分差 / 阈值、未通过硬门槛数量，不再说“达到收敛条件”。
- 同时在决策包 `dissent_items` 里写入一条 `未达成一致：第 N 轮上限，分差 x（阈值 y），未通过硬门槛 k 项`，供人工审批时识别。
- `score_spread is None`（少于 2 个可比较方案）视为不满足条件 2，到顶时文案写“分差无法计算”。

`score_gap_threshold=None` 时保持旧规则（硬门槛 + dissent 覆盖分支）：

| 顺序 | 条件 | action |
|---|---|---|
| 1 | token 或 wallclock 预算耗尽 | budget_exhausted |
| 2 | 全部硬门槛通过；或未通过项已记录进 dissent | submit_human |
| 3 | 当前轮 >= max_rounds | submit_human |
| 4 | 最近两轮通过项未增加 | no_improvement |
| 5 | 其他 | revise |

- 方案总分 = 各评审四个维度分数之和；`proposal_totals` 取每个方案的平均总分，`proposal_spread` = 最高均分 − 最低均分，只比较本轮至少有一票的方案。
- 可比较方案少于 2 个时 spread 未定义，阈值模式的条件 2 不成立，会落到轮次上限 / revise。
- 状态映射：budget_exhausted → budget_exhausted；submit_human / no_improvement → converged_pending_human；revise → round_n_revise。

### DecisionPackage 与人工规格门

- `submit-decision` 仅 leader 可提交；status 必须 converged_pending_human，且尚无 package。
- `decision_package_digest` 只取 `session_id` / `requirement_snapshot_hash` / `proposal_ids` / `dissent_items` / `hard_gate_summary` / `body_md`，对规范化对象做一次 sha256，不对 sha256 再 hash。
- `resolve` 接受 `decision=approved|rejected`，可选 `comment`、`run_id`；`comment` 保存到会话的 `resolution_comment`，供打回后的新会话复用。
- `resolve` 仅会话 Leader（`leader_bot_id`）可批准或打回；非 Leader 参与者返回 403 forbidden。检查顺序：404 session_not_found → 403 forbidden → 409 invalid_status（重复 approve 的幂等返回也在 Leader 校验之后）。
- approved 且提供 `run_id`：确认 run 存在后，把 `"DecisionPackage"` 写入基线。已有 `run_execution_state` 行时合并并保持原 profile / plan_hash / allowed_tool_refs；无行时只更新 run 的内存基线。绝不调用 schedule / execute_task，绝不把 execution_safety_ready 置 True。
- rejected 不写入/不覆盖 DecisionPackage hash。
- 并发两次 approve 幂等，最终 status=approved，hash 值相同。
- 扩展：`requirement_snapshot` 同时接受字符串与对象（契约为字符串）；`converge` 返回 `dissent_items`；`resolve` 的 `run_id` 为可选扩展。

### 创建会话的补充约定

- 请求体：`{leader_bot_id, participant_bot_ids, requirement_snapshot, budget?, previous_session_id?}`；`leader_bot_id` 必须等于 `X-Bot-Id`。
- `requirement_snapshot` 为字符串或对象都接受；对象会 JSON 序列化后写入 `requirement_text`，原始值仍参与 `requirement_snapshot_hash`。
- `budget` 缺省为 `{max_rounds: 3, score_gap_threshold: 2.0}`；显式传 `score_gap_threshold: null` 走旧收敛规则。
- `participant_bot_ids` 去重后少于 2 个返回 400 validation_error；`requirement_text` 含 `sk-` 类密钥返回 400 secret_in_body。

### 多 Bot 群聊（消息流与驱动器）

`run` / `pause` / `resume` / `terminate` 全部要求 `X-Bot-Id`，且只有会话 Leader 可写（其他 Bot 403 forbidden）：

| 方法 | 路径 | 成功 | 主要错误 |
|---|---|---|---|
| POST | `/api/discussion-sessions/{sid}/run` | 200 `{running, session}` | 400；403 forbidden；404 session_not_found；409 invalid_status |
| POST | `/api/discussion-sessions/{sid}/pause` | 200 `DiscussionSession` | 同上 |
| POST | `/api/discussion-sessions/{sid}/resume` | 200 `DiscussionSession` | 同上 + 400（body 非对象） |
| POST | `/api/discussion-sessions/{sid}/terminate` | 200 `DiscussionSession` | 400（缺 `confirm: true`）；403；404；409 |

- `run` 幂等：同一会话已有后台任务时直接返回当前状态；终态、或已生成决策包的 `converged_pending_human` 返回 409 invalid_status；对暂停中的会话调用等价于 `resume`。
- `pause` 置 `paused=true` 并取消后台任务，可重复调用；`resume` 清 `paused` 并重启驱动器；`terminate` 置 `terminated` 并取消任务，对 `approved` / `rejected` 返回 409。
- `resume` 可选 `{skip_bot_ids}`：只过滤本会话参与者；剩余参与者少于 2 个（或跳过 Leader）时直接置 `terminated`，不重启驱动器。
- 服务启动时会把进行中的讨论置为 `paused`（系统消息 `event=paused`、`reason=server_restart`），不会自动续跑；用户点继续（`POST /resume`）后从数据库状态接着推进。

消息流（两个只读 GET）：

| 方法 | 路径 | 成功 | 主要错误 |
|---|---|---|---|
| GET | `/api/discussion-sessions/{sid}/messages?after=<seq>` | 200 `{"items": [...]}` | 400 validation_error；403 not_participant；404 session_not_found |
| GET | `/api/discussion-sessions/{sid}/events` | SSE | 同上 |

- 身份：`messages` 只认 `X-Bot-Id`；`events` 认 `X-Bot-Id`，也接受 `?bot_id=`（讨论路由中唯一放宽查询参数的）。Leader 或参与者可读，其他 Bot 403 not_participant；会话不存在 404 session_not_found。
- `messages` 的 `after` 默认 0，按 `seq` 升序；非数字或负数按 0 处理。
- SSE 帧：`id: <seq>\nevent: message\ndata: <消息 JSON>\n\n`；连接建立先发一次 `: ping`，空闲 15 秒再发；`Last-Event-ID` 为 seq，只补发更大的 seq（非数字或负数按 0）。
- 消息 JSON：`{session_id, seq, kind, bot_id, round, payload, created_at}`，`kind ∈ system | proposal | review | leader`。
- payload 只带元数据，**消息不含方案正文**：
  - `system`：`{event, text, ...}`，event 如 `session_started` / `round_started` / `proposals_unsealed` / `converged` / `budget_exhausted` / `paused` / `resumed` / `terminated` / `bot_failed` / `bot_skipped` / `review_abstained` / `forced_submit` / `restarted_after_rejection`。
  - `proposal`：`{proposal_id, chars, truncated, round}`。
  - `review`：`{proposal_id, reviewer_bot_id, total, scores, hard_gate_results, summary}`。
  - `leader`：`{action: "submit" | "request_revision", text}`。
- 看方案或规格正文仍走 `GET /proposals`（密封期规则不变）与会话对象里的 `decision_package.body_md`。

驱动器流程与失败处理：

- `run` 起一个后台任务，每次只按 SQLite 状态推进一步：`draft` / `grouping` → 自动把项目内 active Bot（Leader 在前）编组并开第 1 轮；`round1_independent` / `round_n_revise` → 每个参与者各写一份方案（上限 6000 字符，超长先让模型压缩，仍超长则截断并标 `truncated`），交齐后解封转 `cross_review`；`cross_review` → 每个参与者评他人方案，随后调 `should_converge`；`converged_pending_human` 且无决策包 → Leader 综合写规格并自查。
- 模型调用失败（重试一次仍失败）：置 `paused=true`，写 system `bot_failed`（带 `bot_id`、`category`），不丢已有进度；Leader 用 `resume` 重试或 `skip_bot_ids` 跳过该 Bot。
- 评分 JSON 两次都不合法：该票弃权（不落票），写 system `review_abstained`，继续其余评审。
- Leader 自查 `ok=false`（自查 JSON 不可解析也算未通过）：起下一轮（计入 `budget.max_rounds`）；轮次到顶则把当前规格强制提交为决策包，写 system `forced_submit`。
- 讨论会话没有 run，驱动器不使用冻结 pin；每次调用读取 Bot 当前的模型 / Key、私有记忆与资料文件。

打回后用 `previous_session_id`：

- 上一会话被 `rejected` 后，可用 `previous_session_id` 新建会话继续讨论。
- 驱动器把上一会话的 `decision_package.body_md` 作为「上一版规格」、把 `resolution_comment`（本会话优先，否则取上一会话）作为「用户意见」注入方案提示，并写 system `restarted_after_rejection`。
- 新会话有独立的 `requirement_text`、预算与参与者；上一会话的状态和决策包不变。

## P5 执行 DAG、连续执行与模块人验收

所有新增路由都要求 `X-Bot-Id` 请求头作为调用者身份；缺头或空白返回 400 validation_error。

| 方法 | 路径 | 请求 | 成功 | 失败 |
|---|---|---|---|---|
| POST | `/api/runs/{run_id}/module-acceptances` | `{module_id, task_codes, status, evidence_uris, reviewer?, comment?}` | 201 `ModuleAcceptance` | 400 validation_error；403 forbidden；404 run_not_found |
| POST | `/api/runs/{run_id}/defects` | `{task_code, module_id, related_requirement_id?, evidence_uris, detail}` | 201 `DefectRecord`（status=open） | 400 validation_error；404 run_not_found |

### 调度与 DAG

- `POST /api/runs/{run_id}/schedule` 行为不变；granted_v1 额外要求 grant 已签的 key（含 `DecisionPackage`）与 run 当前 `approved_baseline_hashes` 相等，否则 409 baseline_stale。
- 显式请求的后继任务若前置未成功（非 `done`），返回 409 dag_blocked 且不进入执行；`task_codes` 省略时仍由 `select_tasks` 按依赖挑选，legacy run 不受影响。
- 人批一次 grant 后可在 `grant.task_codes` 内连续执行，不逐任务重新 `POST /execution-grants`；超范围仍 409 scope_mismatch，无 grant 仍 403 grant_required。
- 同一 run 的 schedule / execute / 验收写路径共用一把 per-run 锁；pause / terminate 会 bump generation，过时的工具或模型回包不改状态、不写证据。

### 验收与缺陷

- `accepted` 与 `rejected` 都必须带非空 `evidence_uris`，且 URI 必须已存在于对应任务的证据中；`accepted` 还要求任务处于成功状态。
- `model_self_review=true` 一律 400，不作为验收证据。
- `rejected` 自动为每个 task_code 建一条 open 缺陷；缺陷不会自动 resolved。缺陷把任务置为 `failed`（可经既有 `retry` 修复），不打开 force-pass。
- 本路径与遗留整 run 验收 `POST /api/runs/{run_id}/accept` 完全独立；granted_v1 上的 `granted_acceptance_disabled`、`granted_force_pass_disabled` 保持不变。

## 项目对话补充与 Leader 任务编排

项目对话与任务编排使用以下 Leader 写接口。两者要求 `X-Bot-Id`。

| 方法 | 路径 | 请求 | 成功 | 失败 |
|---|---|---|---|---|
| POST | `/api/discussion-sessions/{session_id}/supplement` | `{text}`，1–2000 字符 | 201，关联上一会话的新讨论 | 400 空白或密钥内容，403 非 Leader，409 已结束或成员变更 |
| POST | `/api/discussion-sessions/{session_id}/plan` | 无请求体 | 200 `{run_id}`，进入 PLAN 确认 | 403 非项目 Leader，409 需求未批准，422 计划校验失败，502 模型失败 |

补充信息写入新讨论的需求快照。需求批准后由 Leader 生成规格、设计和任务计划，已有运行可重复查询返回同一个 `run_id`。

## P6 前端使用的只读查询

P6 前端工作台需要读取验收、缺陷、讨论会话与消息流；P6 新增的只读 GET 如下，除 `events` 可用 `?bot_id=` 外全部要求 `X-Bot-Id`：

| 方法 | 路径 | 成功 | 失败 |
|---|---|---|---|
| GET | `/api/runs/{run_id}/defects` | 200 `{items: DefectRecord[]}` | 400 validation_error；404 run_not_found |
| GET | `/api/runs/{run_id}/module-acceptances` | 200 `{items: ModuleAcceptance[]}` | 400 validation_error；404 run_not_found |
| GET | `/api/projects/{project_id}/discussion-sessions` | 200 `{items: DiscussionSession[]}` | 400 validation_error；404 project_not_found |
| GET | `/api/discussion-sessions/{session_id}` | 200 `DiscussionSession` | 400；403 not_participant；404 session_not_found |
| GET | `/api/discussion-sessions/{session_id}/reviews` | 200 `{items: ReviewBallot[]}` | 400；403 not_participant；404 session_not_found |
| GET | `/api/discussion-sessions/{session_id}/messages?after=` | 200 `{items: DiscussionMessage[]}` | 400；403 not_participant；404 session_not_found |
| GET | `/api/discussion-sessions/{session_id}/events` | SSE `text/event-stream` | 400；403 not_participant；404 session_not_found |

- 讨论的只读 GET（含 `messages` / `events`）只对 leader 或 participant 返回内容；非参与者 403 not_participant。`messages` 只认 `X-Bot-Id`，`events` 也接受 `?bot_id=`。
- `reviews` 只返回投票 payload（分数、逐项依据、硬门槛、异议），不包含任何提案正文，盲首轮不会经此泄漏他人草案。
- `messages` / `events` 同样只带消息元数据，不含方案或规格正文；SSE 帧格式与 `Last-Event-ID` 续传见 P4「多 Bot 群聊（消息流与驱动器）」。
- 未新增写接口、未改任何既有 POST 语义。Alembic head 现为 `0012`：本轮只新增 `discussion_messages` 表（迁移 `0012_discussion_messages`），其余表结构未变。

## 工作流阶段投影（加法字段，2026-11-24）

只读查询新增 `workflow` 对象，不改变既有字段与语义；旧客户端可忽略。

| 方法 | 路径 | 附加字段 |
|---|---|---|
| GET | `/api/runs/{run_id}` | `workflow` |
| GET | `/api/runs/{run_id}/monitor` | `workflow` |
| GET | `/api/discussion-sessions/{session_id}` | `workflow` |
| POST | `/api/discussion-sessions/{session_id}/plan`（409） | 错误体附 `workflow`，`error_category` / `detail` 不变 |

`workflow` 形状：`{stage, status, project_id, session_id, run_id, spec_approved, plan_approved, blocked: [{code, detail}], baseline_hashes, model_mode, execution_mode, evidence}`。

- `stage` 是内部阶段（`discussing`、`spec_pending`、`spec_approved`、`planning`、`plan_pending`、`plan_approved`、`authorization_pending`、`executing`、`verifying`、`accepted`，以及 `blocked` / `invalidated` / `needs_reconciliation`）；对外 `status` 仍是原 discussion/run 状态。
- 投影是纯查询：不写库、不改状态；项目/会话绑定不一致时返回 `blocked` + `cross_project_mismatch`，不会静默改写历史。
- 未批准规格时 `POST /plan` 仍返回 409 `invalid_status`「需先确认需求规格」，且不创建 run。

## 执行授权边界（2026-11-24）

所有会触发任务执行的入口共用同一服务端决策：`/schedule`、自动调度循环、`/tasks/{id}/{action}` 的 retry/takeover/submit-takeover/force-pass、`/accept`。

| 场景 | 结果 |
|---|---|
| 规格已批准、PLAN 门仍 pending | 409，拒绝且无任务副作用 |
| legacy run + 真实 provider（非 scripted/replay） | 403 `profile_not_granted_v1`；真实执行必须升 `granted_v1` 并取得 active grant |
| legacy run + scripted/replay provider | **不再因此允许**；需显式注入无副作用模拟执行器，否则同真实执行拒绝（403 `profile_not_granted_v1`） |
| 注入的模拟执行器 | 允许调度，任务证据 `simulated`；不建 worktree/仓库、不跑命令、不 merge |
| granted_v1 + 真实 provider + 总闸关闭 | 409 `execution_safety_not_ready` |
| granted_v1 + 真实 provider + 总闸开启 | 进入既有 grant 范围 / 基线 / DAG / 工具校验 |
| profile 缺失或冲突 | 409 `profile_unspecified` / `profile_conflict` |

`execution_safety_ready` 仍为服务端只读开关且默认 `False`；没有开闸路由或前端入口。脚本成功不等于真实测试通过：成功响应与 monitor 的 `evidence` 会分别标注 `model_mode` / `execution_mode` / `verification_status`。

## 基线失效与崩溃和解（2026-11-24）

- 已批准 SPEC/DESIGN/PLAN（或 DecisionPackage）与当前产物哈希不一致时，`/schedule`、任务执行、`/accept` 返回 409 `baseline_stale`；run 被暂停，`workflow_invalidations` 追加一条历史记录，active grant 标为 `stale`。历史记录与 grant 行不删除；重新批准并取得新 grant 后才可继续。
- 模拟执行器（仅由 `create_app(execution_policy=ExecutionPolicy(simulated=True))` 构造注入）现在覆盖 accept、takeover、submit-takeover、force-pass、release 导出：不建 repo/worktree、不跑命令、不 tag/copy；验收证据为 `simulated://`，发布包只写元数据 JSON、不导出代码树。产品默认不注入。
- `POST /api/runs/{run_id}/reconcile` 返回只读报告：`{run_id, needs_reconciliation, tasks:[{task_code,state,evidence_count,status:"unknown"}], note}`。重启后处于 running/verifying（含已有部分 evidence）的任务被暂停并标记 `needs_reconciliation`；调度/手动 retry 对其返回 409 `needs_reconciliation`，不会自动重放。
- `POST /api/runs/{run_id}/reconcile/{task_code}`（需 `X-Bot-Id`）是受控决议：`decision=continue_reconcile|accept_evidence|mark_failed_safe_retry`，带 `expected_revision`。`accept_evidence` 走只读 `verify_task_completion`：attempt 必须在历史中，且 task/run/project、基线、repo 身份、write_set 在 commit 树、commit 在目标分支 ancestry 全部通过；README HEAD 或任意 commit 不再被接受。`mark_failed_safe_retry` 还要求非空 `verified_safe_scope` 与 `risk_accepted=true`，写入 reconciliation_history。只读报告不等于恢复完成。
- 基线漂移或 CR/重排产生不可变候选：`workflow_candidates[candidate_id]` 冻结 SPEC/DESIGN/PLAN 文档、canonical hashes、父基线、project/run/session 与 candidate_hash；新候选取代旧 pending，旧门转 `superseded`。
- 候选门 `PLAN基线确认` payload 含 `candidate_id`、`candidate_hash`、`changed_keys`、文档与 `source_gate_id`。`POST /api/gates/{gate_id}/resolve` 对候选门**必须**带 `expected_revision`（缺 400），只采用门绑定的候选快照，不读取当时 live artifacts；旧/被取代门 409。若 `SPEC` 变更，body 需 `payload.acknowledge_spec_change=true` + `payload.reason` 才可采用（400 `spec_reapproval_required`）。采用后旧 grant 仍 stale。
- 存在 `baseline_reapproval_required` 时 `POST /api/runs/{run_id}/resume` 返回 400，不会靠 resume 重新调度。
- 证据修正：验收 `pass=false` 后人工批准记为 `verification_status=overridden`（标签“人工覆盖（原验收未通过）”），不再显示测试通过；仅含 skipped/cancelled 的任务不计 execution；模块验收/缺陷响应的 run 级聚合改名为 `run_evidence`，对象结论用 `decision`/`evidence_uris`。
- 有批准哈希但无法证明来源（无 approval、无已裁决基线门、无 fixture 标记）的 run 返回 409 `baseline_unverifiable`，要求显式再批准。
- 模块验收 `accepted` 复验会把同任务旧的 open/reopened 缺陷标为 `resolved`，保留原缺陷行并记录 `resolved_by_acceptance_id`。


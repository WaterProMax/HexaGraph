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
| POST/GET | `/projects` | 建项目 / 列表 |
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
| GET | `/runs/{id}/events/history?after=` | 历史事件 |
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
| GET | `/api/skills` | 200 `{"items": [...]}` | — |
| GET | `/api/skills/{skill_id}/versions` | 200 `{"items": [...]}` | 404 `skill_not_found` |
| POST | `/api/bots` | 201 `BotInstance`（服务器生成 `bot_id`） | 400 `validation_error`；409 `bot_name_conflict` |
| GET | `/api/bots?status=active\|archived` | 200 `{"items": [...]}` | 400 `validation_error`（非法 status） |
| GET | `/api/bots/{bot_id}` | 200 `BotInstance` | 404 `bot_not_found` |
| PATCH | `/api/bots/{bot_id}` | 200 更新后的 `BotInstance`，附加只读整数 `pin_revision` | 400 `validation_error`；404 `bot_not_found`；409 `bot_name_conflict` / `bot_archived` |
| POST | `/api/bots/{bot_id}/archive` | 200 `{"bot_id", "status": "archived"}` | 404 `bot_not_found`；409 `bot_already_archived` |
| POST | `/api/projects/{project_id}/memberships` | 201 `ProjectMembership` | 404 `project_not_found` / `bot_not_found`；403 `bot_archived`；409 `membership_exists` / `leader_already_set` |
| GET | `/api/projects/{project_id}/memberships` | 200 `{"items": [...]}` | 404 `project_not_found` |
| DELETE | `/api/projects/{project_id}/memberships/{bot_id}` | 204，无响应体 | 404 `membership_not_found` |

- 未注册 `POST /api/projects/{project_id}/bots`；该路径自然 404，且不写 `bots` 表。
- 同一项目至多一个 `is_leader=true`；同一 Bot 可加入多个项目。移出项目只解除成员关系，不删除 Bot 或其 pin 历史。
- Bot 的 `model` / `provider_ref` / `skill_bindings` 变更会追加 pin revision；同一 `(run_id, bot_id)` 的冻结快照在运行开始时写入 `run_bot_pin_snapshots`，运行中 PATCH Bot 不改变已冻结值。
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
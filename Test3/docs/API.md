# Test3 HTTP 约定

前缀：`/api`。CORS 仅放行 `http://127.0.0.1:5173` 与 `http://localhost:5173`。

本表只证明路由在 `backend/app/api/routes.py` 中存在，不代表每个分支都有独立集成测试。

## 信封与错误

| HTTP | 含义 |
|---|---|
| 200 | 成功；多数接口直接返回对象，没有统一 `{code,data}` 包一层 |
| 400 | 非法转换、缺控制理由、缺 `FEEDBACK_HASH_KEY` |
| 404 | 项目 / 运行 / 关卡 / 任务不存在 |
| 409 | `expected_revision` 与任务当前 `revision` 不一致 |

乐观锁：`POST /tasks/{task_id}/{action}` 与关卡决议体可带 `expected_revision`。任务控制比较的是**任务** revision，不是 run revision。

## 路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | `{status: ok}` |
| POST/GET | `/projects` | 建项目 / 列表 |
| POST | `/projects/{id}/runs` | 建运行并立刻 `start_idea` |
| GET | `/runs/{id}` | 状态、阶段、关卡、revision |
| GET | `/runs/{id}/stages` | 当前阶段与历史 |
| GET | `/runs/{id}/artifacts` | 产物字典 |
| GET | `/runs/{id}/discussion` | 问题、合并表、发言、争议 |
| GET | `/runs/{id}/todos` | 未决关卡 + `needs_human` 任务 |
| POST | `/gates/{id}/resolve` | `decision` + `payload` |
| GET | `/runs/{id}/tasks` | 任务列表 |
| GET | `/tasks/{id}` | 任务详情 |
| POST | `/tasks/{id}/{action}` | pause/resume/retry/skip/takeover/force-pass/patch |
| POST | `/runs/{id}/pause` `/resume` `/terminate` | 运行级控制 |
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

## SSE

`GET /runs/{id}/events`：`text/event-stream`。从 `Last-Event-ID`（数字 seq）之后重放内存事件，然后每 15 秒打 `: ping`。这是轮询 `RunState.events`，不是持久化 `EventBus` 订阅。

进程重启后内存运行态丢失。SQLAlchemy / Alembic 表（`backend/app/storage/models.py`）有独立集成测试，HTTP 主路径尚未把每次关卡写入 SQLite。

## 控制动作可用状态

后端 `require_control` 与前端 `controlEnabled` 对齐 Design.md 16.3 的子集：`retry`/`force-pass` 仅 `needs_human|failed`；`skip`/`pause` 覆盖未完成态。缺理由的 `force-pass` 被拒绝。

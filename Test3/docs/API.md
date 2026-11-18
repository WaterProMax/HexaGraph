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
  "provider": "existing|deepseek（可选，默认 existing；deepseek 仅本次运行使用 DeepSeek）"
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

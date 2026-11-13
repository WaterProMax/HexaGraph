# Issue #15 接口契约（冻结版 v1）

关联 Issue #15；参考 PR #20（郭婷婷）的草稿 `issue-15-api-contract-draft.md`（该分支保留，本文不覆盖）。
本文只描述**已实现且有测试覆盖**的行为；完整路由表见 `docs/API.md`，结构快照见 `backend/tests/integration/snapshots/openapi_structure.json`。

## 错误码（以代码实测为准）

错误体保持 FastAPI 默认 `{"detail": ...}`。草稿提出的 `{code, detail}` 机器码字段**未采纳**（会改变线上格式，需另行约定）。

| HTTP | 条件 | 测试 |
|---|---|---|
| 400 | 终止缺 `confirm:true`；`ValidationFailed` / `IllegalTransition`（关卡、任务控制、变更单决策、accept）；`PATCH /limits` 未知键；缺 `FEEDBACK_HASH_KEY` | `test_api_contract.py` |
| 404 | 项目 / 运行 / 关卡 / 任务 / 变更单不存在（`POST /crs/{code}/decision` 原为 500） | 同上 |
| 409 | `expected_revision` 不一致（关卡对比 run revision，任务对比任务 revision）；`POST /runs/{id}/accept` 无 SPEC（原为 500） | 同上 |
| 422 | FastAPI 校验失败：缺字段、`after=abc`、缺 `codes`、`PATCH /limits` 非对象体、终止无 body | 同上 |

对草稿的事实修正：

- 未知变更单：修复前为 **500**（草稿 §2.3 写“现为 400”，§4.7 写 500，自相矛盾）；现为 404。`decide_cr` 抛出的 `ValidationFailed` 映射为 400。
- `PATCH /limits` 非对象体是 **422**（草稿写 400）。
- `PUT /config/models` 非法结构现状是 **500**（`ModelsFile.model_validate` 异常未转换），草稿写 422 并建议统一；该路由归模型配置职责，本 PR **不改**，列为已知限制。
- 非法 `Last-Event-ID`：修复前 500；现按 0 处理（全量回放）。

## SSE

`GET /api/runs/{id}/events`

- 帧：`id: <seq>\nevent: message\ndata: <事件 JSON>\n\n`，与修复前一致。
- 事件追加后立即推送（测试要求 ≤1 秒）；`: ping` 心跳在连接建立时发一次，之后每 15 秒无事件时发一次。
- `Last-Event-ID` 数字 seq 之后续传、不重复、保序；非法值按 0。
- 先订阅再回放，防止竞态丢事件；断开后取消订阅。
- 事件来源仍是 `RunState.events`；`runtime.emit` 经 `BUS.emit_sync` 唤醒订阅方。未改 runtime/recovery。恢复事件（`seq=0` 等）语义由 #16 约定，本文不涉及。

## 已知限制

- `PUT /config/models` 非法体 500（#17 范围）。
- `seq` 以进程内 `len(run.events)+1` 生成，重启后连续性属 #16。
- 未在真实浏览器 `EventSource` / Vite 代理下验证。
- 未与 #16/#17 负责人确认（按任务要求不联系组员）。

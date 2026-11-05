# Test3 交接

## 本轮已补（六处缺口）

1. 合并冲突生成「冲突解决」任务（P0、写集=冲突文件），优先调度；该任务失败才把源任务打到 `needs_human`。
2. 验收未通过项自动提缺陷变更单（小变更，最多 2 轮）；通过确认后打 `build-<版本>` 并导出 `data/runs/<id>/release/`。
3. FastAPI lifespan 启动 5 秒调度兜底循环，只扫未暂停的活动运行。
4. `takeover` 锁定并给出工作区路径；`submit-takeover` 走同一套验收/评审/合并。终止运行必须 `confirm=true`，前端有二次确认。
5. 变更批准后 SPEC/DESIGN/PLAN 升到 1.1，未受影响条目逐字相同，CR 标 `applied`。
6. embedding 失败走 `cluster_fast`（fast 槽分批归类），不再回退字符向量。

## 本轮已改（审核必须项）

- **执行不再假通过。** `execute_task` 走 `run_tool_agent` + `TaskToolset.write_file/run_command`，跑完全部验收命令，按 profile 的 empty/skip 模式调用 `judge_output`。命令被拒、超时、空验收、无真实产出、写集越界都不能 `done`。合并后在集成分支跑已完成任务验收和 profile `test_command`，失败则回滚。
- **修复带上下文。** 下一轮编码输入包含 `prev_output` / `review_issues`。LLM/超时/解析失败按 `classify` 的环境故障字段做最多 3 次退避。合并冲突转 `needs_human`。重排关卡会再调分解员并 `check_task_graph`，旧未完成任务标 `cancelled`。
- **白名单与杀进程。** `python-pytest` 只放行 `pytest` / `python -m pytest` / `python -m` / `ruff check`；超时 `killpg`。
- **验收。** `accept()` 在集成分支实跑 F/N 对应验收命令并写 `reason`。`验收确认` 在 `pass=False` 时必须带理由，否则拒绝。前端未通过时禁用空理由批准。
- **限制与调度。** 每个 run `deepcopy` 一份 limits；PATCH 深合并并校验键。`schedule_once` 用 `asyncio.gather` 并发所选任务，传入 `budget_exhausted`，按任务累计令牌，超限 `budget.warn` / `needs_human`。
- **控制。** `resume` 与 `pause` 状态集一致；`skip`/`force-pass` 必须写理由；`retry` 会再走执行器；关卡只能 pending 裁决一次，带乐观锁；运行级 pause/resume/terminate 发 `control.*`。
- **讨论。** `Utterance.rule` 写入规则号，事件和讨论页可见。评审争议类退回会 `reopen_issue` 并续 I 编号；`moderator_final` 会调用；无效发言重写一次。
- **监听。** 提炼/评估走 `call_agent`；红线和类别来自 Agent。关键词只作已决策去重辅助。空 scripted 夹具时不会再因「学号/别的楼」推出 I-03/I-04。
- **变更。** `evaluation_pass` 返回 `(ok, flags)`，红线单独标出。路由传递 `kind`。批准发 `task.state_changed(change_impact)` 且 stale→ready。批准后增量升到 1.1，未受影响条目逐字保留，状态标 `applied`。
- **网关。** 角色温度和 schema 传给提供者；备用模型同样累加令牌，并把 `llm.fallback` 写入 run 事件。

## 已知限制（本轮仍未做）

1. **HTTP 运行态在内存。** `Workbench` 持有 projects/runs。SQLAlchemy / Alembic / `EventBus` 有测试，但主路径不写 SQLite。重启丢失。
2. **任务状态有两处写入。** 计划要求只经 `transition()`。内存路径用 `next_task_state` / 直接赋值。
3. **P07–P11 全链路仍薄。** 没有想法→验收的一条 scripted 长跑。设计评审未接两位架构评审。
4. **控制未完成项。** `patch` 明确拒绝。takeover / submit-takeover、终止二次确认、5 秒调度兜底已补。
5. **令牌。** scripted 提供者为 0，预算页在 scripted 下看不到消耗。
6. **监听聚类。** embedding 失败走 `cluster_fast`（fast 槽），不再回退字符向量。没有 40 条 E8 全案。
7. **变更 1.1。** 批准后 SPEC/DESIGN/PLAN 升 1.1，未受影响条目保持逐字相同，CR 标 `applied`。
8. **前端。** 无 Playwright、无录屏。
9. **E1–E10 replay。** 只有 README，无编号 JSON。
10. **真实百炼。** 未跑 `make check-models` / `make test-live`。
11. **SSE。** 15 秒轮询内存事件。
12. **`POST /config/models/test`。** 固定返回。

## 与设计的偏差

| 设计 | 实现 |
|---|---|
| 阶段/任务/事件持久化 | 内存为主，DB 测试旁路 |
| 任务状态只经 `transition()` | 内存路径直接改 |
| 设计两位背靠背评审 | 未接线 |
| replay E1–E10 | 未录 |
| 反馈 HMAC 必填 | API 缺密钥 400；单测直接传 key |
| embedding 聚类 | 失败走 fast 槽分批归类，不再用字符向量 |
| 默认 LLM 为 dashscope | 进程默认 `scripted`，避免空密钥外呼 |
| 变更批准即应用 1.1 | 批准后升 1.1 并标 `applied` |

## 建议下一步

1. 把 `Workbench` 每次 `emit` / 关卡 / 任务改写落到同一 SQLite 事务。
2. 内存任务改走 `transition()`。
3. 录 E1–E10 replay，补想法→验收 e2e。
4. 有密钥后跑 `make check-models`。
5. Playwright 控制台演示；录 E1–E10 replay。

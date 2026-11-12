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
- **白名单与杀进程。** `python-pytest` 只放行 `pytest` / `python -m pytest` / `python -m ruff` / `ruff check`；`forbidden_prefixes` 先于白名单拦截（含 `python -m pip`）；超时 `killpg`。
- **验收。** `accept()` 在集成分支实跑 F/N 对应验收命令并写 `reason`。`验收确认` 在 `pass=False` 时必须带理由，否则拒绝。前端未通过时禁用空理由批准。
- **限制与调度。** 每个 run `deepcopy` 一份 limits；PATCH 深合并并校验键。`schedule_once` 用 `asyncio.gather` 并发所选任务，传入 `budget_exhausted`，按任务累计令牌，超限 `budget.warn` / `needs_human`。
- **控制。** `resume` 与 `pause` 状态集一致；`skip`/`force-pass` 必须写理由；`retry` 会再走执行器；关卡只能 pending 裁决一次，带乐观锁；运行级 pause/resume/terminate 发 `control.*`。
- **讨论。** `Utterance.rule` 写入规则号，事件和讨论页可见。评审争议类退回会 `reopen_issue` 并续 I 编号；`moderator_final` 会调用；无效发言重写一次。
- **监听。** 提炼/评估走 `call_agent`；红线和类别来自 Agent。关键词只作已决策去重辅助。空 scripted 夹具时不会再因「学号/别的楼」推出 I-03/I-04。
- **变更。** `evaluation_pass` 返回 `(ok, flags)`，红线单独标出。路由传递 `kind`。批准走 `spec_writer`/`architect`/`decomposer` 增量重写，splice 支持受影响条目的新增/删除，合并结果再检查；PLAN 新卡写回 `stale`/`done` 任务（保留 evidence）。版本按已冻结基线递增（1.1→1.2）；驳回标 `rejected`。`stale` 保持到调度器发 `change_approved`。
- **网关。** 角色温度和 schema 传给提供者；备用模型同样累加令牌，并把 `llm.fallback` 写入 run 事件。工具消息带 assistant `tool_calls.id` 与 `tool_call_id`；scripted 提供者校验协议。
- **关卡驳回。** SPEC/DESIGN/PLAN 驳回重写；争议清单驳回重新开同一类关卡；重排/变更驳回只记录不执行。
- **并发合并。** 每个 run 一把 `asyncio.Lock` 包住 merge + 回归 + 回滚，失败 `reset --hard` 不会抹掉其他已合并任务。
- **运行态。** `emit` 追加 JSONL；状态变化时原子写 snapshot（临时文件 + `os.replace`）。启动时从 snapshot + JSONL 恢复并 `recover_tasks`。任务状态只经 `_set_state` → `apply_transition`。未进 SQLite 事件表。
- **设计评审。** `run_design` 调 `review_arch`/`review_quality`，不通过走 `route_design_review`。
- **文档重写循环。** `_write_checked` 把检查错误回给撰写人，最多 N 次；仍不过开「文档检查失败」关卡。
- **冲突 worktree。** `_unlock_origin_after_conflict` 用 `git worktree remove --force` + prune；`create_worktree` 遇残留会清登记后重试。
- **令牌。** 网关按调用记到 ContextVar 累加器，并发任务不再用全局差值重复计。

## 已知限制（本轮仍未做）

1. **主路径仍不是 SQLite 双写。** 运行态落 JSONL/snapshot，可重启恢复；SQLAlchemy 事务路径仍主要给测试。
2. **控制未完成项。** `patch` 明确拒绝。takeover / submit-takeover、终止二次确认、5 秒调度兜底已补。
3. **监听聚类。** embedding 失败走 `cluster_fast`（fast 槽），不再回退字符向量。没有 40 条 E8 全案。
4. **前端。** 无 Playwright、无录屏。
5. **E1–E10 replay。** 只有 README，无编号 JSON。
6. **真实百炼。** 未跑 `make check-models` / `make test-live`。工具协议已在 scripted 侧校验。
7. **SSE。** 15 秒轮询内存事件。
8. **`POST /config/models/test`。** 固定返回。

## 与设计的偏差

| 设计 | 实现 |
|---|---|
| 阶段/任务/事件持久化 | 仅 JSONL + 原子 snapshot，未进 SQLite 事件表 |
| 任务状态只经 `transition()` | 内存路径走 `apply_transition`；事件未进事件表，仅 JSON 可恢复 |
| 设计两位背靠背评审 | 已接线 `review_arch` / `review_quality` |
| replay E1–E10 | 未录 |
| 反馈 HMAC 必填 | API 缺密钥 400；单测直接传 key |
| embedding 聚类 | 失败走 fast 槽分批归类，不再用字符向量 |
| 默认 LLM 为 dashscope | 进程默认 `scripted`，避免空密钥外呼 |
| 变更批准即应用 1.1 | 增量重写后升小版本（1.1、1.2…），标 `applied` |

## 建议下一步

1. 把 `Workbench` 每次 `emit` / 关卡 / 任务改写落到同一 SQLite 事务。
2. 录 E1–E10 replay。
3. 有密钥后跑 `make check-models` / `make test-live`。
4. Playwright 控制台演示。

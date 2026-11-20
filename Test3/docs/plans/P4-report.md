# P4 阶段报告（T01–T03）

本报告按卡追加。所有测试命令均带 `-o addopts=''`，迁移统一经 `upgrade_database` 执行，不使用 `create_all`。

## T01 · 会话状态机与 Leader 动态编组

- 时间：2026-11-20 11:21 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_discussion_steward.py tests/integration/test_discussion_session_api.py -v`
- 退出码：0
- 计数：14 passed（单元 7 / 集成 7）
- 回归：`tests/unit/test_discussion_rules.py tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 40 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0（既有 0005 表达式索引 SAWarning）

### 触及文件

- `app/discussion/models.py`（NEW）
- `app/discussion/session_store.py`（NEW）
- `app/leader/__init__.py`（NEW）
- `app/leader/steward.py`（NEW）
- `app/api/routes_discussion.py`（NEW）
- `alembic/versions/0009_discussion.py`（NEW）
- `tests/unit/test_discussion_steward.py`（NEW）
- `tests/integration/test_discussion_session_api.py`（NEW）
- `app/storage/models.py`（MODIFY：三张 discussion 表 ORM）
- `app/main.py`（MODIFY：挂载 discussion router，prefix=/api）
- `Test3/docs/plans/P4-report.md`（NEW）

### 实现要点

- `DiscussionSession` / `DiscussionRoundState` 等类型在 `app/discussion/models.py`；`DiscussionRoundState` 不含 score / score_delta / variance。
- `DiscussionSessionStore` 的 `status` 列与 `payload.status` 同步；`get_locked` 用 no-op `UPDATE` 取 SQLite 写锁。
- `DiscussionSteward.create_session` 动态查 `ProjectMembershipRow`：leader 必须 `is_leader==1`，participant 必须都是项目成员；参与者去重保序，空列表拒绝。
- `requirement_snapshot_hash = hash_artifact(requirement_snapshot)`；默认 `max_rounds=3`；初始 `draft` / `current_round=0`。
- `group` actor 必须是 leader；允许 `draft`/`grouping`；传入列表则重新校验并替换；并发 group 通过写锁串行，最终是某一次完整列表。
- 未修改 `app/discussion/engine.py`、`rules.py`、`__init__.py`，legacy `GET /api/runs/{run_id}/discussion` 零行为变化；未写 `discussion_msg`。
- 未更新 OpenAPI 快照/API.md（按 P4 约定留到后续统一）。

## T02 · 独立盲首轮

- 时间：2026-11-20 11:22 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_round1_blind.py tests/integration/test_discussion_session_api.py -v`
- 退出码：0
- 计数：21 passed（盲首轮单元 9 / 会话 HTTP 12，含 T01 回归用例）
- 回归：`tests/unit/test_discussion_rules.py tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 40 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0

### 触及文件

- `app/discussion/proposals.py`（NEW）
- `tests/unit/test_round1_blind.py`（NEW）
- `app/api/routes_discussion.py`（MODIFY：start round / proposals / list）
- `tests/integration/test_discussion_session_api.py`（MODIFY：T02 HTTP 场景）
- `Test3/docs/plans/P4-report.md`（MODIFY）

### 实现要点

- `start_round`：leader-only；grouping → round1_independent（current_round=1）；cross_review/round_n_revise → round_n_revise（current_round+1）；超过 `budget.max_rounds` 时先把 status 置 `budget_exhausted` 再抛 409。
- `submit_proposal`：仅 round1_independent / round_n_revise；author 必须是 participant；同一 (session, author, round) 重复返回 409 duplicate_proposal。
- 全部 participant 本轮交齐后自动把本轮 proposal 全部 `sealed=0`，并调用 `open_cross_review` 把 status 置 `cross_review`；最后一票的返回体 `sealed=false`（前面提交者为 true）。
- 密封期 `list_proposals` 对非作者返回 `body_md=None`、`sealed=true`；作者本人可见正文；解封后所有 participant 可见正文。测试同时断言密封期 JSON 不含他人正文。
- 并发两个不同作者交卷：两行都落库，最终 status=cross_review，无丢行。
- 契约说明：列出的模块函数没有 session 参数，实际实现增加 keyword-only `session` 注入（HTTP 与单测均显式传当前 AsyncSession），其余签名与行为不变。

### 密封形状（写死）

- 密封期、非作者：`{"proposal_id", "author_bot_id", "round", "sealed": true, "body_md": null}`。
- 密封期、作者本人：`"sealed": true` 但 `body_md` 为正文。
- 解封后所有 participant：`"sealed": false` 且 `body_md` 为正文。

## T03 · 交叉评审：禁止自评，结构分数不是真理

- 时间：2026-11-20 11:23 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_cross_review.py tests/unit/test_round1_blind.py -v`
- 退出码：0
- 计数：18 passed（交叉评审 9 / 盲首轮回归 9）
- 回归：`tests/unit/test_discussion_rules.py tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 40 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0
- P4 四文件合跑：**37 passed**，退出码 0

### 触及文件

- `app/discussion/cross_review.py`（NEW）
- `tests/unit/test_cross_review.py`（NEW）
- `app/api/routes_discussion.py`（MODIFY：POST reviews）
- `Test3/docs/plans/P4-report.md`（MODIFY）

### 实现要点

- `ReviewBallot` 在 `app/discussion/models.py` 校验：scores 非空、justification key 与 scores 完全一致、hard_gate_results 至少含 coverage / conflicts_closed_or_recorded / evidence_complete；非法体 HTTP 400 validation_error。
- `submit_review` 仅允许 `cross_review`；reviewer 必须是 participant；proposal 必须属于本 session；reviewer == proposal.author 返回 409 self_review_forbidden 且不落行；同一 reviewer/proposal 重复返回 409 duplicate_review。
- 会话状态在 `round1_independent` 且未 `open_cross_review` 时提交评审返回 409 invalid_status。
- 并发两个评审者评同一提案：两行都落库（写锁串行）。
- `score_spread` 只做统计（各 ballot 总分 max-min），`submit_review` 源码中不引用它；测试用 `inspect.getsource` 断言。
- `cross_review.open_cross_review` 复用 `proposals.open_cross_review`，不重复实现。
- 契约说明：列出的模块函数没有 session 参数，实际实现增加 keyword-only `session` 注入（HTTP 与单测显式传当前 AsyncSession），其余签名与行为不变。

### HTTP 错误映射

- `X-Bot-Id` 缺失/空白 → 400 validation_error。
- `reviewer_bot_id` 与 `X-Bot-Id` 不一致 → 403 forbidden。
- 会话不存在 → 404 session_not_found；提案不存在/跨会话 → 404 proposal_not_found。
- 非 participant → 403 not_participant；状态不对 → 409 invalid_status。
- 自评 → 409 self_review_forbidden；重复票 → 409 duplicate_review；成功 → 201 票。

## T04 · should_converge：硬门槛、异议、轮次与预算

- 时间：2026-11-20 11:27 CST
- 命令：`cd Test3/backend && .venv/bin/python -m pytest -o addopts='' tests/unit/test_should_converge.py tests/integration/test_discussion_session_api.py -v`
- 退出码：0
- 计数：26 passed（should_converge 8 / 会话 HTTP 18，含 T01–T03 回归）
- 回归：`tests/unit/test_discussion_rules.py tests/unit/test_tools_llm_agents.py tests/unit/test_p1_f08_tool_authorization.py` → 40 passed，退出码 0
- 迁移衔接：`tests/integration/test_alembic.py tests/integration/test_p1_rev05_alembic_handoff.py tests/integration/test_events_and_db.py` → 6 passed，退出码 0

### 触及文件

- `app/discussion/converge.py`（NEW）
- `tests/unit/test_should_converge.py`（NEW）
- `app/api/routes_discussion.py`（MODIFY：converge 路由；`requirement_snapshot` 改 `str | dict`）
- `tests/integration/test_discussion_session_api.py`（MODIFY：converge / 字符串快照）
- `Test3/docs/plans/P4-report.md`（MODIFY）

### should_converge 决策表（按序写死）

| 顺序 | 条件 | 返回 action |
|---|---|---|
| 1 | `max_tokens` 非空且 `tokens_used >= max_tokens`，或 `max_wallclock_seconds` 非空且 `elapsed_seconds >= max_wallclock_seconds` | `budget_exhausted` |
| 2 | 全部硬门槛通过；或未通过数 `3 - latest_pass_count` 已被 `dissent_items` 覆盖（去重后数量足够） | `submit_human` |
| 3 | `current_round >= budget.max_rounds` | `submit_human`（带未决项，不再 revise） |
| 4 | 最近两轮 `hard_gate_pass_counts[-1] <= [-2]` | `no_improvement` |
| 5 | 其他 | `revise` |

- `submit_human` 的 reason 必须保留 dissent 原文；测试覆盖 `风险X`。
- `budget_exhausted` 优先于一切；`current_round >= max_rounds` 优先于 no_improvement。
- `DiscussionRoundState` 与 `should_converge` 均不含 score / delta / variance；`converge.py` 源码文本不含 `score_delta` / `score_spread` / `variance`（测试用 inspect/源码检查）。

### HTTP converge

- `POST /api/discussion-sessions/{sid}/converge`；X-Bot-Id 必填；actor 必须是 leader 或 participant，否则 403 forbidden。
- 可选 body（扩展登记）：`{tokens_used?: int, elapsed_seconds?: int, dissent_items?: list[str]}`；无 body 为 0/0/[]；非法类型 400 validation_error。
- 从 DB 组装 `DiscussionRoundState`：
  - 每轮取 proposals 与 reviews；仅有当该轮每个 proposal 至少一条 review 时，才统计三个硬门槛“所有 review 均 true”的条数，否则该轮记 0；绝不使用分数。
  - dissent = 所有 review ballot 的 dissent_items（去重保序）+ body 额外 dissent。
  - `all_required_hard_gates_pass = 当前轮通过数 == 3`。
- 写锁后重新检查 status 必须 `cross_review`，否则 409 invalid_status。
- 状态映射：budget_exhausted → `budget_exhausted`；submit_human / no_improvement → `converged_pending_human`；revise → `round_n_revise`。
- 返回 `{action, reason, session, dissent_items}`；`dissent_items` 原样返回（扩展登记）。
- 并发两个 converge：写锁串行，第二个看到 status 已非 cross_review → 409；最终状态不分叉。

### requirement_snapshot 修正

- `CreateSessionBody.requirement_snapshot` 由 `dict` 改为 `str | dict`，service 注解保持 `Any`；同时接受字符串与对象，契约要求字符串。
- 新增 HTTP 测试：字符串 `"plain requirement"` 创建成功，`requirement_snapshot_hash == hash_artifact("plain requirement")`；既有 dict 测试保持。
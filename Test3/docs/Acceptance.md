# Test3 对照 ImplementationPlan 第 23 章

「通过」只表示本轮有对应自动化证据。「未做」不是隐晦的通过。

| # | 标准 | 本轮 |
|---|---|---|
| 1 | P00–P17 验收项全过，`make lint` / `make test` / `make e2e` 成功 | `ruff check` 与 `pytest -m "not live"` 见 Progress。`make lint` 的 format/mypy 被 `\|\| true` 忽略。P07–P17 仍有缺口，见 Handoff |
| 2 | replay 走通 E1–E10；真实联调至少一次且有记录 | 未做。无 replay JSON，无 `docs/RealModelTest-*` |
| 3a | 讨论规则以第 11 章为金标准 | 通过。`test_select_speaker_matches_study_room_gold_standard`、`test_finalize_matches_table_a`、`test_can_finish_before_14_and_not_before_13` |
| 3b | 评审通过与分流 | 通过（单元）。另有 e2e：`test_review_reopen_then_pass` |
| 3c | 任务图检查 | 通过（单元）。`test_task_graph_stub_before_impl` |
| 3d | 调度、完成条件、失败分类 | 纯函数单测仍在。编排层现有 `test_denied_acceptance_cannot_be_done`、`test_repair_round_includes_prev_output`。没有完整调度压力测试 |
| 3e | 控制可用状态 | 后端 `test_control_table` / `test_control_actions_require_reason_by_state`；前端 `control.test.ts` 含 resume |
| 3f | 变更分级与影响 | 单元 + `test_decide_cr_marks_applied_and_bumps_1_1` |
| 3g | 反馈分流 | e2e 导入走 Agent；`test_listening_without_scripted_does_not_hardcode_study_room`。无 40 条 E8 全案 |
| 4 | 信息边界、写集、命令白名单、密钥不进日志 | 通过。`test_info_boundary`、`python -c` 被拒、`sk-` 脱敏 |
| 5 | 任务状态只有 `transition()` 一处修改 | **未满足。** 内存执行/控制直接改 `task["state"]` |
| 6 | 控制台可演示任务图、证据、暂停、重试、变更、反馈 | 页面在（讨论页含规则列，验收未通过需理由）。无浏览器/录屏证据 |
| 7 | 文档与实现一致，偏差已记录 | README / API / Progress / Handoff / Demo 按本轮代码写 |
| 8 | 没有空函数冒充完成 | 执行/验收/监听不再用假输出放行。`patch` 仍拒绝，见 Handoff |

## 本轮绑定命令

```text
cd /agent/repos/HexaGraph/Test3/backend
uv run ruff check app tests
uv run pytest -q -m "not live"
cd ../frontend && npm test
```

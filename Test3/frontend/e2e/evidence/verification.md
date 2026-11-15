# #18 验证记录（2026-11-13，Asia/Shanghai）

基线 `teamwork-001`: `efdd6eb76729d771be7498411f39b25885a7310e`。
环境：Windows、Node 22.15.0、Playwright 1.65 Chromium；集成后端独立 Python 3.14.3 环境。

| 命令 | 实测 |
|---|---|
| `npm test` | 原有 controlEnabled：1 passed |
| `npm run test:e2e:types` | 通过 |
| `npm run build` | 通过；已有 bundle >500 kB 警告 |
| `npm run test:e2e` | 9 passed（复核优化后） |
| `npm run test:e2e -- --repeat-each=2` | 18 passed，零重试，未观察到 flake |
| `npm run test:e2e:integration` | 1 passed，真实 HTTP scripted 后端 |

`scripted-workstation.png`：真实 UI 创建、批准第一个关卡进入阶段 1，并完成暂停/恢复后的截图。`scripted-terminated.png`：总览页终止确认后状态为 terminated、按钮禁用。均为实际浏览器截图，数据仅来自专用离线运行。

交付复核后，原单测、类型检查、构建、9 例 mock、18 次重复运行及真实集成均重新执行通过。两类报告独立保存为 `mock/` 和 `integration/`；集成结束后 mock 的 18 份 trace 仍存在。逐项交付判断及待完成项见 [delivery-checklist.md](delivery-checklist.md)。

## 既有后端基线的失败（本 PR 未改后端）

命令：在已安装后端与 pytest/pytest-asyncio 的独立环境中，`cd Test3/backend && python -m pytest -q -m "not live"`。退出码 1，共 10 项失败；未删减或跳过现有用例。

- `tests/e2e/test_contract_must.py::test_concurrent_merge_rollback_keeps_other_task`
- `tests/e2e/test_contract_must.py::test_conflict_roundtrip_reruns_origin`
- `tests/e2e/test_contract_must.py::test_idea_to_acceptance_exports_release`
- `tests/e2e/test_contract_must.py::test_schedule_loop_completes_ready_task`
- `tests/e2e/test_contract_must.py::test_cr_plan_card_used_on_rerun`
- `tests/e2e/test_leftover_gaps.py::test_merge_conflict_spawns_resolve_task`
- `tests/e2e/test_leftover_gaps.py::test_accept_pass_exports_release_pack`
- `tests/e2e/test_leftover_gaps.py::test_takeover_locks_and_submit_merges`
- `tests/e2e/test_must_fixes.py::test_repair_round_includes_prev_output`
- `tests/unit/test_tools_llm_agents.py::test_path_safety`

前 9 项观察到 failed/needs_human 等状态与预期 done 不符或缺合并/交付结果，根因待负责人定位，不归因于新增前端测试。最后一项明确为 Windows 创建符号链接缺少权限（WinError 1314）。最小复现可直接 `python -m pytest -q tests/unit/test_tools_llm_agents.py::test_path_safety`；其余按上述 node id 单独运行。

未声称整个后端基线通过。未验证真实模型、执行阶段完整交付、恢复或 SSE 时序。中央 Progress/Handoff/Acceptance 文档交由组长整合。

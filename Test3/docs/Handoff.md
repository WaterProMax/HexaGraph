# Test3 交接

## 已知限制

1. **HTTP 运行态在内存。** `Workbench` 持有 projects/runs。SQLAlchemy 模型、Alembic `0001_init`、`EventBus` 有测试，但 `create_app` 不把关卡/任务写入 SQLite。重启丢失。
2. **任务状态有两处写入。** 计划要求只经 `orchestrator.transition.transition()`。内存路径用 `next_task_state` / 直接赋值；`transition()` 只服务 `TaskRow`。
3. **P07–P11 全链路薄。** `run_design` / `run_plan` / `execute_task` / `accept` 是真函数，不是打印假结果；缺 scripted/replay 队列，因此没有想法→验收的一条自动化长跑。设计评审未接两位架构评审。
4. **执行。** `execute_task` 会建 git worktree、按写集落文件、commit、对验收命令走 `run_command`（白名单，拒 `;|&\`$<>`）。scripted coder 若不写真实测试，依赖仓库初始 `tests/test_smoke.py`。修复轮、失败签名、重排关卡已接；杀进程恢复只在 `recover_tasks` 辅助函数，未挂到启动。
5. **令牌配额。** `limits.yaml` 为并发 6 / 修复 6 / 每点 150 万 / P1 0.9。`Gateway` 记 `tokens_in/out`；`Workbench._charge` 累加到 `run.tokens_used`。scripted 提供者为 0，预算页看不到消耗。没有按任务点数截断生成。
6. **监听聚类。** 导入后用文本字符和做 2 维向量，不是 `text-embedding-v4`。红线靠「学号」「隐私」扫描整簇。
7. **变更。** `classify_cr` 与影响追溯有单测；没有 Design 21.3「扫码进入教室页」版本升到 1.1 的端到端。
8. **前端。** 页面能打 API，没有 Playwright，没有录屏。控制按钮单测在 `frontend/src/control.test.ts`。
9. **E1–E10 replay。** `examples/study-room/replay/` 只有 README。`ReplayProvider` 代码在，无编号 JSON。
10. **真实百炼。** 未跑 `make check-models` / `make test-live` / 自习室真模型长跑。不要把 scripted M1 说成联调通过。
11. **SSE。** 15 秒轮询内存事件，不是跨进程 EventBus。
12. **`POST /config/models/test`。** 固定返回提示，不是探测。

## 与设计的偏差

| 设计 | 实现 |
|---|---|
| 阶段/任务/事件持久化 | 内存为主，DB 测试旁路 |
| 任务状态只经 `transition()` | 内存路径直接改 |
| 设计两位背靠背评审 | 未接线 |
| replay E1–E10 | 未录 |
| 反馈 HMAC 必填 | API 缺密钥 400；单测直接传 key |
| embedding 聚类 | 字符和向量 |
| 默认 LLM 为 dashscope | 进程默认 `scripted`，避免空密钥外呼 |

## 建议下一步

1. 把 `Workbench` 每次 `emit` / 关卡 / 任务改写落到同一 SQLite 事务，启动时按事件回放。
2. 内存任务改走 `transition()`，或抽一个不依赖 Session 的同一函数给两边用。
3. 录 E1–E10 replay，补想法→验收 e2e。
4. 有密钥后跑 `make check-models`，把槽位结果写入 `docs/RealModelTest-<日期>.md`。
5. 设计评审、探索任务、变更 1.1、Playwright 控制台演示。

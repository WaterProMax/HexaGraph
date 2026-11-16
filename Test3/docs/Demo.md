# 10 分钟演示稿（scripted）

对象：本机 `scripted`。这不是百炼联调，也不是 E1–E10 replay。离线成功 ≠ 真实模型通过；页面会持续显示「预置测试输出／模拟执行」。

## A. 设计规格离线主演示（推荐）

主样例：`examples/design-specs/self-study-room.md`，与预置座位查询任务（T-01/T-02）一致。`club-signup.md` 只用于证明上传/原文保存，不能声称座位任务是从社团文档生成的。

scripted 不会按任意文档理解业务；队列是预置的。

调度模式以后端 `GET /api/health` 的 `schedule_mode` 为准，不要因为 `preset` 就假设没有自动调度：

- 本演示服务器：`manual`，页面写「请点击调度执行」，不会出现「每 5 秒自动调度」。
- `make dev-backend`：`auto`，scripted 下仍每 5 秒自动调度。

### 复位（没有生产环境公开复位 API）

1. 停掉离线服务器进程。
2. 用新的隔离数据目录再启动（默认即新建临时目录；不要复用上次的 `OFFLINE_SCRIPTED_DATA_DIR`）。
3. 测试与演示必须分开启动，不要共用同一个进程或数据目录。
4. 不要对生产/共享服务调用复位接口——仓库没有公开 reset API。

### 队列限制（每次启动）

一次成功整理（座位任务）+ 一次缺项整理，然后队列耗尽。完整重跑必须先复位。顺序：导入 `self-study-room.md` → DESIGN/PLAN 确认 → 点击调度执行 T-01/T-02 → 再导入缺项文本看到 `needs_input`。中途再导入会打乱队列。

1. 终端一（`Test3/backend`）：

   ```bash
   PATH="$PWD/.venv/bin:$PATH" \
     .venv/bin/python tests/e2e/design_spec_http_server.py --host 127.0.0.1 --port 8765
   ```

   启动日志有 `OFFLINE_SCRIPTED_DATA_DIR=...` 与 `OFFLINE_SCHEDULE_MODE=manual`。

2. 终端二：`cd Test3 && make dev-frontend`（或 `cd frontend && npm run dev -- --host 127.0.0.1 --port 5173`）。
3. 打开 http://127.0.0.1:5173/workstation ，选「从设计规格开始」，读取或粘贴 `self-study-room.md`。
4. 整理后应持续看到「预置测试输出（scripted）」和「模拟执行（预置工具调用）」。确认 DESIGN、确认 PLAN，就绪任务提示「请点击调度执行」，点「调度执行」。
5. 刷新同一运行，标签、任务状态仍在。第二次完整演示必须先复位。

## B. 想法入口 M1（`make dev-backend`）

对象：`scripted` + `TEST3_SCRIPTED_FIXTURE=study-room`。此路径会启动 5 秒自动调度。

1. `cd Test3 && make install && make dev-backend`，另开终端 `make dev-frontend`。
2. 打开 http://127.0.0.1:5173 ，建项目，想法填自习室那句。
3. 总览应出现「初步做法确认」。批准。
4. 讨论页应有 14 条发言与 7 条争议：I-01/02/05/06/07 采纳，I-03/04 待定（与 Design 11.4 表 A 一致）。
5. 批准争议清单，再批准评审，进入 SPEC 关卡。文档页应看到 F1–F3，开口含 I-03/I-04，功能标题不含门禁。
6. 再往后（设计/任务图/执行/变更/反馈）scripted 队列已用尽：要么停在这里说明 M1 边界，要么切 `dashscope` 继续（本轮未验证）。
7. 反馈页：先设 `FEEDBACK_HASH_KEY`，再导入 `examples/study-room/feedback/batch1.json`。未设密钥应 400。

未准备：replay 演示、真模型录屏、执行中暂停/重试的自动剧本。

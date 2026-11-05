# 10 分钟演示稿（scripted）

对象：本机 `scripted` + `TEST3_SCRIPTED_FIXTURE=study-room`。这不是百炼联调，也不是 E1–E10 replay。

1. `cd Test3 && make install && make dev-backend`，另开终端 `make dev-frontend`。
2. 打开 http://127.0.0.1:5173 ，建项目，想法填自习室那句。
3. 总览应出现「初步做法确认」。批准。
4. 讨论页应有 14 条发言与 7 条争议：I-01/02/05/06/07 采纳，I-03/04 待定（与 Design 11.4 表 A 一致）。
5. 批准争议清单，再批准评审，进入 SPEC 关卡。文档页应看到 F1–F3，开口含 I-03/I-04，功能标题不含门禁。
6. 再往后（设计/任务图/执行/变更/反馈）scripted 队列已用尽：要么停在这里说明 M1 边界，要么切 `dashscope` 继续（本轮未验证）。
7. 反馈页：先设 `FEEDBACK_HASH_KEY`，再导入 `examples/study-room/feedback/batch1.json`。未设密钥应 400。

未准备：replay 演示、真模型录屏、执行中暂停/重试的自动剧本。

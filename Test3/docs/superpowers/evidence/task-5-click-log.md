# Task 5 逐按钮点击记录（mock 浏览器）

> mock `/api`。可证明页面点击反馈，不能证明真实后端或真实模型。

| 操作 | 请求结果 | 即时反馈 | 最终状态 | 截图 |
| --- | --- | --- | --- | --- |
| 上传 Markdown | 无 HTTP 导入（本地读取）；POST 计数仍为 0 | 显示文件名 self-study-room.md，原文与字节计数更新 | 未创建运行，停留在 /workstation | `design-spec-accept-upload.png` |
| 空文、超限提交 | 未发出 design-runs | 「设计规格为空」与「超过 100 KiB 上限」错误条 | 不创建运行 | `design-spec-accept-empty-oversize.png` |
| 点击整理及再次点击 | POST /design-runs → 200 importing，仅 1 次 | 立即出现「正在整理」等待文案，按钮禁用 | 同一 run-importing | `design-spec-accept-organize-wait.png` |
| 等待、刷新、超时 | 刷新后 GET artifacts 仍是同一 run；随后 status=failed / error_category=timeout | 超时标题与「保留原文，再次提交」下一步 | 同一运行，原文仍在，无 DESIGN 关卡 | `design-spec-accept-refresh-timeout.png` |
| 驳回 DESIGN | POST /gates/.../resolve decision=reject → 200 rejected | toast「已驳回」 | 运行已停止，原文仍在，可再点整理 | `design-spec-accept-reject-design.png` |
| 批准 DESIGN | POST /gates/.../resolve decision=approve → PLAN 关卡 | toast「已批准并推进」 | 出现 PLAN 确认，尚未调度 | `design-spec-accept-approve-design.png` |
| 批准 PLAN | POST /gates/.../resolve → 任务物化 | 阶段 7，T-01 ready / T-02 pending | 任务和依赖可见，尚未执行 | `design-spec-accept-approve-plan.png` |
| 暂停、调度、恢复 | pause → 调度按钮禁用；resume → schedule 先 400 后 200 started=[T-01] | 暂停后调度禁用；成功 toast「已调度执行任务」 | 暂停不派发；恢复后 T-01 done | `design-spec-accept-pause-schedule-resume.png` |
| 查看节点、任务计划、产物、活动 | 只读 GET run/artifacts/tasks（mock 200） | 各页签有当前运行内容，空活动显示占位「暂无事件」 | 与 run-happy 一致 | `design-spec-accept-tabs.png` |
| 操作失败 | POST /schedule 第一次 400 offline schedule failure | 「调度失败」错误提示，未显示成功 | 任务未因失败请求被标成成功；随后成功调度才更新 | `design-spec-accept-schedule-failure.png` |

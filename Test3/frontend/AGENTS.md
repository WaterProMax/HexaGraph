# 前端视觉维护约定

继承 `../AGENTS.md` 的业务和技术约束。

修改应用导航或 Workstation 任一区域 UI 前，先阅读：

- `../docs/design/UI-Design-System.md`：Ice Glass v1.1 设计规范。
- `../docs/design/UI-Redesign-Log.md`：设计过程、验证范围与已知限制。

优先复用 `src/workstation-glass.css` 中 `.shell` 的共享 token、glass-panel、phase-items 和工作台控件。样式保持 `.sidebar` / `.ws` 范围；主文字、次文字、辅助文字使用深蓝灰角色，不恢复低对比浅灰。保持标题 / 技术编号 / 正文 / 副文的层级，避免多重细线框。新控件需覆盖键盘焦点、禁用、loading、空状态和长内容。

仅修改视觉的任务不得顺手改 API、mutation、审批条件、阶段计算或 React Flow 布局。推广到其它区域时明确范围，不直接覆盖全局 Ant Design token。

设计规则或视觉基线变化时，同步更新规范、过程记录与截图。完成前执行类型检查、Vitest、生产构建，并区分模拟浏览器回归与真实后端验证，不混淆测试结论。

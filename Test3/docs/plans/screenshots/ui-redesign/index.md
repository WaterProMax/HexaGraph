# UI 改版截图索引（UI-R01～UI-R05）

全部截图来自 `Test3/frontend/e2e/openmausbot-ui.pw.ts`：Playwright Chromium、1440×1000、`page.route` HTTP mock；真实 React 页面与真实 `api` client，零付费模型调用，不读写用户 `Test3/data`。

命令：

```bash
cd Test3/frontend
npx playwright test e2e/openmausbot-ui.pw.ts
```

| 文件 | 卡片 | 内容 |
|---|---|---|
| `ui-r01-sidebar-expanded.png` | R01 | 展开侧栏：浏览导航 + 「助手」联系人列表（头像 / 名称 / 角色 / 状态）+ 新建 Bot + 最近运行 |
| `ui-r01-sidebar-collapsed.png` | R01 | 76px 折叠轨：导航图标、圆形「+」、竖排圆形头像（title 为「名称 · 角色」），最近运行隐藏 |
| `ui-r02-bots-list.png` | R02 | `/bots` 列表：头像、名称、角色·模型·槽位、状态胶囊 |
| `ui-r02-bot-new.png` | R02 | `/bots/new`：角色预设（Leader / 产品经理 / 后端 / 测试运维 / 通用）+ 表单 |
| `ui-r02-bot-workspace.png` | R02 | `/bots/:id`：大头像、更换头像选择器（Emoji + 色板）、三个 Tab、编辑表单 |
| `ui-r03-projects.png` | R03 | `/projects` 卡片上的成员头像与 Leader |
| `ui-r03-team-strip.png` | R03 | 项目工作台团队条、当前操作身份、管理成员入口、任务树与四 Tab |
| `ui-r03-members-dialog.png` | R03 | 管理成员弹窗：成员列表、移出、设为 Leader、添加成员 |
| `ui-r04-review-panel.png` | R04 | 执行监控：项目共享记忆、互评卡片（头像 + 硬门槛徽章 + 异议）、缺陷卡片 |
| `ui-r04-defect-locate.png` | R04 | 点击缺陷后定位到 T-02，任务树出现短时高亮 |
| `ui-r05-settings.png` | R05 | Settings 槽位卡片，保留「测试连通」 |

说明：P6 截图（`screenshots/p6-t0*.png`）未被覆盖；本目录为独立新增。
# P6 截图索引

全部截图来自 `e2e/p6-walkthrough.pw.ts`：Playwright + `page.route` HTTP mock，真实 React 页面与真实 `api` client，零付费模型调用。命令：

```bash
cd Test3/frontend
./node_modules/.bin/playwright test e2e/p6-walkthrough.pw.ts
```

| 文件 | UI-A1 步骤 | 内容 |
|---|---|---|
| `p6-t01-sidebar.png` | 1、2 | AppShell 侧栏：工作台 / Bot / 项目 / 模型槽位，最近运行；无 Model/Skill/Market/Cron |
| `p6-t02-empty.png` | 3a | `/bots` 空态「还没有 Bot」 |
| `p6-t02-create.png` | 3b | 新建 Bot：显示名、模型槽位、Skill 版本与绑定 |
| `p6-t02-ready.png` | 3b | 创建成功后列表出现 Leader A 与其 Skill pin |
| `p6-t03-workstation.png` | 4、5、6 | 项目工作台：左任务树 T-01/T-02 与进度、四个 Tab、splitter |
| `p6-t04-banner.png` | 7 | `baseline_stale` 提示：基线已变化，请重新审批 |
| `p6-t04-defect-locate.png` | 8 | 点击缺陷后详情定位到 T-02 |
| `p6-t05-forbidden.png` | 8 | 无权限 403 的明确错误态（`bots-forbidden`） |

说明：走查里的授权状态为 mock 的 `stale` grant；工作台据此展示 `baseline_stale` 分类，与后端 `grant_stale_reason` 的语义一致。前端不提供任何开闸控件。
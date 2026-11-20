# P6 阶段报告（T01–T05，前端工作台）

本报告覆盖 P6 前端工作台（AppShell、Bot、项目工作台、Grant/互评/缺陷、出口走查）。前端工程以仓库实态为准：npm + `package-lock.json`，`npm ci` 安装，Vitest（jsdom）测试，Vite 构建。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | 待 T05 汇总 | `feat(test3): P6-T01 add AppShell sidebar with bots projects settings` |
| T02 | 待 T05 汇总 | `feat(test3): P6-T02 add bot list and form with model skill pins` |
| T03 | 待 T05 汇总 | `feat(test3): P6-T03 add project workstation tree and tabs` |
| T04 | 待 T05 汇总 | `feat(test3): P6-T04 add grant banner discussion defects` |
| T05 | 本报告所在提交 | `docs(test3): P6-T05 exit report and walkthrough screenshots` |

## 前端工程命令实态

- 依赖：`cd Test3/frontend && npm ci` → 445 packages，退出码 0。
- 基线测试：`npm test` → 19 files / 168 tests passed，退出码 0。
- 类型检查：`npx tsc --noEmit`（`tsconfig.json` 为 strict + noEmit）。
- 构建：`npm run build`（`tsc -b && vite build`）。

## T01 · AppShell 侧栏：Bot、Project、Settings

- 命令：`cd Test3/frontend && npm test -- src/components/AppShell.test.tsx src/pages/Settings.test.tsx src/App.retired.test.tsx src/App.routes.test.tsx`
- 退出码：0
- 计数：4 files / 14 tests passed
- 实现：`components/AppShell.tsx` 从原 `App.tsx` 内联 Sidebar 抽取，保留折叠（`COMPACT_VIEWPORT=1100`）、最近运行、品牌区；导出 `DEFAULT_NAV_ITEMS`、`REQUIRED_NAV_KEYS`、`LoadState`、`AppShellProps`。`App.tsx` 导出 `APP_ROUTE_PATHS`，新增 `/bots`、`/bots/new`、`/bots/:id`、`/projects/:projectId`；`/settings` 继续渲染既有 `pages/Settings.tsx`。
- 保留：`/workstation/static-classroom` → `RetiredFeature feature="static-classroom"`、`/deepseek/:id?` → `RetiredFeature feature="deepseek"` 原样保留；无顶级 `/models`、`/skills`。
- Settings 回归：成功探测仍 `POST /api/config/models/test` 并展示结果；失败探测页面不崩溃、请求路径不变。
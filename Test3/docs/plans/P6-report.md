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
## T02 · Bot 列表与表单：Model / Skill pin、四种加载态

- 命令：`cd Test3/frontend && npm test -- src/pages/bots/BotListPage.test.tsx src/pages/bots/BotForm.test.tsx src/api/client.test.ts`
- 退出码：0
- 计数：3 files / 13 tests passed（列表 6 / 表单 4 / client 3）；补 2 条 P2–P5 错误体用例后 `src/api/client.test.ts` 为 5 passed，`npx tsc --noEmit` 通过。
- 类型：新建 `src/api/types.ts`，字段与 C.4 后端同名（BotInstance / BotCreate / BotPatch / BotSkillBinding / SkillDefinition / ExecutionGrant / ReviewBallot / DecisionPackage / DiscussionSession / ModuleAcceptance / DefectRecord / ErrorBody / RunTask）。`secret_ref` 仅环境变量名。
- client：`parseApiError` 现在同时识别 `{"error_category","detail"}` 与旧 `{"detail":{category,summary,run_id}}`；新增 bots/skills/成员/grants/schedule/讨论/验收/缺陷方法，讨论与验收请求带 `X-Bot-Id`。
- 页面：`pages/bots/BotListPage.tsx` + `BotForm.tsx`。列表四态 testid `bots-loading` / `bots-empty`（含「还没有 Bot」）/ `bots-error` / `bots-forbidden`；创建与编辑表单内嵌模型槽位与 Skill 版本绑定；创建 `POST /api/bots` 的 body 不含 `bot_id`，编辑走 `PATCH /api/bots/{id}`，归档走 `POST /api/bots/{id}/archive` 且需二次确认。
- 数据：只调用真实端点 `GET /api/bots`、`GET /api/skills`、`GET /api/config/models`、`GET /api/bots/{id}`。

## T03 · 项目工作台：左任务树 + 四 Tab + splitter + dirtyRef

- 命令：`cd Test3/frontend && npm test -- src/pages/project/ProjectWorkstationPage.test.tsx src/components/WorkstationSplitter.test.tsx`
- 退出码：0
- 计数：2 files / 14 tests passed（工作台 9 / 既有 splitter 5）；随后全量 `npm test` 为 24 files / 196 tests passed，`npx tsc --noEmit` 通过。
- 页面：`pages/project/ProjectWorkstationPage.tsx`。展示组件 `ProjectWorkstation` 接收 `projectId / loadState / tasks / dirtyRef / initialTab`；容器按 `GET /api/runs` → 过滤 `project_id` → `GET /api/runs/{run_id}/tasks` 取真实任务，按契约映射：`done=100`，`running|verifying=40`，其余 0，状态原样使用后端枚举（无 `succeeded`）。
- 四 Tab：`tab-details / tab-monitor / tab-activity / tab-graph` 与 `panel-*`；点击左侧任务切回详情并显示该 code。
- 复用：`WorkstationSplitter` 与 `useWorkstationLayout`，断言 `data-testid="ws-splitter"` 与 `role=separator` 仍在；备注编辑把共享 `dirtyRef.current` 置 true（与 `DesignSpecInput` 同一模式）。
- 四态：`ws-loading / ws-empty / ws-error / ws-forbidden`；空任务列表显示 `ws-empty` 且不崩溃。
- 项目入口：`pages/Projects.tsx` 的项目卡片新增「打开工作台」链接到 `/projects/:projectId`，原「创建并开始」跳到 `/workstation/${run.id}` 的行为保持不变。

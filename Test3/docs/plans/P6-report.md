# P6 阶段报告（T01–T05，前端工作台）

本报告覆盖 P6 前端工作台（AppShell、Bot、项目工作台、Grant/互评/缺陷、出口走查）。前端工程以仓库实态为准：npm + `package-lock.json`，`npm ci` 安装，Vitest（jsdom）测试，Vite 构建。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| T01 | `6930003b8ec1fe6dfcc1a28f65d51bd7106c8d02` | `feat(test3): P6-T01 add AppShell sidebar with bots projects settings` |
| T02 | `eb5bdc60d9910c4add65c13a8f90f87b7346af82` | `feat(test3): P6-T02 add bot list and form with model skill pins` |
| T03 | `ae9f1f18c5feccbf1aab3a9e9a55c8e6910ba6a9` | `feat(test3): P6-T03 add project workstation tree and tabs` |
| T04 | `15b32da8b952a2695c555acb7d96d039f26d8359` | `feat(test3): P6-T04 add grant banner discussion defects` |
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

## T04 · Grant 提示、讨论互评、缺陷回到任务 + 后端只读 GET

- 前端命令：`cd Test3/frontend && npm test -- src/pages/project/GrantStatusBanner.test.tsx src/pages/project/DiscussionReviewPanel.test.tsx src/pages/project/DefectList.test.tsx src/pages/project/ProjectWorkstationPage.test.tsx` → 4 files / 22 passed，退出码 0；全量 `npm test` 27 files / 209 passed，`npx tsc --noEmit` 通过。
- 后端命令：`cd Test3/backend && TEST3_ISOLATION_IMAGE=sha256:af6493938f5d… .venv/bin/python -m pytest -o addopts='' -q tests/integration/test_p6_readonly_get.py tests/integration/test_api_contract.py tests/integration/test_module_acceptance_and_defects.py tests/integration/test_discussion_session_api.py tests/unit/test_p1_rev01_execution_boundary.py tests/integration/test_schedule_grant_http.py` → 88 passed，退出码 0。
- 组件：`GrantStatusBanner.tsx`（`baseline_stale` → 含「基线」「重新审批」，不出现「请逐行确认」；`grant_required` → 含「执行授权」；`stale/revoked/consumed` 回退；无信号不渲染）、`DiscussionReviewPanel.tsx`（逐票硬门槛、逐项依据、异议；文案只把结论归于硬门槛/异议/轮次，出现「分数仅作记录」，不出现「分差…自动通过」）、`DefectList.tsx`（点击缺陷回调 `onLocateTask(task_code)`；不自动 resolved）。
- 组装：`ProjectWorkstationPage` 新增可选 `grantErrorCategory / grantStatus / ballots / dissentItems / defects`；缺陷点击把左侧选中任务切到该 `task_code` 并回到详情 Tab。容器在 `actorBotId` 存在时读取缺陷与讨论票；只读面板失败不影响工作台主体。
- 只读 GET（本卡唯一后端改动，均为新增）：
  - `GET /api/runs/{run_id}/defects`
  - `GET /api/runs/{run_id}/module-acceptances`
  - `GET /api/projects/{project_id}/discussion-sessions`
  - `GET /api/discussion-sessions/{session_id}`
  - `GET /api/discussion-sessions/{session_id}/reviews`
- 头与错误：全部要求 `X-Bot-Id`（缺头 400 validation_error）；讨论三个 GET 仅 leader / participant，非参与者 403 not_participant；run/project/session 不存在分别 404 run_not_found / project_not_found / session_not_found；错误体沿用 `_json_error`。
- 盲轮安全：`reviews` 只返回投票 payload，不含任何提案正文，盲首轮不会经此泄漏他人草案（测试断言无 `body_md`）。
- OpenAPI：`UPDATE_OPENAPI_SNAPSHOT=1 … tests/integration/test_api_contract.py` → 28 passed；路径 65 → 70（+5，删除 0），既有 65 条路径（含 `GET /api/runs/{run_id}/discussion`、`POST /api/runs/{run_id}/accept`）全部保留。`Test3/docs/API.md` 已新增 P6 只读查询章节（标题前空行）。未新增写接口、未新增 Alembic（head 仍 0010）。
- 契约：规格批准按钮未新增；前端不提供开闸控件，`execution_safety_ready` 只展示。

## T05 · 出口：测试、构建、走查与截图

### A. 前端出口命令

| 命令 | 退出码 | 结果 |
|---|---|---|
| `cd Test3/frontend && npx tsc --noEmit` | 0 | strict + noEmit 通过 |
| `npm test` | 0 | 27 test files / 209 tests passed |
| `npm run build` | 0 | `tsc -b && vite build`，3304 modules，`dist/index.html + assets` 生成（chunk > 500 kB 为既有体积告警，非失败） |
| `npm test -- src/pages/project/ProjectWorkstationPage.test.tsx` | 0 | 12 passed（四 Tab testid、四态、缺陷定位、备注脏标记） |
| `npm run test:e2e:types` | 0 | e2e TypeScript 通过 |
| `./node_modules/.bin/playwright test e2e/p6-walkthrough.pw.ts` | 0 | 2 passed（UI-A1 走查 + 错误/无权限态） |

- 既有 `App.retired.test.tsx`、`App.routes.test.tsx`、`Workstation.test.tsx`、`WorkstationSplitter.test.tsx`、`api/client.test.ts` 均在全量 `npm test` 中通过。
- 走查使用 Playwright `page.route` HTTP mock，真实 React 页面与真实 api client；零付费模型调用。为跑 Playwright 1.65 所需的 chromium 1254，执行了 `./node_modules/.bin/playwright install chromium`（浏览器下载，非 Docker）。

### B. 后端（本阶段改了后端只读 GET 与 OpenAPI）

隔离镜像：`TEST3_ISOLATION_IMAGE=sha256:af6493938f5df1f06ca97f63bac9e0eebd9119185183dbc25cc4cc7143ef72cd`（不可变 Id，未 `docker tag`、未 pull/build）。

| 命令 | 退出码 | 计数 |
|---|---|---|
| `.venv/bin/python -m pytest -o addopts='' -v tests/integration/test_api_contract.py` | 0 | 28 passed |
| `.venv/bin/python -m pytest -o addopts='' -m 'not live' -q tests/unit/test_p1_rev01_execution_boundary.py tests/integration/test_schedule_grant_http.py tests/integration/test_module_acceptance_and_defects.py tests/integration/test_discussion_session_api.py` | 0 | 56 passed |
| `.venv/bin/python -m pytest -o addopts='' -m 'not live' -q` | 0 | 609 passed, 1 skipped, 2 deselected, 0 failed |

- skip 仍为 `test_worker_fails_closed_without_backend`，2 deselected 为 `live`。
- 新增后端测试 `tests/integration/test_p6_readonly_get.py`：4 passed（defects/acceptances 列表、缺头 400、404、讨论会话与评审的 200/403/404）。

### C. 默认镜像仍 fail-closed

- `cd Test3/backend && env -u TEST3_ISOLATION_IMAGE .venv/bin/python -m pytest -o addopts='' -m 'not live' -rs tests/unit/test_p1_rev03_isolation_preflight.py` → 退出码 0，8 passed / 1 skipped。
- skip 原因：`isolation image is not present locally: python:3.11-slim (no pull attempted)`；跑后 `docker image inspect python:3.11-slim` 仍非 0。

## UI-A1 八步走查

| 步骤 | 结果 | 证据 |
|---|---|---|
| 1. 侧栏可进入 Bot、Project、Settings | PASS | `screenshots/p6-t01-sidebar.png`；Playwright 断言三个 href 并逐页打开 |
| 2. 无顶级 Model/Skill/Market/Cron | PASS | 断言导航无 `/models`、`/skills`，页面无 Market/Cron 文本；`APP_ROUTE_PATHS` 单测 |
| 3a. /bots 空态可见 | PASS | `p6-t02-empty.png` |
| 3b. 创建 Bot（表单内选 model 与 skill 版本）后列表出现 | PASS | `p6-t02-create.png`、`p6-t02-ready.png` |
| 4. 打开项目工作台，左树有任务、进度可见 | PASS | `p6-t03-workstation.png`；T-01=100、T-02=40 |
| 5. 右四个 Tab 均可切换 | PASS | `p6-t03-workstation.png`；四个 `panel-*` 依次可见 |
| 6. splitter 可拖 | PASS | 拖动后 `aria-valuenow` 增大；手柄 `data-testid="ws-splitter"` 保留 |
| 7. baseline_stale banner 正确 | PASS | `p6-t04-banner.png`；含「baseline_stale」「基线」「重新审批」 |
| 8. 缺陷点击落到对应任务；错误/无权限有明确错误态 | PASS | `p6-t04-defect-locate.png`（detail=T-02）、`p6-t05-forbidden.png` |

## 新增与修改文件总表

新增前端：

- `src/components/AppShell.tsx`、`AppShell.test.tsx`
- `src/api/types.ts`
- `src/pages/Settings.test.tsx`
- `src/pages/bots/BotListPage.tsx`、`BotForm.tsx` 及测试
- `src/pages/project/ProjectWorkstationPage.tsx`、`GrantStatusBanner.tsx`、`DiscussionReviewPanel.tsx`、`DefectList.tsx` 及测试
- `e2e/p6-walkthrough.pw.ts`
- `docs/plans/screenshots/*.png`、`screenshots/P6-index.md`

新增后端：

- `tests/integration/test_p6_readonly_get.py`

修改：

- `src/App.tsx`（AppShell 挂载、`APP_ROUTE_PATHS`、`/bots*`、`/projects/:projectId`）
- `src/api/client.ts`（错误体兼容 + P2–P5 方法）、`client.test.ts`
- `src/pages/Projects.tsx`（项目卡片工作台链接）
- `src/styles.css`（Bot 表单、工作台、Grant/互评/缺陷样式）
- `app/api/routes_acceptance.py`、`app/api/routes_discussion.py`、`app/execution/acceptance.py`（只读列表）
- `tests/integration/snapshots/openapi_structure.json`（65 → 70）
- `docs/API.md`、`docs/plans/P6-report.md`

## 契约核对

- 无顶级 Model/Skill/Market/Cron：路由表与导航测试通过。
- 下线路由仍在：`/workstation/static-classroom`、`/deepseek/:id?` 指向 `RetiredFeature`，`App.retired.test.tsx` 全绿。
- `POST /api/bots` body 无 `bot_id`（单测断言）；编辑走 PATCH；归档需确认。
- 四态齐全：Bot 列表与工作台均有 loading / empty / error / forbidden。
- 未开闸：`execution_safety_ready` 仍只在 `Test3/backend/app/services/runtime.py:230` 赋 `False`；前端只展示，无开闸控件。
- `p1-pr-record.json` 无 diff，仍 `status=BLOCKED`、`github_pr_url=null`。
- 未 push；原 5 个未跟踪文件未纳入；`node_modules/`、`dist/`、`test-results/`、`playwright-report/` 未纳入（`Test3/.gitignore` 已覆盖）。
- OpenAPI 只增不删：65 → 70，删除 0，既有路径全部保留。
- 错误体解析同时兼容 `{"error_category","detail"}` 与旧 `{"detail":{category,summary,run_id}}`。
- 零真实付费 API：单测 mock fetch、走查 mock 路由；无 `model_live`。

## 声明

- 未进入 P7；未做杀进程恢复、真实 PR 闭环或自动 merge/deploy。
- 恰好 5 个普通本地 commit，parent 链从 `4c1dc888fd3d1f53d0011ab454ea49523af0424d` 起连续；无 amend/reset/force。
- T05 期间为走查补齐「项目 leader 作为默认 actor」的容器接线（`ProjectWorkstationPage.tsx`），与 T04 组件同属只读面板，本报告如实记录；该文件随 T05 提交。

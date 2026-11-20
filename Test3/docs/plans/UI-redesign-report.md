# OpenMausBot 风格前端改版报告（UI-R01～UI-R05）

本报告记录 HexaGraph Test3 前端的 OpenMausBot 风格改版。所有改动只在前端（`Test3/frontend/`）与文档/截图（`Test3/docs/plans/`），没有修改 `Test3/backend/`、没有新增迁移或业务路由、没有打开 `execution_safety_ready`、没有触碰 PR #34 记录、没有重启或抢占 5173 / 8765。

## 提交总览

| 卡片 | 完整 SHA | 提交信息 |
|---|---|---|
| R01 | `4b5b86d9def4545fcc1edbac85a9f8f690f36849` | `feat(frontend): UI-R01 OpenMausBot-style sidebar and BotAvatar` |
| R02 | `ed0172dc5c48aba0826e22a7a23824591dc78322` | `feat(frontend): UI-R02 bot workspace tabs, avatar picker and role presets` |
| R03 | `bdc1b60b701d712cb95f0cb6935d5d090b2e024c` | `feat(frontend): UI-R03 project team strip, members dialog and shared memory` |
| R04 | `37973e7d0b4047c10ab0f1b4ef1b3984a85c570b` | `feat(frontend): UI-R04 discussion room, defect cards and visual tokens` |
| R05 | 本报告所在提交 | `docs(frontend): UI-R05 redesign tests, screenshots and report` |

R05 的完整 SHA 由本文件内容决定，提交后见 `git log -1 --format=%H`（未 amend）。R05 同时补齐了「头像选择后侧栏即时刷新」的同文档事件（`hexagraph:bot-avatar-changed`）与折叠轨细节，属于 R01/R04 的收尾，如实记录。

## 与 OpenMausBot 的对照落地

| 参考要点 | 本次落地 |
|---|---|
| 产品分区：侧栏 / 主区 / 单 Bot 面板 | 侧栏 = 浏览导航 + 助手头像列表 + 最近运行；`/bots/:id` = 单 Bot 工作区（配置 / 个人记忆两个 Tab） |
| 展开态联系人行 | 头像 + display_name + role_template + active/archived 胶囊；当前路径命中时 `aria-current="page"` |
| 折叠 / 图标密度 | 保留 76px 折叠轨；下方竖排圆形头像，`title`/`aria-label` 为「名称 · 角色」 |
| 新建入口 | 侧栏「+ 新建 Bot」与 `/bots` 页顶部「+ 新建 Bot」，都链到 `/bots/new` |
| 头像编辑 | 默认首字母/Emoji + 确定性色板；`localStorage` 键 `hexagraph.botAvatar.v1` 持久化 Emoji / 色板（不含吉祥物、不含上传后端） |
| 单 Bot 一切设置 | 模型 / Skill / 归档仍在 Bot 表单与工作区；模型槽位页只保留家级 Settings |
| 视觉原则 | 全部复用 `--ink`/`--glass-*`/`--radius*` token；1440×1000 截图验收 |
| 不做的 | 无顶部计数徽章、无第二套设置入口、无开闸控件 |

明确未复制 OpenMausBot 任何源码；未移植 Maus 吉祥物、雕刻身体、节日服装、目光追随或 CursorAvatar。

## API 封装清单（只封装既有后端）

`src/api/client.ts` 新增：

- `memories({owner_bot_id?, project_id?, visibility?}, botId)` → `GET /api/memory/records`，带 `X-Bot-Id`
- `createMemory(body, botId)` → `POST /api/memory/records`
- `publishMemory(memId, expectedVersion, botId)` → `POST /api/memory/records/{mem_id}/publish`
- `addMembership(projectId, body)` → `POST /api/projects/{id}/memberships`
- `removeMembership(projectId, botId)` → `DELETE /api/projects/{id}/memberships/{bot_id}`（`req` 支持 204 无正文）

`src/api/types.ts` 新增 `MemorySource` / `MemoryRecord` / `MemoryCreate` / `ProjectMembership` / `MembershipCreate`。字段与后端 schema 同名；`secret_ref` 仍只是环境变量名。错误解析继续同时兼容 `{error_category, detail}` 与遗留 `{detail:{category,summary,run_id}}`。未新增任何后端路径或字段。

## 保留的契约核对

- `REQUIRED_NAV_KEYS`、`DEFAULT_NAV_ITEMS` 四项（工作台 / Bot / 项目 / 模型槽位）、`AppShell` props `{navItems, currentPath, children}` 未变；`aria-label="应用导航"` / `"浏览"`、折叠按钮「收起导航 / 展开导航」与 `aria-expanded`、品牌 `aria-label="HexaGraph 工作台"` 保留。
- 无顶级 `/models`、`/skills`、Market、Cron；`APP_ROUTE_PATHS` 仍含 `/workstation/static-classroom`、`/deepseek/:id?`，两条下线页仍渲染 `RetiredFeature`。
- `WorkstationSplitter`（`ws-splitter`、`ws-drawer-backdrop`、`ws-attention`）、`LEFT_PANEL_ID`、`COMPACT_VIEWPORT=1100`、`dirtyRef` 行为未改。
- 既有 testid 全部保留：`bots-loading/error/forbidden/empty`、`bot-form`、`bot-archive-confirm`、`ws-loading/error/forbidden/empty`、`project-workstation`、`task-tree`、`tab-*`、`panel-*`、`detail-task-code`、`ws-splitter`、`grant-banner`、`discussion-review-panel`、`defect-list`、`defect-${task_code}`、`shell-content`、`retired-feature`。新增 `sidebar-bot-list`、`sidebar-bot-rail`、`sidebar-new-bot`、`sidebar-bots-empty`、`bot-workspace`、`bot-tab-*`、`bot-panel-*`、`bot-avatar-change`、`bot-avatar-picker`、`team-strip`、`manage-members`、`actor-bot-select`、`members-dialog`、`project-memory-panel`。
- Settings 仍 `GET /api/config/models` 展示槽位，按钮「测试连通」仍 `POST /api/config/models/test`；未加 PUT。
- `DiscussionReviewPanel` 标题仍为「结论只由硬门槛、异议与轮次决定；分数仅作记录」，无「自动通过」措辞；`GrantStatusBanner` 文案（含 `execution_safety_not_ready`「不提供开闸入口」）未改。
- Member leader 变更严格 DELETE + POST（先降旧 Leader 再提目标），无 PATCH，失败显示 `error_category` 并重载。

## 出口命令与计数

| 命令 | 退出码 | 结果 |
|---|---|---|
| `cd Test3/frontend && npx tsc --noEmit` | 0 | 通过 |
| `cd Test3/frontend && npm test` | 0 | **34 files / 249 tests passed**（基线 27 / 209，只增不减） |
| `cd Test3/frontend && npm run build` | 0 | 构建成功（既有 chunk 体积告警，非失败） |
| `cd Test3/frontend && npx playwright test e2e/openmausbot-ui.pw.ts` | 0 | 1 passed；截图 11 张 |
| `cd Test3/backend && .venv/bin/alembic heads` | 0 | `0010 (head)` |
| `cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -q tests/integration/test_api_contract.py` | 0 | 28 passed（OpenAPI 70 条路径未删改） |
| `cd Test3/backend && .venv/bin/python -m pytest -o addopts='' -q tests/unit/test_pr_record_not_blocked_as_done.py` | 0 | 5 passed（记录为 PR_OPEN，关闭门槛绿；未改记录） |

## 截图索引

`Test3/docs/plans/screenshots/ui-redesign/index.md`，共 11 张：侧栏展开/折叠、Bot 列表/新建/工作区、项目列表/团队条/成员弹窗、互评与缺陷定位、Settings。P6 的 `p6-t0*.png` 未被覆盖。

## 人审微调

- 角色预设并入字段：`BotForm` 顶部那排独立预设按钮已去掉，改为「角色模板」下拉内置 Leader / 产品经理 / 后端工程师 / 测试运维 / 通用工程师五个选项；选中后仍按原规则建议模型槽位，编辑模式下下拉禁用且不为 PATCH 提交 `role_template`。后端 `role_template` 是自由字符串，UI 收敛为五个预设；若已有 Bot 的角色不在这五个之内，编辑时把原值作为额外选项显示，不会被悄悄改掉。
- 同批更新：`ui-r02-bot-new.png`、`ui-r02-bot-workspace.png` 重拍（后者编辑表单同样换成下拉），`index.md` 描述同步。
- 验证：`npx tsc --noEmit`、`npm test`、`npm run build`、`npx playwright test e2e/openmausbot-ui.pw.ts`（1 passed）均通过；最终计数见本节末条。
- 创建流程改为弹出式三步向导：`/bots/new` 直接在 Bot 列表页上方弹出「创建新 Bot」对话框（遮罩 + 模糊背景），页脚为 取消 / 上一步 / 下一步，第 1 步必须有名字才能继续。
  1. **身份**：104px 封面预览（由名字、职责与确定性色板实时生成）+ 名字输入 + Emoji / 色板 + 职责五选一（Leader / 产品经理 / 后端工程师 / 测试运维 / 通用工程师，各带一句分工说明），选中职责仍联动建议模型槽位。
  2. **模型**：Provider / 模型槽位 / 模型 / secret_ref / 允许工具 / 令牌预算。
  3. **Skill**：身份摘要（封面、名字、职责·槽位·模型、已绑定条数）+ Skill 版本绑定，底部「创建 Bot」。
- 头像草稿在创建成功后才按新 `bot_id` 写入 `hexagraph.botAvatar.v1`，不提前落库、不发后端字段；编辑模式仍是单页表单（禁用角色模板下拉，BotPatch 不带 `role_template`）。对话框根节点仍是 `data-testid="bot-form"`，新增 `bot-create-overlay` / `bot-identity` / `bot-duty-grid` / `duty-*` / `bot-step-summary`；Esc 与「取消」都回到 `/bots`。未复制参考实现的拟物形状选择器（属于对方签名吉祥物部件），只用我们自己的圆形头像 + Emoji + 色板。
- 同批更新：`ui-r02-bot-new.png` 重拍为第 1 步，新增 `ui-r02-bot-new-model.png`（第 2 步）与 `ui-r02-bot-new-skill.png`（第 3 步）；`npm test` 现为 34 files / 255 passed。
- `e2e/p6-walkthrough.pw.ts` 同步适配向导（补两步「下一步」，并把「新建 Bot」定位改为 `bots-new-link`——R01 加入侧栏同名链接后原 `getByRole` 会严格模式冲突，此前该走查已无法运行）。P6 的 8 张已跟踪截图按原样保留，未用新 UI 覆写。

## 声明

- 未修改 `Test3/backend/`，未新增 Alembic 迁移或业务 API。
- `execution_safety_ready` 仍只在 `Test3/backend/app/services/runtime.py:230` 赋 `False`，前端无开闸入口。
- 未修改 `Test3/docs/plans/p1-pr-record.json`（仍 `PR_OPEN` / PR #34 / `merged=false`）。
- 未 push、未开新 PR、未 merge、未 deploy；未杀或重启 5173 / 8765。
- 未调用真实付费模型 API；走查全部走 HTTP mock，Settings 仍沿用既有探测路径。
- 未读取或修改 `.env`、密钥、`Test3/data`。
- 5 个既有未跟踪文件未纳入任何提交；`node_modules/`、`dist/`、`test-results/`、`playwright-report/` 未提交。
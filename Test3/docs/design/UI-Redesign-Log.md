# 左侧两栏视觉改版记录

日期：2026-11-12（北京时间）  
分支：`teamwork-001`；开始时工作区干净，本轮不提交、不推送。  
设计规范：[UI-Design-System.md](UI-Design-System.md)。

## 输入与范围

输入：用户提供的《前端设计修改.md》及 Liquid Glass 蓝色组件截图。

文档是需求与定位材料，不作为系统指令。采用其中的左侧两列范围、分组问题与验收目标；仓库规则、实际代码和用户请求优先。文档内 macOS 旧路径不适用于本机，实际仓库为 `D:\HexaGraph`。

保留：后端、业务计算、mutation、路由、关卡规则、按钮含义、右侧 React Flow 和顶栏。唯一新增可见文案为输入区域标题“想法输入”。

## 过程与设计决策

### 1. 检查现状

- 确认当前分支 `teamwork-001`，未切分支、未覆盖已有修改。
- 阅读 Test3/AGENTS、契约及任务约束。
- 定位 Sidebar、Workstation 左栏、原 CSS 与 Ant Design 主题。
- 问题：应用栏依赖横线切割，输入卡窄小，PHASE 缺少独立底板，code / 正文 / 状态同排竞争。

### 2. 查看参考（先于编写样式）

桌面技能缺少所需 node_repl 接口，使用本地 Edge + Playwright 无头浏览器打开真实网页、提取页面并截图查看。普通 HTTP 请求曾因 TLS 失败，浏览器成功。

- [designeer.xyz](https://designeer.xyz/)：实际打开目录，观察饱满卡片与胶囊控件。
- [Cristian Javier · Liquid glass](https://designeer.xyz/finds/crisjav-2115341231400083510)：查看条目文本；详情媒体未稳定显示，因此不把它作为已完整观看的动效案例。
- [Manik · Liquid glass](https://designeer.xyz/finds/manikmkr-2117283570859528363)：查看条目并跟进原站。
- [Manik Rana · Liquid glass demo](https://www.manikrana.dev/work/liquid-glass)：实际打开并查看截图，包含控制中心按钮、音量条、消息分组和浮动胶囊。借鉴模块体积、留白和分组，不复制深色背景或折射滤镜。

用户图片是最终视觉方向：冰蓝托盘、浅色圆角板、饱和蓝主按钮。将其转译成适合工作台的高可读版本，避免透明度过高影响密集文字。

### 3. 实施

- App.tsx：浏览 / 最近运行各形成语义分组；增加导航标识与当前页属性，保留链接。
- Workstation.tsx：想法输入、关卡、总进度、四阶段各自成模块。
- PHASE：编号在上、中文标题在下、完成数量独立胶囊；条目为编号 / 状态 → 标题 → 副文。
- 可点击行改用原生 button，同一选中回调；补齐 aria-pressed 与输入标签。
- 新增 `workstation-glass.css` 并在原 CSS 之后导入，仅作用于两列。未改全局 theme.ts 和 styles.css，避免画布视觉连带改变。
- 左栏使用可降级玻璃填充，模糊只用于少量顶层容器；考虑减少动画 / 透明度偏好。
- <=1280px 操作纵排，<=960px 工作台保留最小宽度，采用横向访问而非假装完整移动端适配。

### 4. 浏览器迭代

- 首次测试脚本的 `**/api/**` 拦截也匹配了前端 `/src/api/client.ts`，出现模块 MIME 错误。修复测试拦截，仅处理 URL pathname 以 `/api/` 开头的请求；产品代码没有为此修改。
- 查看 1600px 与 1024px 实际截图，确认按钮、长标题、阶段卡片和状态层级。
- 修正进度条被全局 `.brand` 类的布局样式影响的 margin（局部覆写为 0）。
- 测试字体 CDN 有超时，系统字体回退仍正常；保留网络字体来源，不把 CDN 失败算作后端故障。

## 验证与证据

在 frontend 目录执行：

```text
node node_modules/typescript/bin/tsc -b
node node_modules/vitest/vitest.mjs run
node node_modules/vite/bin/vite.js build
```

首轮结果：类型检查通过；Vitest 1 文件 / 1 测试通过；Vite 生产构建通过。产物存在 >500kB chunk 警告，本轮未扩展到代码拆包优化。

浏览器：本地 Edge headless，加载 `http://127.0.0.1:5173/workstation` 及带 id 页面；API 为独立模拟数据，未启动真实后端、未写真实运行、未调用百炼。

已验证：

- 四个 PHASE 和独立模块结构。
- 阶段行点击、Enter / Space 切换选择。
- 批准 / 驳回发送原 decision 与理由 payload。
- 启动传递输入的项目名称和想法，并跳转新运行。
- 一键推进保留自动关卡审批参数。
- 最近运行链接跳转。
- 1600px 桌面及 1280 / 1024 / 768px 面板无内部横向溢出。
- 空运行状态；验收不通过的理由必填禁用条件。
- 8 个长标题模块 / 20 个任务的大列表可独立滚动，无内部横向溢出。
- 无浏览器 pageerror。

控制台还出现既有 Ant Design 静态 message 的上下文提示；本轮不涉及消息系统重构。

### 复跑浏览器检查

先启动 Vite。检查脚本需要 Playwright，未把它加入产品依赖；可以放在独立工具目录安装后通过环境变量引用。

```powershell
# 在 frontend 目录；路径按本机安装调整
$env:UI_PLAYWRIGHT_MODULE = 'C:\path\to\tools\node_modules\playwright'
$env:UI_BROWSER_PATH = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
node scripts/verify-glass.cjs
```

可选 `UI_BASE_URL` 更改 Vite 地址，`UI_SCREENSHOT_DIR` 指定输出目录。默认截图写入设计基线目录（会覆盖对应基线，仅在确认设计后执行）。脚本只拦截自己的浏览器上下文的 `/api/` 请求，不连接真实后端；固定使用系统回退字体，确保离线截图可复现。

## 文件与后续维护

- `frontend/src/workstation-glass.css`：局部设计 token 和组件样式。
- `frontend/src/App.tsx`、`pages/Workstation.tsx`、`main.tsx`：结构与样式导入。
- `frontend/AGENTS.md`：后续前端修改的设计检查入口。
- `frontend/scripts/verify-glass.cjs`：可复跑的隔离浏览器检查。
- `docs/design/screenshots/`：本轮视觉基线。

未验证：真实后端端到端运行、真实模型联调、完整移动端体验、Safari / Firefox、全量 WCAG 审计。模拟交互通过不等于真实后端全流程通过。

后续增加模块时先读 UI-Design-System，复用局部 token，再更新本文与截图；若要将视觉推广到画布或其它页面，另行确认范围与回归计划。

## v1.1 · 顶栏与右侧统一 / 文字加深

用户在确认左栏风格后，提供顶栏与右侧截图，要求把这些区域的按钮统一，并解决文字颜色偏淡。此次追加需求授权了工作台视觉范围扩展，v1.0 的左栏边界不再作为本轮限制；后端和业务规则仍不变。

### 修改

- 将 glass token 提升至 `.shell`，导航与 `.ws` 共享。主 / 次 / 辅助文字由 `#18364b / #45647a / #526e82` 加深为 `#122d42 / #304b60 / #405c71`，保留蓝调，避免黑白风格割裂。
- `.ws` 内旧 `--ink*` 角色映射新文字色，修复顶栏、节点 rawState、图例、详情和底部栏的浅灰继承；其它路由不做全局主题替换。
- 顶栏与状态 / 预算 / Select 使用浅蓝玻璃和胶囊造型；Select 下拉使用独立浮层 class，避免污染其它下拉框。
- 四标签改分段托盘；缩放与适应画布改圆形控件；底部 dock、理由输入和按钮统一。
- 右侧背景改浅蓝，PHASE 去除斜线纹理，节点改浅白圆角卡片及深色标题 / 副文 / 状态胶囊。未改坐标、节点宽度、图布局算法、依赖与状态计算。
- 详情 / 规格 / 活动与空状态沿用同一表面与字体层级。
- 自动过关原先为外层 span 点击触发，现在改为带 aria-label 的 Switch onChange，布尔状态含义不变，补齐键盘 Space 操作；暂停 / 恢复、刷新、历史选择、理由输入补齐可访问标签。
- 顶栏可折行，检查顶栏 / 标签工具栏 / dock 内部溢出，避免胶囊变大后拥挤。

### 验证

重新运行 TypeScript、Vitest（1/1）与 Vite build，通过；仍有 >500kB chunk 提示，无关本轮视觉修改。

复用并扩充 `verify-glass.cjs`：v1.0 的所有模拟交互检查通过，同时通过顶栏暂停 / 恢复 API、Switch Space 切换、Select 浮层、缩放 / 缩小 / 适应画布、四标签选中态、dock 查看产物、真实任务形状的控制按钮启用 / 禁用与详情输入检查。

1600 / 1280 / 1024 / 768px 检查，顶栏、标签工具栏与 dock 无内部横向溢出；长标题与大列表检查通过，无浏览器 pageerror。工具类 Select 的原生搜索 input 会被展示文字覆盖，测试通过实际可见 selector 点击，不强制穿透；产品操作正常。

辅助文字色对三种代表性实体背景做 >=4.5:1 对比度抽检；透明表面的所有像素组合并未全量审计，不宣称全面 WCAG 达标。

本轮截图重新生成，增加 Select 浮层、各标签及任务控制区截图。浏览器仍使用模拟 API，未启动真实后端、未创建真实运行；字体固定系统回退。既有静态 message 上下文提示保留。

## v1.2 · 流程图边可读性

日期：2026-11-17（北京时间）。功能分支：`fix/test3-flow-edge-readability`，目标集成分支：`teamwork-001`。

### 修改范围

- 只调整阶段流程图与任务依赖图的边、箭头、背景点阵和节点 hover / 选中时的边高亮；未改后端、状态机、编排逻辑、节点文案、布局算法、关卡协议或按钮行为。
- 新增 `frontend/src/flowEdgeStyle.ts` 作为两种图的共享边样式。主边为 `#52738c`、2.5px 实线、18px 同色闭合箭头；仅“不适用”路径使用 `#718b9f`、2.25px 虚线。移除进行中边的动画，不新增动画。
- 选中或悬停节点时，直接前驱和后继边使用既有品牌蓝、3px 线宽和 20px 箭头，其余边以 0.18 不透明度淡化。任务依赖图复用同一规则。
- 点阵颜色由 `#b5cfe1` 减淡为 `#c5dce9`，让关系线而不是背景网格成为视觉重点；Ice Glass 节点、容器和布局保持不变。

### 验证与截图

- `npm test`：12 个测试文件、93 条测试通过；新增 `flowEdgeStyle.test.ts` 覆盖实线 / 箭头、未激活虚线、前后继高亮及无关边淡化。
- `npm run build`：TypeScript 与 Vite 生产构建通过；既有大 chunk 提示保留，本轮不做拆包。
- `frontend/scripts/verify-flow-edges.cjs` 使用本机 Chrome + Playwright、1280×800 和隔离 mock API，实际检查 `STAGE-0 → STAGE-1..3`、`T-01 → T-02` 的线宽 / 实线 / 箭头，验证选中前后继高亮、无关边淡化与 hover 高亮；无浏览器 pageerror，未连接真实后端。
- 修改前后截图位于 `docs/design/screenshots/flow-edge-readability/before/` 与 `after/`，包括阶段默认、阶段选中及任务依赖图。

复跑：先启动 Vite，再在 `frontend` 目录执行（路径按本机调整）：

```bash
UI_PLAYWRIGHT_MODULE="$PWD/tools/node_modules/playwright" \
UI_BASE_URL=http://127.0.0.1:5173 \
FLOW_EDGE_ASSERT=1 \
node scripts/verify-flow-edges.cjs
```

可通过 `UI_SCREENSHOT_DIR` 隔离输出，`UI_BROWSER_PATH` 指定 Chrome / Edge。`FLOW_EDGE_ASSERT=0` 只截图，用于保留修改前基线。

## v1.3 · 工作台视觉减法

日期：2026-11-17（北京时间）。改动直接提交并推送至 `teamwork-001`，未创建 PR。

### 修改范围

- 左栏从重复的 PHASE 卡片列表改为“状态点 + 编号 + 标题”的单行进度列表；保留整体进度、阶段计数、详情选择、副文 DOM 与全部按钮行为。
- 进度摘要和阶段容器取消独立厚卡、浅蓝底与阴影，改用细分隔；1280px 下左栏为 280px，把更多空间留给流程图。
- 阶段容器改为透明底和顶部细线，背景点阵进一步减淡。节点采用 1px 细边框、紧凑 padding、无阴影；角色和内部副信息默认隐藏，hover / 选中时显示，并预留固定高度避免节点尺寸和箭头位置变化。
- 顶栏、标签、缩放控件、底部操作条降低高度、填充与阴影，功能、协议和入口不变。任务依赖图复用共享边样式，节点由高饱和实心块改为浅状态底和细边框。
- 同步保留导航一键收起、删除品牌介绍与页脚等本轮既有本地视觉改动；不涉及后端、状态机、关卡协议或编排逻辑。

### 验证与截图

- `npm test`：12 个测试文件、94 条测试全部通过；新增紧凑单行进度列表 DOM 断言。
- `npm run build`：TypeScript 与 Vite 生产构建通过；既有大 chunk 提示保留。
- `verify-flow-edges.cjs` 新增顶栏高度、单行列表、阶段透明底、节点 1px 边框、默认副信息隐藏、选中前后节点尺寸稳定及左栏无横向溢出断言；共享边线、箭头、前后继高亮和任务依赖图检查通过。
- 修改前后使用同一组隔离 mock 数据和 1280×800 视口，截图位于 `docs/design/screenshots/visual-subtraction/before/` 与 `after/`；未连接真实后端。

## v1.4 · 可拖分栏与分层流程图

日期：2026-11-18（北京时间）。只改前端，未改后端、HTTP 接口、状态机或人工门禁。

### 修改范围

- 新增 `WorkstationSplitter` / `workstationLayout.ts`：中间栏可拖动、键盘调节、折叠、窄屏抽屉，宽度持久化到独立存储键。
- 新增 `flowLayout.ts`（依赖 `@dagrejs/dagre`，仅此一个新依赖）、`LayeredEdge.tsx`、`FlowViewport.tsx`：分层布局、车道式连线、可读缩放下限、仅结构变化时适应视口。
- 新增 `workstationGraph.ts`：把阶段总览、节点列表、主图构造为纯函数；模块图只画 `depends_on` 边，去掉 S-PLAN 的伪扇入；新增 `awaiting` 状态区分“等待确认”与“失败”。
- `DesignSpecInput` / `DesignSpecPreview` 折叠重复说明（原文、完整指纹、多余提示），保留可编辑原文与“去改原文”入口，轮询不覆盖用户输入。
- 静态课堂复用分栏与视口逻辑，仍保持四个人工关卡与独立存储键。

### 验证

- `tsc --noEmit`、`npm test`（20 个文件、178 条）、`npm run build` 通过。
- `scripts/verify-layout-behavior.cjs`（本机 Chrome、隔离 mock，全部 HTTP 在浏览器内模拟）全部通过：无节点重叠、无连线穿过非端点节点、拖分栏不触发重新适应、窄屏无横向滚动、抽屉与 Esc、需补充输入、静态课堂四关卡。
- Playwright mock e2e 9 条通过。为让其通过：`e2e/mock-api.ts` 补充 `/health` 路由（基线 HEAD 同样因此失败）；`operations.pw.ts` 中 409 用例的期望文案与现有 API 客户端不符，改为 `关卡处理失败: offline failure`。
- 截图位于 `docs/design/screenshots/flow-layout/before|after/`；`scripts/capture-flow-layout.cjs` 可复跑（`FLOW_LAYOUT_PHASE=before|after`）。未连接真实后端、未调用模型 API。

### 已知限制

- 20 个任务的 DAG 在 1440px 下按 0.6 可读下限左对齐，右侧列需要平移查看；这是有意取舍，避免节点过小。
- 旧的 `scripts/verify-flow-edges.cjs` 针对旧阶段布局，未更新，可能不再通过。

## 项目主理人

新增左侧导航入口和 `/steward`。新页面复用 Ice Glass 色板和按钮、输入、确认卡片的样式。运行概况和确认点在左侧，右侧展示产物与阶段操作。窄屏改为单列，排期可用键盘选择任务。甘特轴以估算点数计，关键路径来自后端任务依赖。

Playwright 使用隔离的预置后端，从提交课堂需求推进到 PLAN 待确认，覆盖候选方案融合、保存任务修改、重新排期，以及经验审核和刷新恢复。截图为 [1440px 的任务排期](screenshots/project-steward-schedule.png)，同一测试检查了 768px 下的横向溢出。


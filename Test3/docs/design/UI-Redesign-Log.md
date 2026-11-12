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

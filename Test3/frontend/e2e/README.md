# #18 前端关键操作自动化测试

独立测试目录，页面、样式、API 客户端和后端业务逻辑均不修改。开工方案见 [Issue 评论](https://github.com/WaterProMax/HexaGraph/issues/18#issuecomment-6846715908)。

## 环境和命令

测试 runner 要求 **Node.js 20+**（原应用 README 的 Node 18 不适用于新增 Playwright 1.65）。

```sh
cd Test3/frontend
npm ci
npx playwright install chromium
npm test
npm run build
npm run test:e2e:types
npm run test:e2e
npm run test:e2e -- --repeat-each=2
```

runner 自动启动前端，5173 端口必须空闲；不会复用用户已开的服务。默认单 worker、零重试，不以重试隐藏失败。`*.pw.ts` 不会被原 Vitest 收集。

mock 用真实浏览器操作 React 页面和真实 API 客户端，仅拦截 HTTP。覆盖创建项目与运行、批准关卡、暂停/恢复、终止取消与确认、创建项目失败、创建运行失败、批准关卡失败与原页重试恢复、409 冲突保持当前阶段、验收失败时批准必须有非空理由。检查 POST 路径/请求体和页面可见结果；未知接口和页面异常使测试失败。Google Fonts 返回空 CSS，其余外部请求中止并报错。SSE 为静态心跳，**不声称验证 SSE 推送、重连或实时延迟**。

## scripted 真实前后端关键操作集成

先在独立 Python 3.11+ 虚拟环境安装后端依赖，并激活环境，使 `python` 指向它：

```sh
python -m venv .venv
# Windows: .venv/Scripts/Activate.ps1
# POSIX: source .venv/bin/activate
python -m pip install -e ../backend
npm run test:e2e:integration
```

8765 和 5173 端口必须空闲。runner 自行启动专用后端，强制 `scripted` + `study-room`、清空模型密钥并使用临时数据目录；退出后清理。不要连接用户真实数据。浏览器 `/api` 由 Vite 代理到该后端，无 mock API 响应。

这个场景从 UI 创建运行、批准第一个关卡进入阶段 1、暂停/恢复，再在 `/runs/:id` 总览页取消并确认终止。它验证关键操作的前后端集成，**不证明阶段 2–8、任务执行、崩溃恢复或真实百炼链路**。完整最终验收仍需 #14/#15/#16 离线集成后复跑；真实模型不属于本测试依赖。

## 证据与失败复现

mock 生成 `test-results/mock/` 与 `playwright-report/mock/`，真实集成生成 `test-results/integration/` 与 `playwright-report/integration/`。两类运行互不覆盖；同类下次运行仍会覆盖，需先另存。查看：

```sh
npx playwright show-report playwright-report/mock
npx playwright show-report playwright-report/integration
npx playwright show-trace test-results/mock/<case>/trace.zip
npm run test:e2e -- --grep "failed gate"
```

trace 包含请求、响应和页面，仅对本套离线夹具/专用 scripted 服务保存与分享。不要对真实含密钥或个人数据的服务直接录制。已提交的 `evidence/` 只有合成离线数据截图与验证摘要，不含本机路径和账号凭据。

若业务测试失败，保留命令、基线 SHA、最短点击步骤、期望/实际、trace，并交回 #14（页面交互）、#15（契约/推送）、#16（恢复/运行时）；不要改测试期望以掩盖缺陷。

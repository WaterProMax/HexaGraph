# 11 月 18 日回归与验收记录

共享基线 `teamwork-001` 为 `9b27c5567523c75746c6430b335043993b6a1977`。环境为 Windows、Node 22.15.0、Python 3.14.3。Playwright 使用 Chromium。本轮验证使用隔离数据和离线模型夹具。

| 检查 | 本轮结果 |
|---|---|
| `npm test -- --maxWorkers=2 --minWorkers=1` | 14 个文件，109 项通过 |
| `npx vitest run src/pages/Workstation.test.tsx --maxWorkers=1 --minWorkers=1` | 整文件 21 项通过，包含之前在加载期失败的批准异常用例 |
| `npm run test:e2e:types`、`npm run build` | 均通过。构建仍提示已有 bundle 大小警告 |
| `npm run test:e2e` | 11 项浏览器测试通过，包含两项静态课堂验收 |
| `npm run test:e2e:integration` | 两项真实 HTTP 浏览器集成通过，覆盖 scripted 关键操作与 DeepSeek 无密钥失败 |
| `python -m pytest -o addopts='' -q -m 'not live'` | 基线 162 项通过、17 项失败、1 项排除 |

初次前端全量发现两项失败。导入大小上限用例原断言文案与当前 UI 不一致。关卡异常用例整文件运行时卡在运行加载视图，改用关卡标题作为就绪信号，按钮交互和错误断言保留。最新全量和整文件复测通过，尚未证明导致原时序问题的全部机制。浏览器基线失败由新增 `/health` 请求未被夹具覆盖及 409 提示文案更新引起。

真实 HTTP 设计规格彩排使用仓库自带 manual scripted 服务。自习室样例上传成功，两道人工关卡可批准，发起手动调度的 HTTP 请求成功。此机调度后 T-01 为 `needs_human`，T-02 为 `blocked`，刷新后仍有预置输出及模拟执行标识。第二次导入缺项文本返回 `needs_input / missing_fields`。

最小复现执行阻塞：在 Test3/backend 的 Python 环境中执行 `python -m pytest -o addopts='' -q tests/e2e/test_design_spec_http_server.py::test_offline_queue_is_one_success_one_missing_then_exhausted`。期望两个任务 `done`，实测依次为 `needs_human` 和 `blocked`。同一基线另有 OpenAPI 快照差异和 WinError 1314 等失败。恢复、完整任务执行和真实模型联调仍需团队继续验收，#18 保持 Open。

静态课堂验收在浏览器中确认了十条预置讨论、四道人为确认、T-02 与 T-03 同时运行而 T-04 等待、刷新恢复、三次复位及暂停播放。静态验收面板展示的是教学案例的预置结果。仓库测试数来自上表的实际执行。

实测截图：[课堂分叉与等待汇合](classroom-parallel.png) · [无密钥认证失败](deepseek-no-key.png)。

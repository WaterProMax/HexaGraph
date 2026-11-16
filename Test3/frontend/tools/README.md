# 前端浏览器回归工具（非产品依赖）

Playwright 只装在本目录，不进 `frontend/package.json`。

```bash
cd Test3/frontend/tools
npm install
# 使用本机 Chrome 通道，无需再下载浏览器包

cd ..
npm run dev -- --host 127.0.0.1 --port 5173

UI_PLAYWRIGHT_MODULE=$PWD/tools/node_modules/playwright \
  UI_BASE_URL=http://127.0.0.1:5173 \
  node scripts/verify-design-spec.cjs

# 计划「六」逐按钮表（mock /api，写截图与 docs/superpowers/evidence/task-5-click-log.md）
UI_PLAYWRIGHT_MODULE=$PWD/tools/node_modules/playwright \
  UI_BASE_URL=http://127.0.0.1:5173 \
  node scripts/verify-design-spec-acceptance.cjs
```

可选：`UI_BROWSER_PATH` 指定浏览器可执行文件；`UI_SCREENSHOT_DIR` 指定截图目录。

## 设计规格页面 + 真实后端 HTTP 离线验证

`../scripts/verify-design-spec-http.cjs` 不 mock `/api`。关键确认和调度全部由页面完成，脚本仅以 GET 只读核对后端状态。测试服务器显式使用 `ScriptedProvider`，关闭会读取 settings 的 lifespan，不读取 `.env`，不调用真实模型。健康检查为 `schedule_mode=manual`。主样例是 `examples/design-specs/self-study-room.md`；`club-signup.md` 只验证上传/原文保存。

1. 终端一，从 `Test3/backend` 启动真实 FastAPI 和测试夹具：

   ```bash
   PATH="$PWD/.venv/bin:$PATH" \
     .venv/bin/python tests/e2e/design_spec_http_server.py --host 127.0.0.1 --port 8765
   ```

   也可用 `uv run python tests/e2e/design_spec_http_server.py`。数据默认写入新的临时目录，启动日志打印其路径。

2. 终端二，从 `Test3/frontend` 启动真实 Vite：

   ```bash
   npm run dev -- --host 127.0.0.1 --port 5173
   ```

3. 终端三准备 Playwright（只装 Node 包，使用本机 Chrome，不下载浏览器）：

   ```bash
   mkdir -p /tmp/hexagraph-e2e
   cd /tmp/hexagraph-e2e
   npm install --no-save playwright@1.61.1
   ```

4. 从 `Test3/frontend` 执行：

   ```bash
   UI_PLAYWRIGHT_MODULE=/tmp/hexagraph-e2e/node_modules/playwright \
     node scripts/verify-design-spec-http.cjs
   ```

覆盖成功与缺项两条路径，包括 DESIGN/PLAN 页面确认、任务依赖与状态、页面调度、成功/缺项后的刷新。截图写入 `docs/design/screenshots/design-spec-http-*.png`。

复位与队列：没有生产环境公开复位 API。每次启动只有一次成功整理 + 一次缺项整理，然后队列耗尽。完整重跑必须停掉终端一并换新的隔离数据目录再启动。自动化测试与人工演示必须分开启动，不要共用进程或数据目录。演示步骤见 `docs/Demo.md`。

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
```

可选：`UI_BROWSER_PATH` 指定浏览器可执行文件；`UI_SCREENSHOT_DIR` 指定截图目录。

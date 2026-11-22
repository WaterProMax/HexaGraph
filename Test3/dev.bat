@echo off
rem HexaGraph Test3 一键开发启动：后端(8765) + 前端(5173)，各开一个窗口。
rem 注意：后端故意不用 --reload（Windows 上 uvicorn 热重载杀不掉旧 worker，会继续用旧代码服务）。

start "HexaGraph backend :8765" cmd /k "cd /d %~dp0backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8765"
start "HexaGraph frontend :5173" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo  后端健康检查: http://127.0.0.1:8765/api/health
echo  前端页面:     http://localhost:5173
echo  关闭对应窗口即停止服务。

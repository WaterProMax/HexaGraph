# Test3 多体工作流工作台

按 `teamwork-001` 上的 `Design.md` / `Architecture.md` / `ImplementationPlan.md` 实现。不使用 LangGraph、AutoGen。规则是确定性纯函数。模型走阿里云百炼（DashScope）；默认测试与本机演示走 `scripted`，不打真实网。

设计文档以仓库根目录为准；`Test3/` 下同名文件是符号链接。

## 环境

- Python 3.11+（本机验证为 3.12 + `uv` 0.13.7）
- Node.js 18+（前端）
- 可选：`DASHSCOPE_API_KEY`（只放本机 `.env`，不要提交）

## 安装

```bash
cd Test3
make install
cp .env.example .env   # 按需填写密钥
```

`make install` 会在 `backend/` 执行 `uv sync --group dev`，并在存在 `frontend/package.json` 时执行 `npm install`。

## 配置

| 变量 | 作用 |
|---|---|
| `DASHSCOPE_API_KEY` | 百炼 OpenAI 兼容接口密钥 |
| `FEEDBACK_HASH_KEY` | 反馈作者 HMAC；未设置时 `POST /api/runs/{id}/feedback/import` 返回 400 |
| `TEST3_LLM_PROVIDER` | `scripted`（默认）/ `replay` / `dashscope` |
| `TEST3_SCRIPTED_FIXTURE` | `scripted` 时默认 `study-room`，灌入自习室 M1 队列 |
| `TEST3_DATA_DIR` | 覆盖数据目录，默认 `Test3/data/` |
| `TEST3_HTTP_TRUST_ENV` | `1` 时 HTTP 客户端读取 shell 的 `http(s)_proxy` / `all_proxy`；默认 `0` 直连（本机代理常把 `all_proxy` 指到未装的 SOCKS 端口） |

槽位与角色见 `config/models.yaml`、`config/roles.yaml`。硬上限见 `config/limits.yaml`：并发 6、修复 6 轮、每点 150 万令牌、P1 通过线 0.9。

真实联调：

```bash
# .env
DASHSCOPE_API_KEY=sk-...
TEST3_LLM_PROVIDER=dashscope
FEEDBACK_HASH_KEY=请换成足够长的本地随机串
```

然后 `make check-models`。本轮未持有可用密钥，没有跑通百炼探测。

## 运行

```bash
# 终端 1
cd Test3 && make dev-backend   # http://127.0.0.1:8765

# 终端 2
cd Test3 && make dev-frontend  # http://127.0.0.1:5173/workstation ，/api 代理到后端
```

默认 `scripted` + `study-room`：在前端 Workstation（`/workstation`）或 API 创建项目并提交自习室想法后，会按 Design.md 金标准走完想法 → 讨论 → 方案 → 评审 → SPEC → 设计规格（DESIGN）→ 任务分解（PLAN）→ 编排器执行（T-01/T-02）→ 验收导出。此路径会启动 5 秒自动调度。设计规格离线主演示请用 `examples/design-specs/self-study-room.md` 和 `backend/tests/e2e/design_spec_http_server.py`（手动调度，见 `docs/Demo.md`）；不要把 `club-signup.md` 说成生成了座位任务。Workstation 左侧支持输入需求并查看分阶段任务进度，右侧通过 React Flow Twin Graph 可视化全流程及任务依赖图，并支持任务级控制（pause/resume/retry/skip/force-pass/takeover/submit-takeover）。

示例想法：

```
做一个帮同学在期末周找到有空位自习室的小程序。
```

## 静态课堂演示（可无限重播）

完整静态案例「自习室座位查询」覆盖四类角色讨论、两处分歧、人工确认、五项任务依赖与并行、模拟执行和验收。它只使用前端预置数据，不创建真实运行、不读取密钥、不调用模型，也不消耗 scripted 队列。

```bash
npm --prefix Test3/frontend run dev -- --host 127.0.0.1 --port 5173
```

访问 http://127.0.0.1:5173/workstation/static-classroom ，或从左侧导航进入「静态课堂演示」。中文操作说明、五分钟讲解脚本和实际测试边界见 [静态课堂演示文档](docs/StaticClassroomDemo.md)。

## DeepSeek 真实运行

这是左侧导航中独立于原“工作台”的 **DeepSeek 真实运行** 页面。它按**单次运行**绑定 DeepSeek，不修改 `TEST3_LLM_PROVIDER`，也不会把旧脚本运行或百炼运行切换到新供应商。两种模式的运行列表和详情路径分开展示。

1. 编辑本机 `Test3/.env`（该文件已被 `.gitignore` 忽略）：

   ```dotenv
   DEEPSEEK_API_KEY=填写你的密钥
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   DEEPSEEK_MODEL=deepseek-flash
   DEEPSEEK_TIMEOUT_S=120
   DEEPSEEK_STAGE_TIMEOUT_S=600
   DEEPSEEK_MAX_TOKENS=16384
   ```

   默认模型名与 Base URL 依据 [DeepSeek 官方文档](https://api-docs.deepseek.com/zh-cn/)；如需更换模型，以官方当前文档为准。

2. 正常执行 `make dev`，点击左侧导航 **DeepSeek 真实运行**（`/deepseek`）。
3. 粘贴或读取设计规格，并填写目标语言、框架、存储与部署边界。未填写的技术项会明确标为“未指定”，模型不得自行编造。
4. 系统真实调用 DeepSeek 整理 SPEC / DESIGN，停在 **DESIGN 基线确认**；确认后真实生成 TaskGraph，再停在 **PLAN 基线确认**。只有确认 PLAN 后才物化任务。
5. 点击调度执行后，复用现有受限执行器：工作区写集、命令白名单、超时、真实命令结果、代码审查、集成回归、Git 合并和人工控制均保留。

**边界：**真实 API 会产生费用；不会自动回退到预置答案、scripted 或百炼。密钥缺失、认证失败、超时、JSON/结构错误、缺字段、依赖环、写集冲突等会显示为失败或待人工处理。任务失败不会被包装成演示成功。PLAN 阶段有总超时，可终止运行；服务重启不会自动续跑被中断的模型阶段。

## 测试

前端视觉维护请先读 [Ice Glass UI 设计规范](docs/design/UI-Design-System.md)；本轮修改与验证记录见 [UI 改版记录](docs/design/UI-Redesign-Log.md)。

```bash
cd Test3
make test          # 后端，排除 @pytest.mark.live
make e2e           # tests/e2e
make lint          # ruff；mypy 目前允许失败（Makefile 里 || true）
cd frontend && npm test   # vitest：控制按钮可用状态
```

本轮实测见 `docs/Progress.md` 与 `docs/Acceptance.md`。

## 常见问题

- **空密钥却选了 dashscope**：进程会打百炼并失败。默认 provider 是 `scripted`，避免误调用。
- **导入反馈 400**：设置 `FEEDBACK_HASH_KEY`。
- **任务页没有图数据**：需要先走到 PLAN 关卡并物化任务；M1 脚本只到 SPEC。
- **密钥进仓库**：`.gitignore` 忽略 `.env`；日志会替换 `DASHSCOPE_API_KEY` 与 `DEEPSEEK_API_KEY` 明文，运行快照只保存供应商、模型标识和非敏感 Base URL。
- **DeepSeek 整理瞬间失败、界面只显示“设计规格整理失败”**：先看 `Test3/data/runs/<run_id>/import-error.txt`。常见原因是 shell 导出了 `all_proxy=socks5h://127.0.0.1:7891`，而 httpx 没装 `socksio`，会在建连接前抛 `ImportError`。默认 `TEST3_HTTP_TRUST_ENV=0` 直连可绕开；确需代理时安装 `httpx[socks]` 并设 `TEST3_HTTP_TRUST_ENV=1`。

偏差与未完成项见 `docs/Handoff.md`。

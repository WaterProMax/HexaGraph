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

默认 `scripted` + `study-room`：在前端 Workstation（`/workstation`）或 API 创建项目并提交自习室想法后，会按 Design.md 金标准走完想法 → 讨论 → 方案 → 评审 → SPEC → 设计规格（DESIGN）→ 任务分解（PLAN）→ 编排器执行（T-01/T-02）→ 验收导出。Workstation 左侧支持输入需求并查看分阶段任务进度，右侧通过 React Flow Twin Graph 可视化全流程及任务依赖图，并支持任务级控制（pause/resume/retry/skip/force-pass/takeover/submit-takeover）。

示例想法：

```
做一个帮同学在期末周找到有空位自习室的小程序。
```

## 测试

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
- **密钥进仓库**：`.gitignore` 忽略 `.env`；日志里会替换 `DASHSCOPE_API_KEY` 明文。

偏差与未完成项见 `docs/Handoff.md`。

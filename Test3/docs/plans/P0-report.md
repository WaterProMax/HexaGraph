---
safe_isolated_baseline: true
coordination_required: true
worktree_plan: user_provided_path
p0_cards_complete: ["P0-T01", "P0-T02", "P0-T03", "P0-T04", "P0-T05"]
---

# P0 只读基线与隔离判定报告

- 仓库根：`/Users/cenghuanxiao/Desktop/HexaGraph`
- 任务范围：仅 P0-T01…P0-T05；未阅读或实施 P1+ 任务卡。
- 阶段性质：只读核验与证据草稿；未修改业务代码、构建文件或锁文件，未 commit、push、stash、reset、clean、merge、deploy 或新增 worktree。
- 测试执行：**未运行（P0 只读）**。未运行 `make`、npm test、pytest、Playwright、Alembic、迁移、真实模型或付费 API。
- 证据文件：`baseline-lock.json`、`p0-t01-cmd.log`、`decommission-target-state.json` 与本报告。开始前四者均不存在；子 Agent 写本报告前再次确认 `P0-report.md` 不存在，未覆盖其他任务文件。

## P0-T01 · 本地与远端引用

记录时间：`2026-11-19T14:10:23.386739+08:00`（带 `+08:00` 偏移）。完整 stdout/stderr/退出码见 `p0-t01-cmd.log:7-48`。

| 项目 | 实际命令结果 |
|---|---|
| `git branch --show-current` | `chore/test3-retire-static-classroom-and-deepseek` |
| HEAD 前 12 位 | `552923d9992a` |
| `origin/teamwork-001` 前 12 位 | `552923d9992a` |
| 初始 dirty 条数 | **0** |
| `fetch_status` | **ok**（唯一一次 `git fetch origin teamwork-001`，退出码 0） |
| worktree 数 | **1** |

完整 HEAD：`552923d9992a38eb806ff760833bb71ac4b759cf`。fetch 后执行 `git rev-parse origin/teamwork-001` 得到同一完整 SHA；该值不是从历史任务书抄入。fetch 设置了 `GIT_TERMINAL_PROMPT=0`，没有交互凭证，也未执行 push。

T01 在写任何证据文件前执行明确的 `git status --porcelain`，stdout 为空，原始行数为 0，因此锁文件 `dirty=[]`：

```text
<无 stdout；0 行>
```

`git worktree list` 原始输出：

```text
/Users/cenghuanxiao/Desktop/HexaGraph  552923d [chore/test3-retire-static-classroom-and-deepseek]
```

fetch 的 stderr（成功分支更新信息，不是错误）：

```text
From https://github.com/WaterProMax/HexaGraph
 * branch            teamwork-001 -> FETCH_HEAD
```

历史参考仅为对照：`teamwork_001_known_old=1950b621b1d639b5da717a666ca7a2ecd3247aaa`、`main_known_old=f6a7b22ff7acaf18f01cae833a07b27ba2c73525`。当前 HEAD 与历史 teamwork SHA 字符串比较结果为 `head_equals_historical_teamwork=false`。

**当前 HEAD 与历史 `1950b621` 不同，后续挂接行号必须重搜，不得照抄历史行号。** 本报告 T03 已按当前树重搜。

## P0-T02 · 构建、测试与 Alembic

### Makefile 实际配方

来源：`Test3/Makefile:17-30`。原文如下（未执行）：

```make
test:
	cd $(BACKEND) && uv run pytest -q -m "not live"

test-live:
	cd $(BACKEND) && uv run pytest -q -m live

e2e:
	cd $(BACKEND) && uv run pytest -q tests/e2e
```

`BACKEND` 的定义见 `Test3/Makefile:2-4`。Makefile 全文件为 1-36 行，未见 `build` 目标。`test-live` 只是登记实际配方，本阶段没有也不得据此进行真实模型探测。

### frontend/package.json 实际 scripts

来源：`Test3/frontend/package.json:6-14`：

```json
{
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview",
  "test": "vitest run",
  "test:e2e": "playwright test",
  "test:e2e:integration": "playwright test --config playwright.integration.config.ts",
  "test:e2e:types": "tsc -p e2e/tsconfig.json"
}
```

### 可复制命令表

| 用途 | 已核实入口/配方 | 证据 |
|---|---|---|
| 后端单测示例 | `cd Test3/backend && uv run pytest tests/unit/<name>.py -v` | 路径前缀遵循 C.0；runner 由 Makefile 与 pyproject 证实 |
| `make test` | `cd $(BACKEND) && uv run pytest -q -m "not live"` | `Test3/Makefile:17-18` |
| `make e2e` | `cd $(BACKEND) && uv run pytest -q tests/e2e` | `Test3/Makefile:29-30` |
| 前端 `npm test` | `vitest run` | `Test3/frontend/package.json:10` |
| 前端 `npm run test:e2e` | `playwright test` | `Test3/frontend/package.json:11` |
| 前端 `npm run build` | `tsc -b && vite build` | `Test3/frontend/package.json:8` |

`make_e2e_equals_npm_test_e2e=false`：前者是后端 pytest 的 `tests/e2e`，后者是前端 Playwright，明确不是同一入口。后续所有后端单测命令以本表为准；进入 `Test3/backend` 后 pytest 路径必须以 `tests/` 开头，不重复 `Test3/backend/` 前缀。

后端使用 uv 的证据：`Test3/backend/pyproject.toml:21-29` 声明 dev dependency group，Makefile 各后端配方使用 `uv run`，且 `Test3/backend/uv.lock` 存在；本阶段没有读取锁文件内容或执行 `uv sync`/`uv run`。

### Alembic head（静态图推导）

- `Test3/backend/alembic.ini:1-3` 指向 `script_location = alembic`。
- versions 只读枚举仅发现 `Test3/backend/alembic/versions/0001_init.py`。
- 该文件 `revision = "0001"`、`down_revision = None`（`0001_init.py:11-12`）。因此 down_revision 图只有一个节点、没有被其他已知节点指向的非 head，`alembic_head="0001"`，`next_alembic_hint="0002"`。
- 推导方式明确为“单一 versions 文件的 revision/down_revision 静态图”，不是数据库当前版本查询。`alembic history` **skipped**：本阶段只读，且不运行可能自动同步依赖或接触数据库的 `uv run`。未执行迁移。

## P0-T03 · `hook_drift` 全表

实际使用 `functions.grep`（ripgrep 正则）、`functions.glob` 与 `functions.read`；没有把历史行号当作当前行号。下表覆盖 contracts.md C.8 全表及 P0-T03 追加符号，共 31 项；相同结构化数据见 `baseline-lock.json:31-311` 的 `hooks`。`—` 对 missing 项表示 `found_file/found_line=null`，不是历史行号。

| # | 符号 | 历史位置（仅对照） | 当前真实位置 | 状态 | 简短上下文 |
|---:|---|---|---|---|---|
| 1 | `Workbench.schedule_once` | `services/runtime.py:1561` | `Test3/backend/app/services/runtime.py:1543` | found | 1544-1548 退休拒绝后进入调度锁；API 在 routes.py:388-394 |
| 2 | `Workbench.resolve_gate` | `services/runtime.py:1036` | `Test3/backend/app/services/runtime.py:1052` | found | 1059 expected_revision；1081-1087 校验并递增 revision |
| 3 | `RunState.revision` | `services/runtime.py:100` | `Test3/backend/app/services/runtime.py:100` | found | `revision: int = 1`；不得用作 grant stale 输入 |
| 4 | `class RunState`（追加） | 同上区域 | `Test3/backend/app/services/runtime.py:95` | found | `@dataclass` 在 94 |
| 5 | `execute_task` | `services/runtime.py:1616` | `Test3/backend/app/services/runtime.py:1600` | found | 1608 任务 revision；1617-1624 repo/wt 与 create_worktree |
| 6 | provenance 读取 | `services/runtime.py:518+` | `Test3/backend/app/services/runtime.py:554` | found | `_is_retired_run` 读 artifacts.provenance.mode；另见 560/629/739/937/1227 |
| 7 | `apply_transition` | `orchestrator/transition.py:13` | `Test3/backend/app/orchestrator/transition.py:13` | found | 13-24 写 task.state 并递增任务 revision |
| 8 | `POST .../schedule` | `api/routes.py:281` | `Test3/backend/app/api/routes.py:388` | found | 389-394 调 schedule_once；当前无 task_codes 请求体 |
| 9 | `POST .../gates/{id}/resolve` | `api/routes.py:111` | `Test3/backend/app/api/routes.py:156` | found | 157-169 查 run 并调 Workbench.resolve_gate |
| 10 | `GateResolve` | `api/routes.py:31` | `Test3/backend/app/api/routes.py:38` | found | 字段 decision/payload/expected_revision 在 39-41 |
| 11 | `classify_llm_error` | `app/errors.py:107` | `Test3/backend/app/errors.py:127` | found | 127-152 异常分类 |
| 12 | `Gateway.complete` | `llm/gateway.py` 类内 | `Test3/backend/app/llm/gateway.py:61` | found | 61-65 semaphore/bucket 后进入 retry |
| 13 | `class Gateway`（追加） | `llm/gateway.py` 类内 | `Test3/backend/app/llm/gateway.py:44` | found | provider.complete 当前在 76 使用槽配置 |
| 14 | `call_agent` | `agents/runtime.py:57` | `Test3/backend/app/agents/runtime.py:63` | found | 63-84 当前无 bot_id/pin/memory 参数 |
| 15 | 静态课堂路由 | `frontend/src/App.tsx:146` | `Test3/frontend/src/App.tsx:141` | found | Active 的是 RetiredFeature 退休说明路由，不是原演示 |
| 16 | deepseek 路由 | `frontend/src/App.tsx:147` | `Test3/frontend/src/App.tsx:142` | found | `/deepseek/:id?` 挂载 RetiredFeature |
| 17 | `WorkstationSplitter` | 历史称存在 | `Test3/frontend/src/components/WorkstationSplitter.tsx:8` | found | Workstation.tsx:44 import、942 使用 |
| 18 | dirtyRef / 分栏 | 前端既有 | `Test3/frontend/src/components/DesignSpecInput.tsx:90` | found | 115 重置、118 防覆盖、141 标记；分栏见上行 |
| 19 | `make test` / `make e2e` | Makefile 历史称存在 | `Test3/Makefile:17` | found | test 17-18；e2e 29-30 |
| 20 | `npm test` | package.json 历史称存在 | `Test3/frontend/package.json:10` | found | `vitest run`；e2e 在 11 |
| 21 | git worktree | `workspace/gitops.py` 待核 | `Test3/backend/app/workspace/gitops.py:78` | found | already_present；remove 在 56-60，P0 未调用 |
| 22 | `StaticClassroomDemo`（追加） | `App.tsx:146` | — | missing | 当前源码无符号；仅 README.md:72 链接与 docs/StaticClassroomDemo.md:1-3 历史说明 |
| 23 | `deepseek` 专用链符号（追加） | `App.tsx:147` | `Test3/backend/app/services/runtime.py:554` | found | 当前为退休只读判断/守卫，不是可用专用 provider |
| 24 | `app/api/runtime.py`（追加） | 契约要求确认 | — | missing | **不存在 app/api/runtime.py**；实际为 app/services/runtime.py |
| 25 | `app/bots` | 设计提议 | — | missing | 目录不存在 |
| 26 | `app/memory` | 设计提议 | — | missing | 目录不存在 |
| 27 | `app/execution` | 设计提议 | — | missing | 目录不存在 |
| 28 | `app/discussion` | 设计提议 | `Test3/backend/app/discussion/__init__.py:1` | found | **already_present**；另有 engine.py/rules.py，不等于新域契约已完成 |
| 29 | `app/skills` | 设计提议 | — | missing | 目录不存在 |
| 30 | `frontend/src/pages/bots` | 设计提议 | — | missing | 目录不存在 |
| 31 | `ExecutionGrant` / `approved_baseline_hashes` / `execution_profile` / `grant_stale_reason` / `task_codes` | P0 接口现状追加核验 | — | missing | backend/app 前四项无匹配；routes.py 的 task_codes 无匹配 |

### 实际 HTTP 挂接与接口边界

- `Test3/backend/app/main.py:50` 使用 `app.include_router(router, prefix="/api")`；router 定义在 `api/routes.py:24`。
- 实际调度路由为 `POST /api/runs/{run_id}/schedule`（`api/routes.py:388-394`），调用 `Workbench.schedule_once`，成功形为 `{"started": started}`；当前函数签名只有 `run_id`、`request`，没有 `task_codes`。
- 实际关卡路由为 `POST /api/gates/{gate_id}/resolve`（`api/routes.py:156-169`），请求模型 `GateResolve` 在 38-41，含 `decision`、`payload`、`expected_revision`。
- 当前两路由均有 `DeepSeekRetired` 映射；这与 P1 计划修改的 runtime/routes 形成真实重叠，不能按历史行号或“无下线代码”假定处理。
- 根 Agent 只读复查 `backend/app` 未命中 `execution-grants`、`/bots`、`/skills`、`memberships`、`memory/records`、`discussion-sessions`、`module-acceptances` 或 `/defects` 路由字符串，因此这些 C.5 新域 HTTP 接口当前未见实现。既有 `GET /api/runs/{run_id}/discussion`（`api/routes.py:140-148`）属于 legacy 讨论读取，不等于 C.5.6 的 `discussion-sessions` 新接口。

## P0-T04 · 下线索引与 P1 路径重叠

目标态草稿为 `decommission-target-state.json`，其 `source="p0_index_not_implemented"`、`blocks_all_p1=false`。它只供后续对照，不表示本 P0 实施或验收了下线。

### Active / History 分类

| 项目 | 分类 | 当前证据与含义 |
|---|---|---|
| `/workstation/static-classroom` | **Active（退休说明路由）** | `App.tsx:141` 挂载 `RetiredFeature feature="static-classroom"`；说明文案在 `pages/RetiredFeature.tsx:4-7`，不是静态课堂继续运行 |
| `/deepseek/:id?` | **Active（退休说明路由）** | `App.tsx:142` 挂载 RetiredFeature；`pages/RetiredFeature.tsx:9-16` 明确不发起请求 |
| `StaticClassroomDemo` 原始实现 | **History** | 当前 frontend/src 未见该符号；`docs/StaticClassroomDemo.md:3` 明确“已下线（只读历史）”，README.md:72 仅保留链接 |
| DeepSeek 专用原始外呼叙事/夹具 | **History** | README.md:72 为历史说明；`App.retired.test.tsx:17` 的 DeepSeekProvider 只是 provenance 夹具。未读取旧提交，不推断旧实现原始落点 |
| `DeepSeekRetired` / HTTP 410 | **Active（守卫）** | `app/errors.py:55-72` 定义受控异常；`api/routes.py:58-67` 映射 HTTP 410、`category=deepseek_retired`。Active 指守卫存在，不指专用外呼可用 |
| `provenance.mode=deepseek` 只读兼容 | **Active（只读兼容）** | runtime.py:548-554 只读判断；routes.py:417-437 原样返回 provenance 并设 read_only；App.tsx:104-110 链到只读工作台 |

### 专用创建/重试/继续/恢复外呼入口

下表 Active 均指“当前源码中的退休守卫/只读恢复分支”，不是活跃专用外呼；各项 `outbound_active=false`。

| 入口 | 分类 | 真实文件/行号与当前行为 |
|---|---|---|
| 专用创建（设计导入 `provider=deepseek`） | Active guard | `services/runtime.py:696-710` 在输入校验、设置、写盘、网络前抛 DeepSeekRetired；HTTP 在 routes.py:100-109，兼容 schema 在 schemas/design_input.py:29-33 |
| 任务 retry/resume/skip/force-pass/takeover/submit-takeover | Active guard | `services/runtime.py:1975-1988` 先 `_reject_retired`；HTTP 在 routes.py:186-197。普通 legacy retry 分支仍在 1999-2004 |
| run resume | Active guard | `services/runtime.py:2040-2049`；HTTP 在 routes.py:210-215 |
| 继续生成 PLAN | Active guard | `services/runtime.py:1451-1455`，在 gateway/timeout/event 前拒绝 |
| schedule / 自动循环继续 | Active guard | `services/runtime.py:1543-1548` 与 routes.py:388-394；自动循环跳过退休 run 在 runtime.py:197-214 |
| 进程重启恢复/对账 | Active read-only recovery | `services/runtime.py:344-367` 恢复后标记退休只读错误；208-211 不再自动调度。本阶段未杀进程验证 |
| 统一 gateway / 旧 provider 配置 | Active outbound guard | `services/runtime.py:589-594` 返回 gateway 前拒绝；`llm/gateway.py:140-155` 对未知 kind（含 deepseek）ConfigError，不回退 |

### 与 P0 所述 P1 路径的真实重叠

| P1 路径 | 当前下线相关真实位置 | 协调要求 |
|---|---|---|
| `Test3/backend/app/services/runtime.py` | 554、593、709、1063、1454、1545、1987、2048 等 | **P1 只改 granted_v1 分支，不搭车下线**；保留退休只读与 legacy 行为 |
| `Test3/backend/app/api/routes.py` | 58-67、100-109、156-165、186-197、210-215、388-394 等 | schedule/gates 扩展与退休异常映射直接重叠；须先协调另一下线任务 |

`blocks_all_p1=false`：字符串命中不阻塞 P1，但上述同文件/同函数区域重叠需要协调，不等于可以无视。通用 OpenAI-compatible 模型槽位/base_url、DashScope、scripted、replay 均明确保留，不做 DeepSeek 品牌黑名单。当前保留证据为：`llm/providers.py:149-156` 的 DashScopeProvider/AsyncOpenAI、`llm/gateway.py:147-154` 的 scripted/replay/dashscope 构建分支，以及 providers.py:56、112。

当前源码已经含退休路由和 410 守卫是**基线事实**；本 P0 没有修改它们，也没有运行退休契约测试，故不宣称“下线完成”或“零网络已实测”。

## P0-T05 · 隔离方案与阶段出口

### 最终 dirty 与 worktree 复核

复核时间：`2026-11-19T14:38:18.627941+08:00`。只读重新执行 `git status --porcelain`，完整原始 stdout 为：

```text
?? Test3/docs/plans/
```

因此最终 dirty 原始行数为 **1**；它指向本阶段新建证据目录。T01 初始 `dirty=[]` 与最终一行是两个不同时间点的真实结果，均原样保留，没有把证据文件写成“用户原有脏文件”。最终 branch/HEAD 仍为 `chore/test3-retire-static-classroom-and-deepseek` / `552923d9992a38eb806ff760833bb71ac4b759cf`。

最终 `git worktree list` 仍只有：

```text
/Users/cenghuanxiao/Desktop/HexaGraph  552923d [chore/test3-retire-static-classroom-and-deepseek]
```

未提供 `WORKTREE_PATH`，所以没有执行 `git worktree add`，worktree 数未增加。两份 JSON 在报告写入前由 Python `json.load` 成功解析；`baseline-lock.json` 含 31 个 hooks，目标态文件含正确 source 与 `blocks_all_p1=false`。

### `safe_isolated_baseline=false` 理由（P0 当时结论，已由文末 2026-11-19 隔离补充节取代）

1. T01–T04 证据齐全，且 T01 初始工作区干净，但这只证明当时状态，**不等于当前主工作区已获授权可直接实施 P1**；最终新增的证据目录也没有被当作可覆盖业务文件的许可。
2. 用户没有提供 `WORKTREE_PATH`，P0 明确禁止创建 worktree，因此目前没有具体、已授权的隔离目标路径；在仍需人工提供路径的情况下，保守设布尔值为 false，而不是凭一份计划声称安全。
3. `services/runtime.py` 与 `api/routes.py` 同退休守卫存在真实重叠，当前 branch 又名为 `chore/test3-retire-static-classroom-and-deepseek`；必须与另一下线任务协调写范围或先后顺序，所以 `coordination_required=true`。
4. 现有 `workspace/gitops.py:78-87` 虽提供 create_worktree，但其使用 `-B`，失败清理路径还涉及 remove/prune；P0 未调用，后续必须审查目标路径与清理边界，不能把“有工具函数”等同于“当前树可安全实施”。

### 隔离方案（`worktree_plan=wait_for_human`）

- 等待人工提供明确绝对 `WORKTREE_PATH`，确认目标路径不含会被覆盖的用户内容，并确认下线任务已结束或已划分 runtime/routes 写范围。
- 条件满足后，在指定干净隔离树建立 feature 分支；优先复用经审查的 `workspace/gitops.py` worktree 能力。隔离树建立前，禁止在当前主工作区实施 P1。
- 后续每次执行前重读 `git status --porcelain`；任何用户脏文件均禁止覆盖、stash、reset 或 clean。P1 只修改 granted_v1 所需分支，不搭车修改退休路由/守卫。
- 禁止写入：隔离获批前当前主工作区的 P1 业务代码/构建/锁文件、届时任何用户脏文件、`Test3/data/` 与运行数据、任务书目录，以及任何未由用户明确给出的 worktree 路径。
- 本阶段没有创建 worktree，没有 commit；即使写了隔离计划，也不声称当前工作区可直接实施。

### 四份证据检查

- [x] `Test3/docs/plans/p0-t01-cmd.log`：T01 六条命令的 stdout/stderr/退出码。
- [x] `Test3/docs/plans/baseline-lock.json`：T01 锁、命令、Alembic、31 hooks、出口与最终复核。
- [x] `Test3/docs/plans/decommission-target-state.json`：Active/History、专用入口、overlap、保留能力；未声称已实施。
- [x] `Test3/docs/plans/P0-report.md`：T01–T05 汇总与人审项。

### 不确定项/后续人审注意

- Alembic `0001` 是唯一 versions 文件静态推导的 head，不是 `alembic history` 或数据库查询结果；后者按要求 skipped。
- 退休 410、零网络、重启只读恢复均有当前源码证据，但本阶段未运行测试、未发 HTTP、未操作进程/运行数据，实际行为仍需后续授权验收。
- 未读取旧提交，DeepSeek 原始专用 provider 的历史实现位置不作推断；本报告只区分当前 Active 守卫与文档/夹具 History。
- `app/discussion` 与 gitops 是 already_present；Bots/Memory/Execution/Skills/前端 Bots 页面目录 missing。既有 Discussion 包不表示 C.4/C.5 新域契约已实现。

### 人审必须确认的两项

1. **布尔值**：是否认可 `safe_isolated_baseline=false`、`coordination_required=true`；如需改判，必须在隔离路径与协调条件落实后给出书面豁免/新结论。
2. **隔离方案**：是否认可 `worktree_plan=wait_for_human`，并提供 `WORKTREE_PATH`、明确 runtime/routes 与另一下线任务的协调方式；在此之前不得开始 P1。

P0 完成，停止


---

## P0-T05 补充 · 隔离 worktree 落地与人工确认（2026-11-19T14:50:28+08:00）

> 本节由人工指令触发，**只完成工作区隔离，未实施 P1**，未改任何业务代码。本节结论取代上方 P0 当时的 `safe_isolated_baseline=false` / `worktree_plan=wait_for_human`；上方内容保留为历史记录，不删除、不改写其证据含义。

### 1. 基线复核（只读）

- 复核时间：`2026-11-19T14:48:47+08:00`（UTC `2026-11-19T06:48:47Z`）。
- 原工作区：`/Users/cenghuanxiao/Desktop/HexaGraph`，分支 `chore/test3-retire-static-classroom-and-deepseek`，HEAD `552923d9992a38eb806ff760833bb71ac4b759cf`，HEAD tree `3734070f041dbf8ec868a3f8d7f8e5a1db0dfe73`。
- `git rev-parse refs/remotes/origin/teamwork-001` = `552923d9992a38eb806ff760833bb71ac4b759cf`。
- `git ls-remote origin refs/heads/teamwork-001 refs/heads/main` 实际返回：`teamwork-001` = `552923d9992a38eb806ff760833bb71ac4b759cf`，`main` = `1950b621b1d639b5da717a666ca7a2ecd3247aaa`。远端与本地引用一致，未变化。
- 未提交状态：仅 4 个 untracked P0 证据文件（`P0-report.md`、`baseline-lock.json`、`decommission-target-state.json`、`p0-t01-cmd.log`，均位于 `Test3/docs/plans/`）；`git diff` 与 `git diff --cached` 均为空，即 **0 个 tracked 修改、0 个业务改动**。
- 隔离前 worktree 列表：仅原工作区 1 个。

### 2. 新分支与新 worktree

- 分支：`feat/test3-agent-team-v1`，从 `552923d9992a38eb806ff760833bb71ac4b759cf` 创建；创建前本地与 `origin` 均不存在同名分支。
- worktree：`/Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1`；创建前该路径不存在；未使用 `-B` / `--force`，未删除、重置或强占任何已有路径。
- 实际命令：
  ```text
  git branch feat/test3-agent-team-v1 552923d9992a38eb806ff760833bb71ac4b759cf
  git worktree add /Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1 feat/test3-agent-team-v1
  ```
- 新 worktree 校验：HEAD = `552923d9992a38eb806ff760833bb71ac4b759cf`，tree = `3734070f041dbf8ec868a3f8d7f8e5a1db0dfe73`（与原 HEAD 完全一致），`git status --porcelain` 为空。
- 隔离后 worktree 列表：原工作区 + 新 worktree，共 2 个；原工作区 HEAD、分支与 4 个 untracked 证据文件均未变化。

### 3. 四份证据复制

从原工作区 `Test3/docs/plans/` **复制**（非移动）到新 worktree 同路径；复制前后 SHA-256 一致：

| 文件 | SHA-256（复制前后相同） |
|---|---|
| `P0-report.md` | `7c747639cdbd79048746f804019c95fa2a31e475707870608656544d2e05c450` |
| `baseline-lock.json` | `697d3fc8928c442a9344dbf7ec507b07b50c90a972283b410e883aa5f29c0225` |
| `decommission-target-state.json` | `83db912b938dea2464a46df88ecde4d90fe4d2e3dcbbc5cd9aa1c8670a17f828` |
| `p0-t01-cmd.log` | `fd4490f321b10be9503665f01301553883792daa31c840f6d84a3431bc471c98` |

复制后新 worktree 的 `git status` 仅显示这 4 个 untracked 证据文件；**未 commit**。原工作区四份文件保留原位，未移动。

### 4. 隔离与协作规则（自本轮起生效）

1. 下线任务（静态课堂 / DeepSeek 专用入口退役）继续留在原工作区 `/Users/cenghuanxiao/Desktop/HexaGraph` 的 `chore/test3-retire-static-classroom-and-deepseek` 分支；四份 P0 证据留在原处，不移动、不提交。
2. 新功能（P1 及以后）只在新 worktree `/Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1` 的 `feat/test3-agent-team-v1` 分支开发，不得在原工作区改 P1 业务代码。
3. 共享文件（至少 `Test3/backend/app/services/runtime.py`、`Test3/backend/app/api/routes.py`）后续按函数/符号逐个 `git diff` 核对；**禁止整文件覆盖**（`cp`、`git checkout/restore`、整文件粘贴、`merge -X theirs` 等），**禁止恢复已下线功能**（`StaticClassroomDemo`、静态课堂路由、DeepSeek 专用入口/常量等）。
4. 不运行/停止服务，不读写密钥与运行数据，不 push，不建 PR；P1 的真实 push/PR 仍须单独的 `github_write` 授权。

### 5. `safe_isolated_baseline=true` 判定

- **基线一致**：新 worktree 的 HEAD 与 tree 均与原 `552923d…` 完全一致，且创建后 `git status` 为空。
- **无业务改动**：复制证据前 0 个 tracked 修改；复制后仅 4 个 untracked 文档，无源码/构建/锁文件改动，未 commit。
- **不影响原任务**：原工作区 HEAD、分支、未提交证据、worktree 归属均未变化；新分支与 worktree 独立存在，未占用或清理原路径。
- **路径与分支归属清楚**：目标路径创建前不存在、同名分支创建前不存在；未使用强制参数，未删除/重置任何内容。
- 因此标记 `safe_isolated_baseline=true`。`coordination_required` 仍为 `true`：`runtime.py` / `routes.py` 与下线任务存在真实重叠，后续合并或共享文件修改必须按第 4 节逐函数核对；该布尔值表示“可在隔离树安全开始 P1”，不表示“可整文件合并”。

### 6. 人审状态

- 已由本轮人工指令明确：路径 `/Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1`、分支 `feat/test3-agent-team-v1`、基线 `552923d9992a38eb806ff760833bb71ac4b759cf`。
- 本轮到此停止，等待确认后再进入 P1；未实施 P1。

P0-T05 隔离补充完成，停止

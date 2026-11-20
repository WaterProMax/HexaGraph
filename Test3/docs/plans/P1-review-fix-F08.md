# P1 审查修复 · F-08 执行工具权限交集

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`83ca3ee0ad999cd377a296d362e51d2b9aefdf6f`
- 起点：`bd9a9fdc62f7272d3d396c542f522e6c3f29f3e9`（F-07 记录），核对无差异。
- 范围：只做 F-08；未进入 F-09/P2，未打开执行总闸。
- 结论：granted 命令必须同时通过平台策略、Grant 与物化规格三层；空授权、越权、
  规格不一致都在任何副作用前拒绝。

> 说明：本轮要求的修复任务书 `Test3/docs/plans/P1-review-fix-F08.md` 在起点不存在
> （目录只有 F-01～F-07），本记录依据本轮提示词执行；未虚构已读文件。

## 1. 实际字段与语义

| 层 | 真实对象 | 语义 |
|---|---|---|
| 平台/Bot 策略 | `Workbench._whitelist()` / `_forbidden()`，来源 `config/profiles/python-pytest.yaml` 的 `whitelist_prefixes` / `forbidden_prefixes` | 命令前缀列表 |
| Grant | `ExecutionGrant.allowed_tool_refs` | 命令前缀列表（与平台同一套词汇） |
| 物化规格 | `task["granted_execution"]["command"]`、`["tool_refs"]` | `command` 是完整 argv；`tool_refs` 由 Grant 绑定而来 |

`tool_ref` 不是工具 ID、不是任意标签，而是**命令前缀**：例如 `python -m pytest`。
匹配复用 `app/tools/sandbox.command_allowed`，按 argv 的**完整 token 前缀**比较
（`cmd[:len(parts)] == parts`），没有子串匹配、没有正则、没有通配。

命令映射：

- `command` 来源是 TaskCard 第一条 acceptance command，否则 profile `test_command`；
- `tool_refs` 在 `_granted_spec_for` / `_bind_grant_to_tasks` 中绑定为
  `grant.allowed_tool_refs`；
- wrapper 把 `spec["command"]` 原样交给 worker，worker 不允许再自行改写或回退默认命令。

## 2. 交集计算

新增 `app/execution/tool_policy.py::authorize_granted_command()`，wrapper 与 worker
共用这一处判断，不在两边各维护规则。

顺序（全部在写文件/起进程之前）：

1. `command` 为空 → `spec_command_missing`（409）；不再回退默认 pytest。
2. 传入 `expected_command` 时 argv 必须完全相等 → `spec_command_mismatch`（409）。
3. 清洗 Grant refs：去空白、丢弃空串/非字符串；为空 → `grant_tool_refs_empty`（403）。
4. 清洗 spec refs；为空 → `spec_tool_refs_missing`（409）。
5. `spec_refs ⊄ grant_refs` → `spec_tool_refs_conflict`（409）。
6. 平台：`command_allowed(argv, whitelist, forbidden)` 失败 → `platform_tool_denied`（403）。
7. Grant：`command_allowed(argv, grant_refs)` 失败 → `grant_tool_denied`（403）。
8. 规格：`command_allowed(argv, spec_refs)` 失败 → `spec_tool_denied`（409）。

空 `allowed_tool_refs` 表示“没有授权”，绝不解释为通配；空字符串 ref 也按空处理。

## 3. 生产 wrapper 与直接 worker

| 入口 | 校验位置 | 结果 |
|---|---|---|
| `Workbench.execute_task()` | `_authorize_granted_execution()` 之后、revision/状态/预检之前 | 三类拒绝都在零副作用阶段 |
| `Workbench._execute_granted_task()` | 建 worktree 之前再校验一次 | 防止绕过 wrapper 的调用 |
| `execute_task_granted()` | 最顶部：run/task 绑定 + 三层授权，先于写校验/预检/命令 | 直接调用同样不可绕过 |

worker 新增绑定检查：

- `grant.run_id != run_id` → `grant_binding_mismatch`（409）；
- `task_code not in grant.task_codes` → `scope_mismatch`（409）；
- 通过后才做 WriteSpec 纯校验、隔离预检、staged 写入、命令执行和 evidence 写入。

`execute_task_granted()` 新增 `tool_refs`（物化规格的 tool_refs）与可选
`spec_command`；缺 `tool_refs` 即 `spec_tool_refs_missing`。`whitelist` 参数作为该次
执行的平台策略，wrapper 传 `_whitelist()`。

F-05 的 Grant/PLAN 边界、F-06 的预检失败 BLOCKED、F-07 的安全 evidence 写入均未改动。

## 4. 零副作用证据

拒绝测试用 sentinel 证明以下调用次数为零：

- `create_worktree`（不建 `wt/granted-*`）；
- `execute_task_granted`（wrapper 拒绝时 worker 不被调用）；
- `preflight_isolation` / `run_isolated`（隔离探测与命令均未发生）；
- `create_evidence_dir`（不产生 evidence 目录）；
- 任务 `revision` 不变、状态不变；
- 临时外部哨兵内容不变。

worker 绑定与授权拒绝另有 sentinel：preflight 未被调用，isolation root 保持空目录。

## 5. 测试

新增 `tests/unit/test_p1_f08_tool_authorization.py`（16 条，全部不依赖 Docker）：

| 场景 | 断言 |
|---|---|
| 平台允许、Grant 不允许（wrapper） | `grant_tool_denied` 403；零副作用；哨兵不变 |
| Grant 允许、平台禁止（wrapper，命令为 `python -c`） | `platform_tool_denied` 403；零副作用 |
| 规格 tool_refs 超出 Grant | `spec_tool_refs_conflict` 409 |
| 规格 refs 不覆盖命令 | `spec_tool_denied` 409 |
| Grant refs 为空 | `grant_tool_refs_empty` 403 |
| 物化 command 为空 | `spec_command_missing` 409，不回退默认命令 |
| 三层一致（wrapper） | 到达隔离边界，实际 argv 等于物化 command，evidence 真实落盘 |
| worker run_id 错绑 | `grant_binding_mismatch` 409，preflight 未调用，root 为空 |
| worker task 越界 | `scope_mismatch` 409，同上 |
| worker 平台拒绝 / Grant 拒绝 | `platform_tool_denied` / `grant_tool_denied` 403 |
| worker 空 refs / 空 spec refs / 空 command / command 不符 | 对应 category + 409 |
| worker 三层一致 | 到达隔离边界，argv 与规格一致 |

既有成功用例只补了夹具确需的显式授权（未批量放权）：

- `test_isolated_execute_task.py`：grant `["python -m pytest"]`，命令与 spec refs 对齐；
- `test_p1_rev03_evidence_safety.py` / `test_p1_rev03_isolation_escape.py`：按用例补
  `["python -c"]` 或 `["python -m pytest"]`，并传 `tool_refs`/`whitelist`；
- `test_p1_rev03_isolation_preflight.py`：BLOCKED 用例的 Grant 补上与命令一致的前缀；
- `test_p1_rev01_execution_boundary.py`：grant 连续性用例补 `["python -m pytest"]`。

WriteSpec 绝对路径、`..`、符号链接的既有 `WriteDenied` 断言保持不变。

## 6. 测试命令与结果

定向（本轮新增 + 指定回归）：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_p1_f08_tool_authorization.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/unit/test_p1_rev03_evidence_safety.py \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  tests/unit/test_isolated_execute_task.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  -o addopts='' -m 'not live'
# 1 failed, 58 passed, 2 skipped
```

全量非 live：

```text
.venv/bin/python -m pytest -o addopts='' -m 'not live'
# 8 failed, 328 passed, 2 skipped, 2 deselected in 22.38s
```

相对 F-07（`8 failed, 312 passed, 2 skipped, 2 deselected`）：通过 +16（新增 16 条
F-08 测试），失败集合不变。剩余红灯：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-02 push main / 无授权 commit | 2 | F-09、F-10 |
| REV-03 真实容器逃逸（本机无 Docker） | 1 | F-06 环境限制 |
| REV-06 list 未知仍 create | 2 | F-11 |
| REV-07 否定授权 / 结构化记录 | 2 | F-09 |
| REV-09 revision 恒真断言 | 1 | F-12 |

2 条跳过仍是无后端时的隔离成功路径，未扩大跳过范围；真实容器逃逸用例保持红灯，
未被删除或弱化。

`ruff check`（本轮文件）：通过。`mypy app` 本轮文件无新增报错（仓库既有历史错误与
Makefile 的 `|| true` 不变）。

## 7. F-06 未关闭项

- 有后端时的真实 granted 执行仍未验证（本机 Docker daemon 不可达）；
- 镜像内 pytest/项目依赖、宿主 PATH 覆盖、成功路径断言强度；
- 整棵 worktree 以 rw 挂载给容器，命令级授权不等于容器内文件 scope 限制。

这些仍是开闸前待解决项，本轮未扩展实现、未标为完成。

## 8. 生产总闸仍为 False

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动，生产代码没有
  置 `True` 的路径。
- `tests/e2e/test_granted_v1_sandbox_write.py` 通过：生产 granted 入口仍先返回
  `execution_safety_not_ready`，不会进入工具授权、预检或 worker。
- 只有测试在进程内临时置 `execution_safety_ready = True`。
- 未安装/启动 Docker、未拉镜像、未启动服务、未迁移数据库、未调用真实 API、未 push/PR。

## 9. 修改文件与工作区

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/execution/tool_policy.py` | 新增三层命令授权判断 |
| `Test3/backend/app/execution/isolated.py` | worker 绑定检查与三层授权；移除默认命令回退 |
| `Test3/backend/app/services/runtime.py` | wrapper 在副作用前授权并传递 tool_refs/spec_command |
| `Test3/backend/tests/unit/test_p1_f08_tool_authorization.py` | 新增 16 条回归测试 |
| 既有测试 5 个文件 | 仅为成功夹具补显式工具授权与对齐的 tool_refs |
| `Test3/docs/plans/P1-review-fix-F08.md` | 本记录 |

- 代码/测试提交：`83ca3ee0ad999cd377a296d362e51d2b9aefdf6f`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前后 tracked 工作区均干净；未跟踪项仅原有 `P1-review.md` 与 4 个 P0 文件，未纳入提交。

## 10. 停止点

F-08 完成，等待验收。**不进入 F-09、P2，不打开 `execution_safety_ready`。**
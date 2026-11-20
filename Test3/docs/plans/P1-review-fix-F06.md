# P1 审查修复 · F-06 真实隔离预检（含 F-05 残留入口）

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`d43b6efc33519ce8eee68a8990ef1c2f4c69dc81`
- 起点：`dc3fbc9e883d0925d9a0f0082cf024096afcd9e5`（F-05 记录），HEAD 未变化。
- 范围：只做 F-06 与 F-05 残留入口；未进入 F-07 或 P2。
- 结论：granted 执行只有在 Docker 预检通过时才运行；本机预检失败（daemon 不可达），
  granted 执行在产生任何副作用前返回 BLOCKED。生产执行总闸仍为关闭。

> 说明：本轮要求的修复任务书文件 `Test3/docs/plans/P1-review-fix-F06.md` 在起点提交中不存在
> （`git log` 与目录均无），本记录依据会话中给出的 F-06 约束与通用禁令执行。

## 1. 隔离后端评估与选择

### 1.1 现有 `app/tools/sandbox.py` 是否足够

不足。它提供的是**策略**，不是安全边界：

- `normalize_under/in_write_set` 只约束进程内 WriteSpec 写入；
- `run_command` 只做命令前缀白名单、shell 元字符拒绝、cwd、超时与事后截断；
- 子进程仍在宿主命名空间：可写任意绝对路径、读用户 home/凭据、开网络、访问 socket；
- 没有 CPU 内存限制，也没有把输出字节限制在做隔离层。

因此不能把 `cwd + 命令白名单` 当作 granted 执行的隔离，也不能靠过滤 pytest 源码
或把 worktree 当安全边界来交差。worktree 仍只承担版本隔离。

### 1.2 选定后端

新增 `app/execution/isolation.py`，只支持 **Docker**：

- 仅当 `docker` CLI 存在、daemon **已在本机运行**、镜像**本地已存在**时才可能通过；
- 预检不安装、不启动 Docker，`docker run --pull=never`，不拉镜像、不改宿主配置；
- macOS 的 `sandbox-exec` **未采用**：它无法满足 CPU/内存限制要求，且不能作为跨平台保证；
- 没有 Podman/VM 可用性检测之外的兜底，也没有任何“直接在本机跑测试”的回退。

隔离参数（预检与执行共用同一构造）：

| 约束 | 实现 |
|---|---|
| 网络 | `--network=none` |
| 文件系统 | `--read-only` + `--tmpfs /tmp`；唯一 bind mount 是任务 worktree `-v <wt>:/work:rw` |
| 用户 home / 凭据 | 不挂载 home、不挂 credentials；`HOME=/tmp`，仅传显式允许且名字不含 KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL/AUTH 的环境变量 |
| Docker/SSH socket | 不挂载，预检断言 `/var/run/docker.sock` 不存在 |
| 权限 | `--cap-drop=ALL`、`--security-opt=no-new-privileges`、`--ulimit=nofile=256:256` |
| CPU / 内存 / 进程数 | `--cpus=1`、`--memory=512m`、`--memory-swap=512m`、`--pids-limit=128` |
| 超时 | 宿主侧 `asyncio.wait_for`，超时 kill 进程组并 `docker rm -f` |
| 输出字节 | 宿主侧只保留 256 KiB，超出标记 `truncated`，不落无限日志 |
| 写入范围 | WriteSpec 先做绝对路径/`..`/符号链接与 write_set 纯校验，再写入 `/work` |

### 1.3 预检探测内容

`preflight_isolation()` 在临时目录（`tempfile.mkdtemp`，`finally` 删除）中启动一个
`--rm` 探针容器，要求同时满足：

- `/work` 可写，`/work` 是挂载点；
- 根文件系统只读：`/probe-outside.txt` 写入失败；
- 网络不可达：`1.1.1.1:443` 连接失败；
- 宿主 home 路径在容器内不存在；
- `/var/run/docker.sock` 不存在；
- `HOME=/tmp`。

任一项不满足即 `available=False`，并给出具体失败项。探测结果按进程缓存，测试可
`reset_preflight_cache()`；`TEST3_ISOLATION_BACKEND=none` 可显式关闭（仍只会 fail closed）。

### 1.4 本机预检结果（真实输出）

```text
{'available': False, 'backend': 'docker',
 'reason': 'docker daemon is not reachable; refusing to start it',
 'details': {'error': 'Cannot connect to the Docker daemon at
   unix:///Users/cenghuanxiao/.docker/run/docker.sock. Is the docker daemon running?'},
 'seconds': 0.115}
```

本机 `/usr/local/bin/docker` 存在但 daemon 未运行；按任务书禁止启动 Docker，所以
**本机没有可用隔离后端**。`/usr/bin/sandbox-exec` 存在但未采用（理由见 1.2）。

## 2. 预检失败 → BLOCKED

`Workbench._block_unless_isolated()` 在 `execute_task()` 的授权之后、revision/状态/worktree
之前调用；预检不可用时：

- 返回 `{"kind": "BLOCKED", "isolation_backend": ..., "reason": ...}`；
- 不发 `task.state_changed`、不 bump revision、不建 `wt/granted-*`；
- 发 `task.isolation_blocked` 事件（含 reason/backend/details）；
- 设置 `task["last_error"] = "isolation_preflight_failed"`。

`_execute_granted_task()` 与 `execute_task_granted()` 各自再检查一次（纵深防御）；
后者在写任何文件、起任何进程之前抛 `IsolationUnavailable`，包括 WriteSpec 校验之后。

测试证据（`tests/unit/test_p1_rev03_isolation_preflight.py`）：

| 测试 | 断言 |
|---|---|
| `test_disabled_backend_blocks_granted_execution_without_side_effects` | `TEST3_ISOLATION_BACKEND=none` 时结果为 BLOCKED；状态/revision 不变；`wt/T-01` 与 `wt/granted-T-01` 不存在；命令本应写出的外部文件不存在；worker 未被调用；事件存在 |
| `test_failed_preflight_blocks_before_worktree_and_process` | 探针失败（daemon 不可达）时同上，`last_error=isolation_preflight_failed`，`isolation_backend=docker` |
| `test_worker_rejects_bad_write_specs_before_any_probe` | 绝对路径、`..`、符号链接均 `WriteDenied`，且发生在预检/写文件之前 |
| `test_worker_fails_closed_without_backend` | 无后端时 `IsolationUnavailable`，isolation root 内没有任何新文件 |
| `test_preflight_never_leaves_probe_directories` | 探测后临时目录无残留 |
| `test_container_argv_has_no_host_mounts_and_has_limits` | argv 仅挂载 `/work`，含 `--network=none`、资源上限、`--cap-drop=ALL`；`safe_env` 过滤密钥变量 |

“未启动无隔离 pytest”由三层保证：BLOCKED 发生在 worker 之前；worker 内预检先于命令；
测试用 sentinel 证明 `execute_task_granted` 未被调用。

### 2.1 预检成功路径

`test_escape_is_contained_when_backend_available`：仅在预检通过时运行；测试内 pytest 写
临时“外部”绝对路径，断言文件不存在且退出码非 0。本机无后端，按任务书声明为 **SKIPPED**。

## 3. F-05 残留入口

| 入口 | 处理 | category / HTTP | 零副作用断言 |
|---|---|---|---|
| `accept()` | 在 `_maybe_tasks_complete`/验收命令之前显式拒绝 | `granted_acceptance_disabled` / 409 | 任务状态、revision、gates、`acceptance` artifact 不变；legacy 命令 sentinel 未调用 |
| `control_task("force-pass")` | 在状态/回归之前显式拒绝 | `granted_force_pass_disabled` / 409 | 状态、revision、evidence 不变；`run_command` sentinel 未调用 |
| `_run_regression()` | 直调也在执行命令前拒绝 | `granted_force_pass_disabled` / 409 | 命令 sentinel 未调用 |
| `control_task("takeover")` | 先过 `_require_execution_safety`，再在 `locked_by`/repo/worktree 之前拒绝 | `granted_manual_merge_disabled` / 409 | `locked_by` 未设置、revision 不变、未建 `wt/T-01`；`create_worktree` sentinel 未调用 |
| `submit-takeover` / legacy merge | 保持 F-05 的拒绝 | `granted_manual_merge_disabled` / 409 | 同 F-05 测试 |

新增 4 条测试位于 `tests/unit/test_p1_rev01_execution_boundary.py`。

## 4. 测试命令与结果

F-06 与指定回归：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_tools_llm_agents.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  tests/unit/test_isolated_execute_task.py \
  -o addopts='' -m 'not live'
# 1 failed, 23 passed, 2 skipped
```

唯一红灯是 `test_p1_rev03_isolation_escape.py::test_whitelisted_pytest_cannot_write_absolute_outside_path`
（本机无后端，worker 抛 `IsolationUnavailable`，无法执行逃逸复现）。预检成功时的等价用例见
2.1，按任务书跳过。

F-05 边界与 Grant 回归：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  tests/integration/test_p1_rev08_production_enable_path.py \
  tests/unit/test_schedule_grant_guard.py \
  tests/integration/test_schedule_grant_http.py \
  tests/integration/test_execution_grant_api.py \
  tests/unit/test_grant_policy.py \
  tests/unit/test_grant_refresh.py \
  tests/unit/test_grant_repo.py \
  -o addopts='' -m 'not live'
# 73 passed
```

全量非 live：

```text
.venv/bin/python -m pytest -m 'not live' -o addopts=''
# 8 failed, 303 passed, 2 skipped, 2 deselected in 21.14s
```

相对 F-05（`9 failed, 293 passed, 2 deselected`）：新增 10 条通过、2 条跳过、失败减少 1。
失败减少的 1 条是 **F-07 的 evidence 符号链接测试**，它现在是**空转通过**：worker 在写
evidence 之前就因无后端 fail closed，测试的 `try/except Exception: pass` 吞掉了
`IsolationUnavailable`，并没有证明符号链接写入被修好。F-07 问题仍在，需在有隔离后端的
环境重新验证。

剩余 8 条红灯：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-02 push main / 无授权 commit | 2 | F-09、F-10 |
| REV-03 逃逸复现（无后端，无法执行） | 1 | F-06 环境限制，后端可用时应转绿 |
| REV-06 list 未知仍 create | 2 | F-11 |
| REV-07 否定授权 / 结构化记录 | 2 | F-09 |
| REV-09 revision 恒真断言 | 1 | F-12 |

未删除、未改为跳过、未弱化任何断言。

`ruff check`（本轮改动文件）：通过。`mypy app` 本轮新增文件无报错（仓库既有 47 条
历史错误与本轮无关，Makefile 对 mypy 为 `|| true`）。

## 5. 测试结构调整说明

`tests/unit/test_isolated_execute_task.py` 原先直接用宿主 `python` 子进程验证写集/脱敏：

- 写集与并发隔离改为直接调用 `stage_writes()`（纯文件层），断言不变；
- 脱敏改为 `redact_secrets()/build_evidence()` 直接断言；
- 需要真实执行命令的“失败测试不算成功”改为无后端时跳过，有后端时断言不变。

这是把依赖宿主子进程的用例移到隔离后端下，不是放宽断言。

## 6. 生产总闸仍关闭

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动，生产代码没有
  任何置 `True` 的路径。
- `tests/e2e/test_granted_v1_sandbox_write.py` 仍通过：生产 granted 入口先返回
  `execution_safety_not_ready`，不会走到隔离预检，也不会建 worktree。
- 只有测试在进程内临时置 `execution_safety_ready = True` 来覆盖 BLOCKED/边界逻辑。
- 未启动/停止服务，未迁移用户数据库；所有写入都在 `tmp_path` 或探针临时目录。
- 未安装/启动 Docker，未改宿主配置，未 push/PR/merge。

## 7. 修改文件

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/execution/isolation.py` | 新增 Docker 预检与隔离执行 |
| `Test3/backend/app/execution/isolated.py` | 写集纯校验、预检后执行、隔离证据 |
| `Test3/backend/app/errors.py` | 新增 `IsolationUnavailable` |
| `Test3/backend/app/services/runtime.py` | BLOCKED 门；accept/force-pass/`_run_regression`/takeover 拒绝 |
| `Test3/backend/tests/unit/test_p1_rev03_isolation_preflight.py` | 新增 7 条 F-06 测试 |
| `Test3/backend/tests/unit/test_p1_rev01_execution_boundary.py` | 新增 4 条残留入口测试，continuity 用例注入预检替身 |
| `Test3/backend/tests/unit/test_isolated_execute_task.py` | 写集/脱敏改为纯层断言，命令执行在无后端时跳过 |
| `Test3/docs/plans/P1-review-fix-F06.md` | 本记录 |

## 8. 停止点

F-06 与 F-05 残留入口完成，等待审查。**不进入 F-07、P2 或真实 PR。** F-06 完成不等于
granted 执行已可用：本机没有隔离后端，真实 granted 执行仍为 BLOCKED；F-07 的 evidence
符号链接问题未修复。
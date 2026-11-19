# P1 审查修复 · F-07 evidence 安全写入

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`4ab7cf4be14845b8c4b32a169f45432d3cc46acc`
- 起点：`efc1126b9b78d4aa75e1a1e31b3f3ae98345c020`（F-06 记录），核对无差异。
- 范围：只修 evidence 目录与文件写入及其回归测试；未进入 F-08/P2，未打开执行总闸。
- 结论：evidence 改为系统安全临时目录 + `O_NOFOLLOW|O_EXCL` 相对目录 fd 创建；链接、非普通
  文件、写入失败均明确失败，不返回成功 evidence，不清理外部对象。

> 说明：本轮要求的修复任务书 `Test3/docs/plans/P1-review-fix-F07.md` 在起点不存在
> （目录只有 F-01～F-06），本记录依据本轮提示词执行；未虚构已读文件。

## 1. 根因

`app/execution/isolated.py` 的 evidence 写入：

```python
evidence_dir = isolation_root.parent / f"{isolation_root.name}-evidence"  # 可预测
evidence_dir.mkdir(parents=True, exist_ok=True)                            # 跟随符号链接
log_path.write_text(output, ...)                                           # 跟随符号链接
evidence_path.write_text(json.dumps(evidence), ...)                        # 跟随符号链接
```

- 路径可预测（`<worktree>-evidence`），与任务目录同级；
- `mkdir(exist_ok=True)` 对已存在的符号链接目录不报错，随后两个 `write_text` 都沿链接写到外部；
- 没有排他创建，链接替换（TOCTOU）无法被拒绝；
- 原有回归测试 `except Exception: pass` + 只断言“外部目录为空”，在 F-06 的
  `IsolationUnavailable` 下空转通过，并未执行到写入逻辑。

## 2. 改动与安全写入机制

新增 `app/execution/evidence.py`，所有本链路 evidence 文件（命令输出日志 + evidence JSON）
统一走同一入口。

### 2.1 目录

- `tempfile.mkdtemp(prefix="test3-evidence-")`：系统安全临时接口，名称不可预测；
- 创建后 `chmod 0700` 并 `lstat` 复核：必须是真实目录，不是链接，权限恰为 `0700`；
- 每次调用生成独立目录，不同任务不会复用。

### 2.2 文件

```text
dir_fd = os.open(directory, O_RDONLY|O_DIRECTORY|O_NOFOLLOW)
fd     = os.open(name, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_NONBLOCK, 0600, dir_fd=dir_fd)
fstat(fd) -> 必须是普通文件；fchmod 0600；写满后 fsync
```

- `O_EXCL`：目标名已存在（文件、链接、FIFO、socket）一律失败，不覆盖、不删除；
- `O_NOFOLLOW`：目录或文件在打开瞬间是链接则 `ELOOP`，不跟随；
- `dir_fd`：先打开目录再相对目录创建，没有“先检查路径、后打开”的窗口；
- `O_NONBLOCK`：即使目标被替换成 FIFO，也不会阻塞；
- 写入后 `lstat` 复核 inode 与普通文件类型，防止写完被替换；
- 文件名只允许 `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`，不接受路径分隔符或 `..`。

### 2.3 失败与清理

- 任何目录/文件/类型/写入错误抛 `EvidenceWriteFailed`（`app/errors.py`），
  `execute_task_granted` 不返回 `CommandResult`，上层按失败处理，绝不记录成功；
- 写入失败只清理本次 `create_evidence_dir()` 返回的目录：
  `lstat` 确认是真实目录后，用目录 fd `unlink` 条目（不跟随链接），再 `rmdir`；
  路径若已变成链接或非目录则直接放弃，不删除外部对象。

### 2.4 兼容性

- `CommandResult.log_path` / `evidence_path`、`build_evidence()` 结构、`task.evidence` 事件
  字段保持不变；变化仅是 evidence 目录位置（系统临时目录）与权限。
- “无隔离后端必须 BLOCKED”未改动：预检仍在写文件前，F-06 测试继续通过。

## 3. 攻击面与测试对应

新增 `tests/unit/test_p1_rev03_evidence_safety.py`（9 条，全部不依赖 Docker）：

| 攻击/场景 | 测试 | 证明点 |
|---|---|---|
| 正常写入 | `test_evidence_dir_and_files_are_private` | 读取内容正确；目录 `0700`、文件 `0600` |
| 目录复用/可预测 | `test_evidence_directories_are_unpredictable_per_task` | 两次创建路径不同，均为 `test3-evidence-*` |
| 预置文件符号链接指向外部哨兵 | `test_existing_file_symlink_is_refused_and_target_untouched` | 抛 `EvidenceWriteFailed`；哨兵内容与权限不变；链接仍在（未被删除/覆盖） |
| 目录符号链接重定向 | `test_directory_symlink_redirect_is_refused` | 抛错；外部目录仍为空 |
| 目录打开后、文件打开前换成链接（TOCTOU） | `test_symlink_swap_at_open_time_is_not_followed` | 钩子记录到 `swap.json`（证明进入 open 步骤），随后抛错；外部哨兵不变 |
| 非普通文件 | `test_non_regular_file_is_refused_without_hanging` | FIFO 目标被拒；3 秒内返回，线程未挂起；FIFO 未被替换 |
| 写入失败与清理边界 | `test_failed_write_never_returns_success_and_cleanup_is_local` | 第二个文件失败时抛错；清理只删自己的目录；外部哨兵保留 |
| worker 真实调用写入入口 | `test_worker_writes_evidence_through_safe_writer` | 仅替换 preflight/run；真实落盘；权限、内容、evidence JSON 全部核对 |
| worker 写入失败不返回成功 | `test_worker_raises_instead_of_returning_success_when_evidence_write_fails` | 抛 `EvidenceWriteFailed`；已被调用的 evidence 目录全部清理；外部哨兵不变 |

修正 `tests/unit/test_p1_rev03_isolation_escape.py::test_evidence_symlink_cannot_redirect_writes`：

- 删除 `except Exception: pass`；
- 仅替换容器边界（preflight/run），保留真实 evidence 写入；
- 断言 evidence 文件真实存在、目录 `0700`、文件 `0600`、JSON 内容等于假输出，
  且旧的 `wt-evidence` 链接未被使用、外部哨兵内容与权限不变。
  因此测试确实执行到写入逻辑，而不是被 `IsolationUnavailable` 提前短路。

真实容器逃逸测试 `test_whitelisted_pytest_cannot_write_absolute_outside_path` 保持原样：
本机无 Docker，仍是红灯（环境限制），没有把“pytest 没启动”当作隔离成功。

## 4. 测试命令与结果

新增/修改的 evidence 测试：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev03_evidence_safety.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  -o addopts='' -m 'not live'
# 1 failed, 10 passed
```

唯一红灯是上述真实容器逃逸用例；9 条 evidence 安全测试全部通过并真实落盘。

指定回归组：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  tests/unit/test_isolated_execute_task.py \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  -o addopts='' -m 'not live'
# 1 failed, 33 passed, 2 skipped
```

全量非 live：

```text
.venv/bin/python -m pytest -o addopts='' -m 'not live'
# 8 failed, 312 passed, 2 skipped, 2 deselected in 21.99s
```

与上轮（`8 failed, 303 passed, 2 skipped, 2 deselected`）相比：

- 通过 +9：新增 9 条 evidence 安全测试；
- 失败数不变，集合不变；
- 原先空转通过的 evidence 链接测试现在是真实执行后的通过；
- 2 条跳过仍是无后端时的隔离成功路径（F-06 约定），未扩大跳过范围。

剩余 8 条红灯：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-02 push main / 无授权 commit | 2 | F-09、F-10 |
| REV-03 真实容器逃逸（本机无 Docker） | 1 | F-06 环境限制 |
| REV-06 list 未知仍 create | 2 | F-11 |
| REV-07 否定授权 / 结构化记录 | 2 | F-09 |
| REV-09 revision 恒真断言 | 1 | F-12 |

未删除、未跳过、未弱化任何既有红灯断言。

`ruff check`（本轮文件）：通过。`mypy app` 本轮文件无报错（仓库既有历史错误与 Makefile
的 `|| true` 不变）。

## 5. F-06 仍未关闭的条件

本轮没有验证以下事项，也未把它们标为完成：

- 有隔离后端时的真实 granted 执行（本机 Docker daemon 不可达）；
- 镜像内 pytest/项目依赖是否可用、宿主 PATH 覆盖问题；
- 有后端时成功路径测试的断言强度；
- 整个 worktree 以 rw 挂载给容器，`WriteSpec` 白名单不等于对容器命令的完整 scope 限制。

这些仍是开闸前待解决项。

## 6. 生产总闸仍为 False

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动，生产代码没有置
  `True` 的路径。
- `tests/e2e/test_granted_v1_sandbox_write.py` 通过：granted 入口仍先返回
  `execution_safety_not_ready`，不会进入隔离预检或 evidence 写入。
- 只有测试在进程内临时置 `execution_safety_ready = True`。
- 未安装/启动 Docker、未拉镜像、未启动服务、未迁移数据库、未调用真实 API、未 push/PR。

## 7. 修改文件

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/execution/evidence.py` | 新增安全 evidence 目录/文件写入与清理 |
| `Test3/backend/app/execution/isolated.py` | 日志与 evidence JSON 统一走安全写入；失败清理后上抛 |
| `Test3/backend/app/errors.py` | 新增 `EvidenceWriteFailed` |
| `Test3/backend/tests/unit/test_p1_rev03_evidence_safety.py` | 新增 9 条安全写入测试 |
| `Test3/backend/tests/unit/test_p1_rev03_isolation_escape.py` | 修正 evidence 回归测试，删除异常吞没与空转断言 |
| `Test3/docs/plans/P1-review-fix-F07.md` | 本记录 |

## 8. 提交与工作区

- 代码/测试提交：`4ab7cf4be14845b8c4b32a169f45432d3cc46acc`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前：tracked 干净，未跟踪仅原有 `P1-review.md` 与 4 个 P0 文件；
- 提交后：同样只保留这些既有未跟踪文件，未纳入提交。

## 9. 停止点

F-07 完成，等待验收。**不进入 F-08、P2，不打开 `execution_safety_ready`。**
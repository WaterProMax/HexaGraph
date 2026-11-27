# F-06 隔离收尾：硬链接回写修正

基线 HEAD：`7d8848a1a53d60c8878a2cb2ef8b0b1c6325ae62`，分支 `feat/test3-agent-team-v1`。

## 缺陷

`workspace_scope._write_regular` 对已存在的宿主文件用 `O_TRUNC` 打开，会截断该 inode。
工作树里 `allowed.txt`（在 write_set 内）与 `evil.txt`（不在）若是硬链接，回写 allowed 时
evil 的内容也会被改成 `in-scope-new-content`。

## 修正（仅 `_write_regular`）

在已打开的父目录 fd 上：

1. `os.stat(name, dir_fd=…, follow_symlinks=False)`；不存在则直接新建；
2. 已存在但不是普通文件（含符号链接）→ `WriteDenied`，不写；
3. 是普通文件 → 记下 mode，`os.unlink(name, dir_fd=…)` 只去掉本目录项；
4. `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` 写成新 inode。

父目录逐级 `lstat` 与 `O_NOFOLLOW` 打开父目录保持不变。`_delete_regular`、副本执行、
write_set 过滤、符号链接丢弃、pytest 预检失败、固定容器 PATH、F-05 对
accept / force-pass / takeover 的拒绝均未改动。

## 回归与证据

`tests/unit/test_isolation_scope_writeback.py` 新增：

- `test_in_scope_writeback_does_not_rewrite_out_of_scope_hardlink`：走真实
  `execute_task_granted`（假 `run_isolated` 只改副本）。宿主 allowed/evil 为硬链接、
  `write_set=["allowed.txt"]`；断言 applied 仅 allowed，allowed 为新内容，evil 仍为
  `shared-original`、保留原 inode 且 `st_nlink == 1`，两者 inode 不再相同。
- `test_write_regular_refuses_host_symlink_target`：宿主目标是符号链接时拒绝，外部哨兵不变。

先红后绿：改生产代码前这两条均失败（硬链接用例复现为 evil 被改写；符号链接用例得到
`OSError ELOOP` 而非 `WriteDenied`）；修正后通过，复现不再成立。
原有用例（范围内普通更新、范围外丢弃、符号链接不回写、删除只作用 write_set）继续通过。

## 测试（Test3/backend，`.venv/bin/python -m pytest -o addopts='' -m 'not live'`）

注意：在受限沙箱里跑会因临时目录内 git 不可用而多出 22 条与本改动无关的失败
（改动前后失败集相同）；下列计数为非沙箱本机运行结果。

- 指定 8 个文件：`1 failed, 68 passed, 2 skipped`
- 全量：`1 failed, 414 passed, 2 skipped, 2 deselected`（上一轮记录为 412 passed，+2 为新增回归）

唯一失败：`test_whitelisted_pytest_cannot_write_absolute_outside_path`，错误为
`IsolationUnavailable: docker daemon is not reachable; refusing to start it`。本机无 Docker，
该用例未删除、未 skip、未弱化。两条 skip（`test_isolated_execute_task.py:57`、
`test_p1_rev03_isolation_preflight.py:219`）同样因无后端，**不是已验证**。

## 补充：有 Docker 的验证（同日，用户授权开启 Docker）

Docker Desktop 已在运行；本地没有任何带 pytest 的镜像，且不拉基础镜像。经用户确认，用宿主
`pip download` 取得纯 Python wheel（pytest 9.2.0、pluggy、iniconfig、packaging、pygments、
tomli、exceptiongroup、typing_extensions），在本地已有的 `python:3.10-slim` 上离线 COPY 安装，
构建本地镜像 `test3-isolation-local:pytest`（Dockerfile 在 `/tmp`，不入库），并用
`TEST3_ISOLATION_IMAGE=test3-isolation-local:pytest` 运行；未执行 `docker pull`。
预检仍要求断网、`/work` 为挂载、不暴露 docker.sock、HOME 重定向、pytest 可用，这些均通过。

- 指定 8 个文件：`70 passed, 1 skipped`
- 全量 `-m 'not live'`：`416 passed, 1 skipped, 2 deselected`，0 失败
- `test_whitelisted_pytest_cannot_write_absolute_outside_path` 现在通过（真实容器内逃逸被拦）；
  `test_escape_is_contained_when_backend_available`、`test_failing_offline_test_is_not_success`
  由 skip 变为真实通过。
- 剩下的 1 条 skip（`test_p1_rev03_isolation_preflight.py:200`）是“无后端时必须失败”的用例，
  有后端时按设计跳过（“covered by the escape test”）；无 Docker 的失败路径已在上一轮以
  `IsolationUnavailable` 验证。
- 这只证明本机这一镜像下的隔离行为；`execution_safety_ready` 仍为 False，不因此开闸。
- 未推送 GitHub、未建分支/PR；`p1-pr-record.json` 仍为 `BLOCKED`。

## 状态

- `execution_safety_ready` 仍为 False（`grep "execution_safety_ready = True" app/` 无结果）。
- `p1-pr-record.json` 未改动，仍为 `BLOCKED`、`github_pr_url=null`。
- 未安装、未启动 Docker，未拉镜像；未做任何 GitHub 远程写入；未进入 P2。
- 未纳入提交：`P1-review.md` 与 4 个 P0 文件（仍为未跟踪）。

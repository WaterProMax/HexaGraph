# P1 F-06 隔离遗留 · 最小收尾

- 日期：2026-11-20（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`c6bc9a166b3efaecfcbe70a3dfc17098c4e99459`
- 起点：`609e65eb2606e01cfb9542fc6d811d93a39550d9`（F-12 记录），核对无差异。
- 范围：F-06 遗留的最小代码与离线测试；未进入 P2，未打开总闸，未安装/启动 Docker。
- 结论：容器改为在**一次性副本**上执行，只有 `write_set` 内的普通文件变更被受控回写；
  预检缺 pytest 即失败；容器不再继承宿主 PATH。本机仍无可用后端，真实隔离执行未验证。

> 说明：本轮提示词要求的“修复任务书通用约束与 F-06”文件在仓库中不存在独立新版本；
> 已阅读现有 `P1-review-fix-F06.md` 与 `P1-review-fix-F12.md`，其余按本轮提示词执行。

## 1. 选定的最小范围方案

**容器只拿到 worktree 的一次性副本，宿主工作树从不挂载。**

`app/execution/workspace_scope.py`（新增）：

1. `prepare_worktree_copy(root)`：把 worktree 复制两份到系统临时目录
   （`work/` 给容器、`baseline/` 作为对照），`symlinks=True` 保留链接本身。
2. `collect_changes(copy)`：对两份树按路径比较类型与内容（普通文件 sha256、符号链接目标），
   得到 added / modified / deleted。
3. `apply_changes(copy, changes, write_set)`：
   - 路径必须是相对、无 `..`/`.`/NUL；
   - 必须命中 `write_set`（沿用 `in_write_set` 前缀语义）；
   - 符号链接与非普通文件一律丢弃（`reason=symlink` / `not-a-regular-file`）；
   - 删除只允许普通文件；
   - 回写用父目录 `O_NOFOLLOW` + 最终组件 `O_NOFOLLOW|O_CREAT|O_TRUNC`，父目录逐级
     `lstat` 拒绝链接；删除用目录 fd + `follow_symlinks=False` 校验。
4. `cleanup_worktree_copy` 删除本次临时目录（失败路径在 `finally` 中执行）。

`execute_task_granted` 的流程（`isolated.py` L205-225）：

```text
stage_writes(host root) → prepare_worktree_copy → run_isolated(cwd=copy.work)
→ collect_changes → apply_changes → cleanup
```

写什么：`write_set` 内的普通文件新增/修改/删除。
不写什么：`write_set` 外的一切变更、任何符号链接/类型变化、`write_set=None` 时的全部
容器变更。
验证：`scope.applied` / `scope.discarded` 写入 evidence；测试直接核对宿主文件与哨兵。
失败时：命令异常或 scope 应用失败都会清理副本并上抛；宿主可能已有部分 in-scope 变更，
接口文档与 evidence 记录该边界。

副作用对比：旧实现 `-v <host worktree>:/work:rw`，容器可改整棵树；新实现挂载的是临时副本，
宿主只有在 `apply_changes` 之后才可能变化，且只限 `write_set`。

## 2. 四个已确认问题的改动

### 2.1 预检必须把「镜像缺 pytest」判为失败

- `isolation.py` L91：探针仍执行 `python -m pytest --version` 并写 `pytest_available`；
- `isolation.py` L203-220：`_probe_failures` 新增
  `if not checks.get("pytest_available") → "pytest is not available in the isolation image"`；
- 因此默认 `python:3.11-slim`（`DEFAULT_IMAGE`，L37）即使容器能起，也会预检失败 → BLOCKED。
  镜像与依赖必须由使用者通过 `TEST3_ISOLATION_IMAGE` 预先准备，本轮不 pull。

### 2.2 容器不再继承宿主 PATH

- `isolation.py` L47-49：新增固定容器 `CONTAINER_PATH=/usr/local/bin:/usr/bin:/bin` 与
  `_RESERVED_ENV`（PATH/HOME/TMPDIR/PYTHONPATH/PYTHONHOME/LD_LIBRARY_PATH/VIRTUAL_ENV）；
- `_docker_argv` L273：容器固定 `-e PATH=<CONTAINER_PATH>`；L288 起调用方 env 在写入前
  过滤保留名；
- `safe_env` L296-307：显式排除保留名和密钥类变量，宿主 PATH/HOME 不再进入容器；
- `execute_task_granted` L223：默认 `env_allow` 从 `["PATH"]` 改为 `[]`。

docker CLI 自身仍用 `_docker_cli_env()`（L240-247）获得 `PATH/HOME/DOCKER_*`，但那只是
宿主 docker 进程的环境，不再作为容器内工具来源。

### 2.3 逃逸/成功测试不再「任意非零即通过」

`tests/unit/test_p1_rev03_isolation_preflight.py::test_escape_is_contained_when_backend_available`：

- 保留外部文件不存在与非零退出；
- 新增断言：输出中必须出现 pytest 标识（`pytest` 或 `test session starts`），且
  `No module named pytest` 不算通过——证明 pytest 真的启动，而不是导入失败；
- 本机无后端时该用例仍 skip；`test_whitelisted_pytest_cannot_write_absolute_outside_path`
  未删除、未 skip、未弱化，继续以 `IsolationUnavailable` 失败。

### 2.4 整树 `:rw` 的 scope 约束

见第 1 节：宿主工作树不再挂载，容器只能改副本；回写受 `write_set`、路径与符号链接三重限制。
不使用「事后 git diff 看起来没多改」作为证明。

## 3. 离线测试如何覆盖（无 Docker）

新增 `tests/unit/test_isolation_scope_writeback.py`（6 条，全部真实执行 staging / 复制 /
比较 / 回写，只把 `run_isolated` 换成会改副本的假 runner）：

| 测试 | 证明 |
|---|---|
| `test_in_scope_change_is_applied_and_out_of_scope_discarded` | `allowed.txt` 更新落宿主；`keep.txt`/`evil.txt` 被丢弃；命令 cwd 是副本且结束后已清理 |
| `test_symlink_changes_are_not_written_back` | 副本内把文件换成链接、新增链接：宿主文件不变、链接目标哨兵不变，reason=`symlink` |
| `test_deletions_follow_write_set_only` | write_set 内文件被删除，范围外删除被忽略 |
| `test_container_changes_are_discarded_when_write_set_is_missing` | `write_set=None` 时所有容器变更都不落宿主 |
| `test_scope_copy_collects_added_modified_deleted` | 副本比较能识别三类变更 |
| `test_apply_rejects_unsafe_relative_path` | `../escape.txt` 直接 `WriteDenied` |

`test_p1_rev03_isolation_preflight.py` 新增：

- `test_probe_fails_when_the_image_lacks_pytest`：`pytest_available=False` 必须产生失败项；
- `test_probe_accepts_only_complete_checks`：全部检查通过时无失败项；
- 既有 argv 测试改为断言 `safe_env(["PATH", ...]) == {}`、argv 含固定容器 PATH 且不含宿主 PATH。

`pytest 真正启动` 的断言只在有真实后端的 case 中执行；本机无后端，因此该断言**未被实际
验证**，只完成了代码与 skip 语义。缺依赖的 fail-closed 由 `_probe_failures` 单测锁定。

## 4. F-05 残留入口复盘（未解除任何拒绝）

当前 `runtime.py` 在总闸之外仍显式拒绝：

| 入口 | 位置 | category |
|---|---|---|
| `accept()` | L2940-2949（`_maybe_tasks_complete`/验收命令之前） | `granted_acceptance_disabled` |
| `force-pass` | L2823-2827（状态/回归之前） | `granted_force_pass_disabled` |
| `_run_regression()` | L2726-2733（执行命令前） | `granted_force_pass_disabled` |
| `takeover` | L2816-2821（`locked_by`/worktree 之前） | `granted_manual_merge_disabled` |
| `submit-takeover` | L2903-2909（legacy merge 前） | `granted_manual_merge_disabled` |

结论：

- 这些拒绝独立于 `execution_safety_ready`；将来即使开闸，也不会自动复活 legacy 验收、
  强通或接管合并路径；
- 开闸后 P1 验收路径仍不能用这些入口；granted 的验收/合并若需要，应另开任务，在隔离
  执行与证据链之上设计，而不是解除上述拒绝；
- 本轮未删除、未放宽这些 `GrantRejected`，也未重新接通 `run_command` 或本地自动 merge。

## 5. 测试命令与计数

定向（本轮新增与相关）：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_isolation_scope_writeback.py \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  -o addopts='' -m 'not live'
# 14 passed, 1 skipped
```

相关回归：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_isolated_execute_task.py \
  tests/unit/test_p1_rev03_evidence_safety.py \
  tests/unit/test_p1_f08_tool_authorization.py \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  -o addopts='' -m 'not live'
# 1 failed, 52 passed, 1 skipped
```

全量非 live：

```text
.venv/bin/python -m pytest -o addopts='' -m 'not live'
# 1 failed, 412 passed, 2 skipped, 2 deselected in 21.61s
```

相对 F-12（`1 failed, 404 passed, 2 skipped, 2 deselected`）：通过 +8（6 条 scope 回写
测试 + 2 条预检测试），失败与跳过数量不变。

失败/跳过原因：

- 失败：`test_whitelisted_pytest_cannot_write_absolute_outside_path`——本机 Docker daemon
  不可达，worker 在写 evidence 前抛 `IsolationUnavailable`；未删除、未 skip、未弱化。
- 跳过 2 条：`test_escape_is_contained_when_backend_available`（无后端）与
  `test_failing_offline_test_is_not_success`（无后端，命令执行路径）。
- 全量仍有既有的 aiosqlite `Event loop is closed` 线程警告（`test_execution_grant_api.py`），
  与本轮无关。

`ruff check`（本轮文件）：通过。`mypy app` 中本轮模块无报错。

## 6. 总闸、PR 记录与环境限制

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 保持唯一赋值，
  `grep "execution_safety_ready = True" app/` 无结果；e2e granted 测试继续证明生产入口先返回
  `execution_safety_not_ready`——这只说明闸门关闭，不是隔离验证；
- `Test3/docs/plans/p1-pr-record.json` 未改动，仍为 `status=BLOCKED`、`github_pr_url=null`、
  `push_attempted/pr_attempted=false`；
- 本机预检真实结果仍为 `docker daemon is not reachable`；未安装、未启动 Docker，未 pull 镜像，
  未改宿主配置；
- 未联网、未读令牌/密钥/.env、未动 `Test3/data` 或实际业务库、未迁移数据库、未 push/PR；
- 有后端的真实集成（容器内 pytest/依赖、逃逸、scope 回写）需用户明确允许并准备环境后才能验证。

## 7. 未声称完成

- 未声称真实隔离执行已验证；
- 未声称 `pytest 真正启动` 的断言已在本机通过（skip）；
- 未声称跨机/多进程幂等；
- 未声称 P1 可开闸或真实 PR 已验收；
- 未进入 P2，未实现独立 Bot / Skill 对象。

## 8. 修改文件与工作区

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/execution/workspace_scope.py` | 新增副本、变更收集与受控回写 |
| `Test3/backend/app/execution/isolated.py` | 容器跑副本、写集回写、默认不传 PATH、evidence scope |
| `Test3/backend/app/execution/isolation.py` | pytest 预检失败、固定容器 PATH、保留名过滤 |
| `Test3/backend/tests/unit/test_isolation_scope_writeback.py` | 新增 6 条离线 scope 测试 |
| `Test3/backend/tests/unit/test_p1_rev03_isolation_preflight.py` | 补强逃逸断言、预检与 PATH 测试 |
| `Test3/docs/plans/P1-review-fix-isolation-closeout.md` | 本记录 |

- 代码/测试提交：`c6bc9a166b3efaecfcbe70a3dfc17098c4e99459`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前后 tracked 工作区均干净；未跟踪项仅原有 `P1-review.md` 与 4 个 P0 文件，未纳入提交。

## 9. 停止点

F-06 遗留收尾完成，等待审查。**不进入 P2，不打开 `execution_safety_ready`，不向其它窗口
或终端投递提示词。**
# P1 审查修复 · F-10 Git 写绑定

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`243eb7e1a6beb171b525c91aa698c1b8632a1850`
- 起点：`0313097ddcfa902eb98bb6b9f98445552e5474ad`（F-09 记录），核对无差异。
- 范围：只做 F-10；未进入 F-11/F-12/P2，未打开执行总闸。
- 结论：commit / push / PR 三类写操作都必须同时绑定结构化授权、active ExecutionGrant
  和工作区真实 git 状态；受保护分支、越权 ref、`git add -A`、`--force` 均不可达。

> 说明：本轮要求的修复任务书 `Test3/docs/plans/P1-review-fix-F10.md` 在起点不存在
> （目录只有 F-01～F-09），本记录依据本轮提示词执行；未虚构已读文件。

## 1. 根因

旧 `app/tools/live_git.py`：

- `commit_all()` 不需要授权，直接 `git add -A`；
- `push_once()` 只比较 `feature_branch == base_branch`，因此 `feature_branch="main"` 且 base
  不是 main 时仍会执行 `git push origin HEAD:refs/heads/main`；
- 不校验当前分支、remote URL，也不绑定 ExecutionGrant；`grant_id` 只是可省略的 marker 字段；
- `gh pr list/create` 没有 `--repo owner/repo`。

## 2. 绑定规则

新增统一入口 `_require_binding(auth, grant, run_id, workspace, runner)`，三类写操作在
任何变更命令之前都必须通过。

### 2.1 授权（F-09）

- `auth is None` → `GitHubWriteDenied("missing github_write authorization")`；
- 五个字段必须非空；F-09 解析失败在调用前就已拒绝；
- 不含“逐字段比较”的模糊匹配。

### 2.2 ExecutionGrant

- `grant is None` → 拒绝；
- `grant.run_id != run_id` → 拒绝（run 绑定不能再省略）；
- `grant.status != "active"`（stale/revoked/consumed）→ 拒绝；
- `grant.task_codes` 为空 → 拒绝；
- `grant.repo_owner/repo_name/repo_remote/base_branch/feature_branch` 必须与授权记录逐字段
  相等，否则拒绝；
- marker 的 `grant_id` 现在必须等于当前 `grant.grant_id`，换 Grant 会重新 push（测试覆盖）。

### 2.3 工作区 git 状态

用普通本地 git 命令（不读凭据、不读密钥环境变量）：

```text
git symbolic-ref --short HEAD
git remote get-url <remote>
```

- 当前分支必须等于 `auth.feature_branch`；
- remote URL 解析出的 host 必须是 `github.com`，owner/repo 必须与授权一致
  （大小写不敏感）；支持 `https://github.com/owner/repo(.git)`、`ssh://…` 和
  `git@github.com:owner/repo.git`，其它 host/形状一律拒绝。

### 2.4 受保护分支与 ref

- `feature_branch` 为 `main`/`master` → 拒绝（在读取工作区之前，runner 零调用）；
- `feature_branch == base_branch` → 拒绝；
- 分支名含空白、控制字符或 ` ~^:?*[\` → 拒绝；
- push argv 只由 `HEAD:refs/heads/<feature_branch>` 构造，没有调用方传入 ref 的入口；
- push argv 中不允许 `--force` 或 `+refspec`，代码显式检查并拒绝。

## 3. commit 的明确文件列表

`commit_all()` 被替换为 `commit_files(workspace, files, message, *, auth, grant, run_id, runner)`：

- `files` 必填且非空；
- 拒绝绝对路径、`..`、空串、`.`/`..`、以 `-` 开头、包含 `*?[` 或 NUL 的路径；
- 只执行 `git add -- <explicit paths>`，源码中不再有 `git add -A`；
- commit 与 `rev-parse HEAD` 不变；
- 成功测试在真实本地仓库（从本地裸仓库 clone）中只提交 `a.txt`，断言 `b.txt` 仍未跟踪，
  证明没有全量暂存。

## 4. gh 必须带 --repo

`_existing_pr_url()` 与 `create_pr_idempotent()` 的 argv 都包含：

```text
--repo <owner>/<repo>
```

测试取 `gh pr list` / `gh pr create` 的实际 argv，断言 `--repo` 存在且值等于
`WaterProMax/HexaGraph`。

F-11 的语义**没有**在本轮修复：`list` 非零退出或坏 JSON 时仍返回 `None` 并落下到 create，
`test_p1_rev06_pr_list_unknown.py` 的两条红灯保持为红。

## 5. 拒绝路径零副作用

- 缺授权、缺 Grant、Grant 非 active / run 不匹配 / 字段不一致、受保护分支：在 runner
  任何调用之前拒绝，`ExplodingShell` 证明调用为零；
- 当前分支或 remote URL 不匹配：只发生 `git symbolic-ref` / `git remote get-url` 两个
  只读查询，`git add`、`git push`、`gh pr create` 调用为零；
- 不安全路径：绑定通过后、`git add` 之前拒绝，变更类调用为零；
- 测试只使用临时目录、本地裸仓库和假 runner，没有真实远程副作用。

## 6. 测试命令与结果

先跑 REV-02 与幂等测试：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev02_live_git_binding.py \
  tests/unit/test_live_git_idempotent.py \
  -o addopts='' -m 'not live'
# 35 passed（REV-02 26 + 幂等 9）
```

加入 REV-06 / REV-07：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev02_live_git_binding.py \
  tests/unit/test_live_git_idempotent.py \
  tests/unit/test_p1_rev06_pr_list_unknown.py \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  -o addopts='' -m 'not live'
# 2 failed, 73 passed（2 条均为 F-11 既有红灯）
```

指定回归组：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  tests/unit/test_p1_f08_tool_authorization.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/unit/test_p1_rev03_evidence_safety.py \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  tests/unit/test_isolated_execute_task.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  -o addopts='' -m 'not live'
# 1 failed, 95 passed, 2 skipped
```

全量非 live：

```text
.venv/bin/python -m pytest -o addopts='' -m 'not live'
# 4 failed, 390 passed, 2 skipped, 2 deselected in 22.59s
```

相对 F-09（`6 failed, 362 passed, 2 skipped, 2 deselected`）：

- REV-02 两条红灯转绿，失败 6 → 4；
- 选中用例 370 → 396（REV-02 从 2 扩到 26 条，幂等文件从 7 扩到 9 条）；
- 通过数 362 → 390（新增 26 条 + 原 2 条转绿）；
- 跳过 2 条不变。

剩余 4 条红灯：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-03 真实容器逃逸（本机无 Docker） | 1 | F-06 环境限制 |
| REV-06 list 未知仍 create | 2 | F-11 |
| REV-09 revision 恒真断言 | 1 | F-12 |

未删除、未跳过、未弱化任何后批红灯。全量运行另有一条既有的 aiosqlite
`Event loop is closed` 线程警告（来自 `test_execution_grant_api.py`），不影响结果，
与本轮改动无关。

`ruff check`（本轮文件）：通过。`mypy app` 中 `live_git.py` 无报错（仓库既有历史错误与
Makefile 的 `|| true` 不变）。

## 7. 未使用真实 GitHub 写入

- 测试使用假 runner、本地裸仓库和本地 git 配置；没有网络请求；
- 没有执行真实的 `git push` 或 `gh pr create`；push argv 只被记录；
- 未读取含令牌的环境变量，未调用真实或付费 API；
- 用户当前没有任何真实 GitHub 写授权；本记录中的示例字段不构成授权；
- 未 push、未创建 PR、未 merge/deploy。

## 8. F-06 未关闭项与总闸

- F-06 未关闭项不变：真实后端执行、镜像 pytest/依赖、宿主 PATH、成功路径断言、
  整树 rw 挂载的 scope 限制；
- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动，生产代码没有
  置 `True` 的路径；
- `tests/e2e/test_granted_v1_sandbox_write.py` 继续通过：生产 granted 入口先返回
  `execution_safety_not_ready`；
- 只有测试在进程内临时置 `execution_safety_ready = True`；
- 未安装/启动 Docker、未拉镜像、未启动服务、未迁移数据库。

## 9. 修改文件与工作区

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/tools/live_git.py` | 统一绑定；显式文件提交；受保护 ref；gh `--repo` |
| `Test3/backend/tests/unit/test_p1_rev02_live_git_binding.py` | 26 条绑定/拒绝/成功测试 |
| `Test3/backend/tests/unit/test_live_git_idempotent.py` | 适配新签名，grant_id 幂等测试 |
| `Test3/backend/tests/unit/test_p1_rev06_pr_list_unknown.py` | 适配新签名，红灯语义不变 |
| `Test3/backend/tests/unit/test_p1_rev07_github_auth_negation.py` | 适配新签名，零调用断言不变 |
| `Test3/docs/plans/P1-review-fix-F10.md` | 本记录 |

- 代码/测试提交：`243eb7e1a6beb171b525c91aa698c1b8632a1850`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前后 tracked 工作区均干净；未跟踪项仅原有 `P1-review.md` 与 4 个 P0 文件，未纳入提交。

## 10. 停止点

F-10 完成，等待验收。**不进入 F-11、F-12、P2，不打开 `execution_safety_ready`。**
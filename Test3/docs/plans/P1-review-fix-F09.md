# P1 审查修复 · F-09 Git 写授权结构化

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`26094c295f160ec11b10b32367b61d610f1fc804`
- 起点：`68ced253d963e0a3680bc0390bd5e7d33945d749`（F-08 记录），核对无差异。
- 范围：只修 `github_write` 授权解析；未进入 F-10/F-11/P2，未打开执行总闸。
- 结论：否定句、子串、自然语言、缺字段和非法 verb 都不再产生 `GitHubWriteAuth`；
  只有完整、肯定、字段精确的结构化记录才被接受。

> 说明：本轮要求的修复任务书 `Test3/docs/plans/P1-review-fix-F09.md` 在起点不存在
> （目录只有 F-01～F-08），本记录依据本轮提示词执行；未虚构已读文件。

## 1. 根因

旧解析 `app/execution/github_auth.py`：

```python
if not text or "github_write" not in text:
    return None
fields = dict(_FIELD.findall(text))   # 正则抽 key=value
```

只要文本含 `github_write` 子串并且能抽到五个字段就返回授权，因此

```text
do not authorize github_write owner=expected repo=repo remote=origin \
base_branch=teamwork-001 feature_branch=feat/review
```

会被解析为有效 `GitHubWriteAuth`。自然语言里的“授权”二字、任何包含 `github_write`
的说明文字都可能被误当成授权。

## 2. 新的记录格式

`app/execution/github_auth.py` 只接受两种**逐字段等价**的形状。

### 2.1 JSON 对象（字段集合必须精确相等）

```json
{
  "type": "github_write_grant_v1",
  "verb": "authorize",
  "owner": "example-owner",
  "repo": "example-repo",
  "remote": "origin",
  "base_branch": "teamwork-001",
  "feature_branch": "feat/test3-agent-team-v1",
  "allow_push": true,
  "allow_pr_create": true,
  "allow_merge": false,
  "allow_deploy": false
}
```

### 2.2 规范单行格式

```text
github_write_grant_v1 authorize owner=<owner> repo=<repo> remote=<remote> \
base_branch=<branch> feature_branch=<branch> \
allow_push=true allow_pr_create=true allow_merge=false allow_deploy=false
```

字段顺序、关键字、`true/false` 字面量都必须完全一致（`fullmatch`），前后不能有其它文本。
两种形状都不允许子串、引号包裹的旧 `owner=...` 句子或换行拼接。

## 3. 拒绝规则

| 输入 | 结果 |
|---|---|
| `None`、空字符串/纯空白 | `None`（视为没有授权） |
| 不含 `github_write` 的普通文本 | `None`（没有授权） |
| 含 `github_write` 但不是精确结构（含否定句、自然语言、旧 key=value 句） | `GitHubWriteDenied` |
| 非法 JSON、JSON 非对象 | `GitHubWriteDenied` |
| `type != github_write_grant_v1` | `GitHubWriteDenied` |
| `verb` 不是精确的 `authorize`（`deny`/`revoke`/`do not authorize`/大小写变体） | `GitHubWriteDenied` |
| 缺少任一必填字段、或多出未知字段 | `GitHubWriteDenied` |
| owner/repo/remote/base_branch/feature_branch 为空或含空白/控制字符 | `GitHubWriteDenied` |
| `allow_push`/`allow_pr_create` 不是 `true` 或不是布尔值 | `GitHubWriteDenied` |
| `allow_merge`/`allow_deploy` 不是 `false` 或不是布尔值 | `GitHubWriteDenied` |

`type` 与 `verb` 只做精确比较，不做大小写折叠或“包含”判断；布尔字段用 `type(x) is bool`
校验，字符串 `"true"`、`1` 都会被拒绝。

解析成功返回的 `GitHubWriteAuth` 仍只有 `owner/repo/remote/base_branch/feature_branch`
五个字段，与现有适配器兼容；没有新增任何写入路径或存储。

## 4. 失败即不 push 的证据

`app/tools/live_git.py` 的 `_require_auth()` 在 `auth is None` 时立即抛
`GitHubWriteDenied`，`push_once` / `create_pr_idempotent` 都不会调用 runner。

测试 `test_rejected_records_never_reach_git_or_gh` 对以下输入逐一断言：

- 否定句原文；
- 仅 `"github_write"` 子串；
- `verb="deny"` 的结构化记录；
- 空字符串。

解析结果为 `None` 后，用 `_ExplodingRunner`（任何调用即 `AssertionError`）分别调用
`push_once` 与 `create_pr_idempotent`，两者都抛 `GitHubWriteDenied`，runner 调用列表为空，
marker 文件也不存在。没有真实 `git`/`gh` 进程，没有网络。

## 5. 测试

先改测试后改实现。`tests/unit/test_p1_rev07_github_auth_negation.py` 从 5 个用例项扩展到
37 个（参数化），覆盖：

- 否定句原文 → 无授权；
- 仅子串、旧 key=value 句、中文“授权”句、非法 JSON、错误 type → 拒绝；
- 非授权 verb（deny/revoke/do not authorize/大小写/空）→ 拒绝；
- 五个必填字段逐个缺失、逐个空白 → 拒绝；
- 布尔字段类型错误、`allow_push/allow_pr_create=false`、`allow_merge/allow_deploy=true` → 拒绝；
- 完整 JSON 夹具与规范单行夹具 → 字段逐项相等；
- 未知字段、字段内空白/换行 → 拒绝；
- 解析失败后适配器零调用。

`tests/unit/test_live_git_idempotent.py` 的成功夹具从自然语言改成结构化 JSON，
`owner/repo/remote/base_branch/feature_branch` 断言原文未改；旧句子的失败断言保留。

测试不联网，只使用夹具字符串和假 runner。

## 6. 测试命令与结果

授权相关：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  tests/unit/test_live_git_idempotent.py \
  -o addopts='' -m 'not live'
# 44 passed
```

加入 REV-06 既有用例：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  tests/unit/test_live_git_idempotent.py \
  tests/unit/test_p1_rev06_pr_list_unknown.py \
  -o addopts='' -m 'not live'
# 2 failed, 45 passed（2 条均为 F-11 的既有红灯）
```

指定回归组：

```text
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
# 6 failed, 362 passed, 2 skipped, 2 deselected in 21.33s
```

相对 F-08（`8 failed, 328 passed, 2 skipped, 2 deselected`）：

- REV-07 从 `3 passed + 2 failed` 变为 `37 passed + 0 failed`；
- 总通过 +34，失败 −2；
- 其余红灯集合不变。

剩余 6 条红灯：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-02 push main / 无授权 commit | 2 | F-10 |
| REV-03 真实容器逃逸（本机无 Docker） | 1 | F-06 环境限制 |
| REV-06 list 未知仍 create | 2 | F-11 |
| REV-09 revision 恒真断言 | 1 | F-12 |

2 条跳过仍是无后端时的隔离成功路径，未扩大跳过范围。未删除、未跳过、未弱化任何断言。

`ruff check`（本轮文件）：通过。`mypy app` 中 `github_auth.py` 无报错（仓库既有历史错误
与 Makefile 的 `|| true` 不变）。

## 7. 未使用真实 GitHub 写入

- 测试只解析夹具字符串，runner 是内存假对象；没有任何 `subprocess` 调用 `git push` 或
  `gh pr create`。
- 未读取令牌环境变量，未访问网络，未调用真实或付费 API。
- 未修改 `live_git.py` 的 push/PR 实现，未新增任何远程写入入口。
- 用户当前没有真实 GitHub 写授权；本记录中的 JSON 仅为格式示例，不构成授权。
- 未 push、未创建 PR、未 merge/deploy。

## 8. 本轮未处理

- F-10 的 workspace / 当前分支 / remote URL / ExecutionGrant 绑定未实现；
- `commit_all` 的 `git add -A` 与受保护分支逻辑未改动（仅解析失败时适配器不 push）；
- REV-02 的 live_git 红灯保留给 F-10；
- F-06 未关闭项（真实后端执行、镜像依赖、宿主 PATH、成功路径断言、整树 rw 挂载）不变。

## 9. 生产总闸仍为 False

- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动，生产代码没有
  置 `True` 的路径。
- `tests/e2e/test_granted_v1_sandbox_write.py` 继续通过：生产 granted 入口先返回
  `execution_safety_not_ready`。
- 只有测试在进程内临时置 `execution_safety_ready = True`。
- 未安装/启动 Docker、未拉镜像、未启动服务、未迁移数据库。

## 10. 修改文件与工作区

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/execution/github_auth.py` | 结构化解析与拒绝规则 |
| `Test3/backend/tests/unit/test_p1_rev07_github_auth_negation.py` | 37 条回归测试 |
| `Test3/backend/tests/unit/test_live_git_idempotent.py` | 成功夹具改为结构化 JSON，断言不变 |
| `Test3/docs/plans/P1-review-fix-F09.md` | 本记录 |

- 代码/测试提交：`26094c295f160ec11b10b32367b61d610f1fc804`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前后 tracked 工作区均干净；未跟踪项仅原有 `P1-review.md` 与 4 个 P0 文件，未纳入提交。

## 11. 停止点

F-09 完成，等待验收。**不进入 F-10、F-11、P2，不打开 `execution_safety_ready`。**
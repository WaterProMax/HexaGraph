# P1 审查修复 · F-11 PR 查询三态与 create 禁止

- 日期：2026-11-19（Asia/Shanghai）
- 分支：`feat/test3-agent-team-v1`
- 代码/测试提交：`a57dfe2b12980b7527e17d7b22fe0670a634305e`
- 起点：`753f43e73793b192ef07cbc7ea1a5cf2b4963d39`（F-10 记录），核对无差异。
- 范围：只做 F-11；未进入 F-12/P2，未打开执行总闸。
- 结论：`gh pr list` 的 absent / exists / unknown 三态已经分开；只有 confirmed absent
  才允许 create，unknown 明确失败且 create 调用为零。

> 说明：本轮要求的修复任务书 `Test3/docs/plans/P1-review-fix-F11.md` 在起点不存在
> （目录只有 F-01～F-10），本记录依据本轮提示词执行；未虚构已读文件。

## 1. 根因

旧 `_existing_pr_url()` 在以下情况统一返回 `None`：

- `gh pr list` 退出码非零；
- 输出不是合法 JSON；
- 结构不符合预期。

`create_pr_idempotent()` 把 `None` 一律当成“没有开放 PR”，于是继续调用
`gh pr create`。查询失败可能只是暂时不可用，但也可能已有 PR，继续 create 会产生重复 PR。

## 2. 三态契约

`_existing_pr_url()` 改为返回 `PrLookup`（`PrLookupStatus` = `absent` / `exists` / `unknown`）：

| list 结果 | 状态 | create_pr_idempotent 行为 |
|---|---|---|
| 退出码 0，JSON 数组为空 | `absent` | 允许 `gh pr create` |
| 退出码 0，数组首项是含 `https://…` url 的对象 | `exists(url)` | 直接返回该 URL，不 create |
| 退出码非零 | `unknown(error)` | 抛 `GitHubWriteDenied("cannot determine open pull requests: …")` |
| runner 抛异常/超时 | `unknown(error)` | 同上 |
| 坏 JSON | `unknown(error)` | 同上 |
| 非数组、首项非对象、url 缺失/空/非 https/非字符串 | `unknown(error)` | 同上 |

unknown 的错误文本明确是“无法确定是否存在开放 PR”，不是“已存在”，也不会返回新 URL。

## 3. 禁止 create 的证据

`tests/unit/test_p1_rev06_pr_list_unknown.py`（13 条）：

- 退出码非零 → 抛错，`create_calls == 0`；
- 坏 JSON → 抛错，`create_calls == 0`；
- 六种非预期结构（对象而非数组、字符串数组、空 url、数字 url、`null`、`{}`）→ 抛错，
  `create_calls == 0`；
- runner 抛 `RuntimeError` → 抛 `GitHubWriteDenied`，`create_calls == 0`；
- 空数组 → 正常 create，`create_calls == 1`；
- 已存在 URL → 直接复用，`create_calls == 0`。

所有 case 的 list 结果由测试脚本显式给出，不依赖“假 runner 总是返回期望 URL”。

## 4. 失败对账复用同一 URL

保留并扩展了原对账路径：

- `test_lost_create_response_is_reconciled_without_second_create`：第一次 create 已在远端
  成功但退出非零；第一次调用抛错，第二次 list 看到同一 PR，返回该 URL，`create_calls == 1`；
- `test_create_success_without_url_is_reconciled_on_retry`：第一次 create 退出 0 但输出没有
  https URL；同样第二次 list 复用，`create_calls == 1`。

同进程两次成功路径幂等仍在 `test_create_pr_is_idempotent` 中覆盖：第二次 list 看到已有
PR，直接复用，create 只发生一次。`_PR_LOCK` 继续序列化同进程的 list+create。

**未声称完成跨进程或跨机幂等。** 当前只有一个进程内的线程锁；多进程/多机器重复 create
仍可能发生，这属于后续工作，不在本任务声明范围内。

## 5. 可选 live 测试改为生产 adapter

`tests/e2e/test_live_pr_optional.py` 原先只解析环境变量文本。现在：

1. 从 `TEST3_GITHUB_WRITE_AUTH` 读取结构化 JSON 授权；解析失败或缺失 → `pytest.skip`；
2. 无授权时不创建 Grant，也不调用任何写入；
3. 有夹具授权时构造 matching active `ExecutionGrant`，调用生产
   `push_once` / `create_pr_idempotent`；
4. 所有 git/gh 调用都走 `FakeRunner`（内存假 runner），即使误加 `-m live` 也不会访问真实
   GitHub；
5. 断言 push 只指向 feature ref、不含 base/`--force`，gh list/create 都带
   `--repo owner/repo`，marker 记录 `grant_id`。

默认 `addopts = -q -m 'not live'` 不会选择该用例。单独验证：

```text
env -u TEST3_GITHUB_WRITE_AUTH .venv/bin/python -m pytest \
  tests/e2e/test_live_pr_optional.py -o addopts='' -q
# 1 skipped
```

skip 只证明“无授权不写”，不作为真实 PR 达标记录；`p1-pr-record.json` 未改动。

## 6. 测试命令与结果

先跑 F-11 与幂等：

```text
cd Test3/backend
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev06_pr_list_unknown.py \
  tests/unit/test_live_git_idempotent.py \
  -o addopts='' -m 'not live'
# 22 passed
```

指定回归组：

```text
.venv/bin/python -m pytest \
  tests/unit/test_p1_rev02_live_git_binding.py \
  tests/unit/test_p1_rev07_github_auth_negation.py \
  tests/unit/test_p1_f08_tool_authorization.py \
  tests/unit/test_p1_rev03_isolation_escape.py \
  tests/unit/test_p1_rev01_execution_boundary.py \
  tests/unit/test_p1_rev03_evidence_safety.py \
  tests/unit/test_p1_rev03_isolation_preflight.py \
  tests/unit/test_isolated_execute_task.py \
  tests/e2e/test_granted_v1_sandbox_write.py \
  -o addopts='' -m 'not live'
# 1 failed, 121 passed, 2 skipped
```

全量非 live：

```text
.venv/bin/python -m pytest -o addopts='' -m 'not live'
# 2 failed, 402 passed, 2 skipped, 2 deselected in 22.79s
```

相对 F-10（`4 failed, 390 passed, 2 skipped, 2 deselected`）：

- REV-06 两条红灯转绿，失败 4 → 2；
- 选中用例 396 → 406（REV-06 从 3 条扩到 13 条，新增 10 条）；
- 通过数 390 → 402（新增 10 条 + 原 2 条转绿）；
- 跳过 2 条不变。

剩余 2 条红灯：

| 失败项 | 数量 | 归属 |
|---|---:|---|
| REV-03 真实容器逃逸（本机无 Docker） | 1 | F-06 环境限制 |
| REV-09 revision 恒真断言 | 1 | F-12 |

未删除、未改成跳过、未弱化任何后批红灯；F-10 的绑定、受保护分支、显式文件提交与
`gh --repo` 测试全部保持通过。全量运行仍有既有的 aiosqlite `Event loop is closed`
线程警告（来自 `test_execution_grant_api.py`），不影响结果，与本轮改动无关。

`ruff check`（本轮文件）：通过。`mypy app` 中 `live_git.py` 无报错。

## 7. 未使用真实 GitHub 写入 / 未打开总闸

- 测试只用假 runner 和临时目录，没有网络请求，没有真实 `git push` / `gh pr create`；
- 未读取含令牌的环境变量去访问 GitHub；未调用真实或付费 API；
- 用户当前没有任何真实 GitHub 写授权；本记录与任务书里的 JSON 字段都不构成授权；
- 未 push、未创建 PR、未 merge/deploy；
- `app/services/runtime.py` 中 `self.execution_safety_ready = False` 未改动，生产代码没有
  置 `True` 的路径；`tests/e2e/test_granted_v1_sandbox_write.py` 继续验证生产 granted 入口
  先返回 `execution_safety_not_ready`；
- F-06 未关闭项不变（真实后端执行、镜像依赖、宿主 PATH、成功路径断言、整树 rw 挂载）。

## 8. 修改文件与工作区

| 文件 | 变更 |
|---|---|
| `Test3/backend/app/tools/live_git.py` | PR 查询三态；unknown 禁止 create；保留失败对账 |
| `Test3/backend/tests/unit/test_p1_rev06_pr_list_unknown.py` | 13 条三态/零 create 测试 |
| `Test3/backend/tests/e2e/test_live_pr_optional.py` | 走生产 adapter + 假 runner，无授权 skip |
| `Test3/docs/plans/P1-review-fix-F11.md` | 本记录 |

- 代码/测试提交：`a57dfe2b12980b7527e17d7b22fe0670a634305e`
- 记录提交：本文件提交（见 `git log -1`）
- 提交前后 tracked 工作区均干净；未跟踪项仅原有 `P1-review.md` 与 4 个 P0 文件，未纳入提交。

## 9. 停止点

F-11 完成，等待验收。**不进入 F-12、P2，不打开 `execution_safety_ready`。**
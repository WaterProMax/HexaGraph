# P1 审查报告

## 1. 结论与审查边界

- 审查基线：`552923d9992a38eb806ff760833bb71ac4b759cf`
- 审查 HEAD：`520b15c102ee3f4674f61977cd766c14b84f6fd3`
- 范围：上述基线到 HEAD 的完整 diff，共 33 个文件、2730 行新增、11 行删除；只审查 P1，未进入 P2。
- 操作边界：未修改业务代码、未 push、未创建 PR、未调用真实模型。复现均使用临时目录、scripted provider、sentinel 或假 runner；没有执行真实 GitHub 写操作。
- 工作区原有 4 个未跟踪的 P0/基线文件不属于该 diff，未修改。

**结论：发现 9 项问题，不建议据此判定 P1 通过。** 其中 2 项严重、3 项高、3 项中、1 项低。完整非 live 测试虽然为 `250 passed, 2 deselected`，但现有测试没有覆盖下述已复现的授权绕过、隔离逃逸、恢复 fail-open 和迁移冲突。

| ID | 严重程度 | 问题 |
|---|---|---|
| P1-REV-01 | 严重 | Grant 未位于真实执行边界；无授权回退、retry/递归/takeover 及越权执行均可绕过 |
| P1-REV-02 | 严重 | Git 适配器允许 push main，且未绑定实际仓库、当前分支或 ExecutionGrant |
| P1-REV-03 | 高 | 白名单测试进程可写出隔离区；evidence 符号链接可重定向写出；工具授权未生效 |
| P1-REV-04 | 高 | 重启及 snapshot 损坏恢复会把 granted run 降为 legacy，形成恢复后的 Grant 绕过 |
| P1-REV-05 | 高 | Workbench `create_all()` 与 Alembic 版本状态脱节，既有 0001 数据库无法继续升级 |
| P1-REV-06 | 中 | PR 查询失败会继续 create；失败后重试未纳入仓库测试，所谓 live 测试不调用 PR 生产路径 |
| P1-REV-07 | 中 | GitHub 授权解析接受否定语义文本，不能证明存在明确授权 |
| P1-REV-08 | 中 | granted profile 与执行计划没有生产启用来源，测试只能借助 internal/test fixture 建立场景 |
| P1-REV-09 | 低 | revision 测试含本地变量恒真断言，部分生产路径证据依赖假 `execute_task` |

---

## 2. 详细发现

### P1-REV-01 · 严重 · Grant 未位于真实执行边界，多个生产入口可绕过

**位置**

- [runtime.py:1694-1700](Test3/backend/app/services/runtime.py#L1694-L1700)：只有 `schedule_once()` 调用 `_granted_scope()`。
- [runtime.py:1753-1828](Test3/backend/app/services/runtime.py#L1753-L1828)：`execute_task()` 自身不校验 Grant；没有 `granted_execution` 字典时落入 legacy agent、提交、评审和 merge 路径。
- [runtime.py:1839-1842](Test3/backend/app/services/runtime.py#L1839-L1842)：granted worker 只判断“是否存在 grant”，未校验任务范围、baseline 或 active/stale/revoked/consumed 状态。
- [runtime.py:1971-1974](Test3/backend/app/services/runtime.py#L1971-L1974)：legacy 成功路径会执行本地自动 merge。
- [runtime.py:2077-2105](Test3/backend/app/services/runtime.py#L2077-L2105)：缺陷修复可直接递归调用 `execute_task()`，不再经过调度守卫。
- [routes.py:195-211](Test3/backend/app/api/routes.py#L195-L211) 与 [runtime.py:2214-2219](Test3/backend/app/services/runtime.py#L2214-L2219)：HTTP task retry 直接重新执行，不经过 `schedule_once()`。
- [runtime.py:2279-2291](Test3/backend/app/services/runtime.py#L2279-L2291)：takeover submit 直接进入 `_accept_review_merge()`。
- [runtime.py:1604-1622](Test3/backend/app/services/runtime.py#L1604-L1622)：生产任务物化不会生成 `granted_execution`；全仓生产代码只读取该字段，赋值点仅在测试中。

**问题与影响**

`_granted_scope()` 是调度器前置检查，不是执行边界检查，因此不能覆盖所有 granted 执行入口：

1. `granted_v1` 任务没有 `granted_execution` 时，即使没有 Grant，也会进入 legacy `run_tool_agent()` 路径；正常生产物化的任务恰恰没有该字段。
2. 即使进入 `_execute_granted_task()`，直接执行、retry 等入口也只复用“最新 active；没有 active 则最新任意状态”的 grant，不重新检查当前任务是否属于 `task_codes`，也不检查 baseline 和 stale/revoked/consumed。
3. retry、缺陷递归和 takeover 都是生产可达路径，因此这不是仅限测试直接调用内部方法的问题。
4. 落入 legacy 路径后，还可能执行本地提交及自动 merge；扫描 `live_git.py` 不含 merge/deploy 字符串不能防止这条路径。

**离线复现证据**

案例 A：profile 为 `granted_v1`、无 Grant、无 `granted_execution`，以 sentinel 替换模型 agent 后调用生产 `execute_task()`。没有抛出 `GrantRejected`，sentinel 被实际到达；未调用真实模型：

```json
{"case":"granted_without_grant_or_spec","sentinel_calls":["legacy-model-tool-agent","legacy-model-tool-agent"],"result_kind":"任务描述问题"}
```

案例 B：Grant 仅授权 `T-01`，将 `T-02` 置为可 retry 状态，调用生产 `control_task(..., "T-02", "retry", ...)`。命令仅为临时 worktree 中的离线 pytest；越权任务实际完成，且证据错挂在 `T-01`-only grant 上：

```json
{"case":"retry_outside_grant_scope","grant_tasks":["T-01"],"retried_task":"T-02","result_kind":"done","result_state":"done","evidence_grant":"G-T01-only"}
```

**现有测试为何未捕获**

- [test_schedule_grant_guard.py:83-99](Test3/backend/tests/unit/test_schedule_grant_guard.py#L83-L99) 和 [test_schedule_grant_http.py:72-79](Test3/backend/tests/integration/test_schedule_grant_http.py#L72-L79) 都用假函数替换 `execute_task`，只验证调度筛选，不验证真实执行边界。
- [test_granted_v1_sandbox_write.py:78-115](Test3/backend/tests/e2e/test_granted_v1_sandbox_write.py#L78-L115) 直接调用生产 worker 是有效覆盖，但先手工注入了生产不会生成的 `granted_execution`，且没有无 Grant、越权、stale/revoked、retry 或 takeover 负路径。
- [test_live_git_idempotent.py:98-101](Test3/backend/tests/unit/test_live_git_idempotent.py#L98-L101) 只扫描适配器源码字符串，无法发现 granted 任务进入 [runtime.py:1971-1974](Test3/backend/app/services/runtime.py#L1971-L1974) 的真实 merge。

### P1-REV-02 · 严重 · Git 适配器允许 push main，且未绑定仓库、分支与 Grant

**位置**

- [live_git.py:42-53](Test3/backend/app/tools/live_git.py#L42-L53)：`commit_all()` 不接收任何授权对象，可在调用方给出的任意 workspace 当前分支提交。
- [live_git.py:69-110](Test3/backend/app/tools/live_git.py#L69-L110)：push 只比较 feature 与 base 是否相同；不拒绝 main，不核对当前分支、remote URL 或 ExecutionGrant。
- [live_git.py:113-166](Test3/backend/app/tools/live_git.py#L113-L166)：PR list/create 未指定 `--repo owner/repo`，目标取决于 workspace 当前仓库。
- [github_auth.py:19-41](Test3/backend/app/execution/github_auth.py#L19-L41)：owner/repo 被解析后没有参与后续 Git/GitHub 操作；授权对象也没有 grant/run 绑定。

**问题与影响**

- `feature_branch="main"`、`base_branch="teamwork-001"` 会通过全部现有防护并生成 `HEAD:refs/heads/main`。
- `grant_id` 只是可省略的 marker 元数据，不会查询或验证对应 ExecutionGrant、状态、run、任务范围或 repo 字段。
- 同一授权对象可对任意调用方提供的 workspace/remote 操作；当前分支也不必是授权 feature 分支。
- `commit_all()` 完全无授权入口，现有测试甚至没有导入或覆盖它。

**假 runner 复现，无真实 push**

```text
push_main_accepted= True
calls= [['git', 'rev-parse', 'HEAD'], ['git', 'push', 'origin', 'HEAD:refs/heads/main']]
remote_url_verified= False
current_branch_verified= False
commit_all_signature= (workspace: 'Path', message: 'str', *, runner: 'Runner | None' = None) -> 'str'
commit_calls= [['git', 'add', '-A'], ['git', 'commit', '-m', 'unauthenticated main commit'], ['git', 'rev-parse', 'HEAD']]
```

[test_live_git_idempotent.py:89-95](Test3/backend/tests/unit/test_live_git_idempotent.py#L89-L95) 只断言 argv 不含 `teamwork-001`，没有 main、仓库错绑、当前分支错绑、Grant 错绑或无授权 commit 用例。FakeShell 在 [test_live_git_idempotent.py:27-41](Test3/backend/tests/unit/test_live_git_idempotent.py#L27-L41) 中还硬编码返回预期 GitHub URL，无法证明生产仓库绑定。

### P1-REV-03 · 高 · 测试进程与 evidence 写出均可越过隔离边界，工具授权未生效

**位置**

- [isolated.py:110-149](Test3/backend/app/execution/isolated.py#L110-L149)：Grant 被明确声明为“traceability only”；测试命令直接进入子进程，没有文件系统沙箱。
- [isolated.py:151-174](Test3/backend/app/execution/isolated.py#L151-L174)：evidence 目录、日志和 JSON 写入没有 `normalize_under()` 或符号链接检查。
- [runtime.py:1861-1874](Test3/backend/app/services/runtime.py#L1861-L1874)：生产 wrapper 传全局 profile whitelist，不使用 Grant 的工具授权，且只捕获 `CommandDenied`。
- [execution_grant.py:28-43](Test3/backend/app/schemas/execution_grant.py#L28-L43)：`allowed_tool_refs` 只有 schema/测试数据出现，生产执行没有读取点。

**问题与影响**

1. `normalize_under()` 只保护 worker 自己执行的 `WriteSpec`。白名单内的 pytest 可以运行任意测试代码，测试进程可用绝对路径直接写隔离区外；命令退出码和 evidence 仍会显示成功。
2. evidence 目录位于 worktree 的 predictable sibling。若该目录已是指向外部目录的符号链接，worker 会跟随链接写 `.log` 和 `.json`。
3. `allowed_tool_refs` 不参与命令决策，Grant 中的工具授权语义没有落实。
4. 直接调用 worker 时也不核对 `run_id`、`task_code` 与 Grant 的匹配关系；Workbench 入口的越权复现见 P1-REV-01。

**临时目录复现**

直接 WriteSpec 的三种攻击均被拒绝，说明原有 `normalize_under()` 本身有效：

```json
{"direct_write_cases":{"absolute":"WriteDenied","dotdot":"WriteDenied","symlink":"WriteDenied"}}
```

但预置 `granted-T-01-evidence -> 外部目录` 后，生产 helper 跟随符号链接写出了两个文件：

```json
{"outside_files":["T-01-1795078635585-c481f280.json","T-01-1795078635585-c481f280.log"],"evidence_resolved_inside_outside":true}
```

使用生产同款 `python -m pytest` 白名单，测试代码写一个绝对路径，结果命令成功且外部文件确实存在：

```json
{"command_whitelisted":true,"result_ok":true,"outside_file_exists":true,"outside_content":"escaped"}
```

[test_isolated_execute_task.py:37-111](Test3/backend/tests/unit/test_isolated_execute_task.py#L37-L111) 与 [test_granted_v1_sandbox_write.py:78-115](Test3/backend/tests/e2e/test_granted_v1_sandbox_write.py#L78-L115) 没有绝对路径、`../`、符号链接、evidence 重定向、测试进程副作用、run/task 不匹配或工具授权负路径。通用 [test_tools_llm_agents.py:18-38](Test3/backend/tests/unit/test_tools_llm_agents.py#L18-L38) 只测试 `normalize_under()`，覆盖不到上述两条绕行路径。

### P1-REV-04 · 高 · 重启与损坏恢复将 granted run 降为 legacy，恢复后绕过 Grant

**位置**

- [runtime.py:601-624](Test3/backend/app/services/runtime.py#L601-L624)：profile/hash setter 不持久化 snapshot；`add_grant()` 只提交 SQLite，不保存 run profile。
- [runtime.py:355-391](Test3/backend/app/services/runtime.py#L355-L391)：重启依赖 JSON snapshot/events 恢复 run。
- [runtime.py:433-447](Test3/backend/app/services/runtime.py#L433-L447)：snapshot 损坏时从 events 构造的 skeleton 将 artifacts 置空，不重建 profile/hash。
- [run_profile.py:19-21](Test3/backend/app/execution/run_profile.py#L19-L21)：缺失 profile 被解释为 legacy。
- [runtime.py:1665-1666](Test3/backend/app/services/runtime.py#L1665-L1666)：legacy 直接跳过全部 Grant 检查。

**复现证据**

设置 `granted_v1`、写入 Grant 后立即重启：

```json
{"before_restart_profile":"granted_v1","persisted_snapshot_profile":"MISSING"}
{"valid_restart_profile":"legacy","valid_restart_grant_count":1}
```

先生成正确 granted snapshot，再损坏 snapshot 走 events-only 恢复：

```json
{"corrupt_snapshot_recovery_profile":"legacy","recovered_artifacts":{},"recovery_db_grant_count":1}
```

两种情况中 SQLite Grant 都还存在，但决定是否受控的 profile 丢失。后续调度按 legacy 放行，而不是 fail closed。新增测试没有 granted run 的正常重启、损坏 snapshot 恢复或 events-only 恢复用例。

### P1-REV-05 · 高 · Workbench 与 Alembic 双建表路径冲突

**位置**

- [runtime.py:573-585](Test3/backend/app/services/runtime.py#L573-L585)：首次 Grant 使用直接 `create_all()`，不执行 Alembic upgrade/stamp。
- [0002_execution_grants.py:18-26](Test3/backend/alembic/versions/0002_execution_grants.py#L18-L26)：正常 0002 升级会再次创建 grants 表。
- [test_alembic_execution_grants.py:28-47](Test3/backend/tests/integration/test_alembic_execution_grants.py#L28-L47)：只测试纯 Alembic 新库 upgrade/downgrade/upgrade。
- [test_grant_repo.py:31-37](Test3/backend/tests/unit/test_grant_repo.py#L31-L37)：仓库测试只测试纯 `create_all()` 新库。

**既有 0001 数据库复现**

先 Alembic upgrade 到 0001，再让 Workbench 写入一条 Grant，最后执行 `upgrade head`：

```json
{"version_after_workbench":"0001","grants_table_exists":true}
{"upgrade_head":"OperationalError","detail":"(sqlite3.OperationalError) table execution_grants already exists"}
```

另一条“全新库先由 Workbench 使用，再首次运行 Alembic”的路径也复现失败：

```json
{"upgrade_after_runtime":"OperationalError","detail":"(sqlite3.OperationalError) table project already exists"}
```

现有两类测试彼此隔离，未覆盖同一生产数据库在 Workbench 与 Alembic 之间的交接、数据保留或恢复。

### P1-REV-06 · 中 · PR 查询故障被当成“无 PR”，失败后重试没有仓库测试

**位置**

- [live_git.py:113-127](Test3/backend/app/tools/live_git.py#L113-L127)：list 非零或 JSON 解析失败均返回 `None`，与“确定没有 PR”不可区分。
- [live_git.py:130-166](Test3/backend/app/tools/live_git.py#L130-L166)：拿到 `None` 后直接 create。
- [test_live_git_idempotent.py:19-40](Test3/backend/tests/unit/test_live_git_idempotent.py#L19-L40)：FakeShell 的 list/create 永远成功。
- [test_live_git_idempotent.py:63-79](Test3/backend/tests/unit/test_live_git_idempotent.py#L63-L79)：幂等用例只有成功后的第二次调用，没有失败后重试。
- [test_live_pr_optional.py:10-22](Test3/backend/tests/e2e/test_live_pr_optional.py#L10-L22)：即使提供授权，也只解析文本并断言字段，不调用生产 push/PR adapter。

**复现证据**

模拟 list 临时故障且远端可能已有开放 PR，适配器仍尝试 create，并得到“已存在”错误：

```text
result= GitHubWriteDenied gh pr create failed: a pull request already exists
create_attempted_after_unknown_list= True
calls= [gh pr list ..., gh pr create ...]
```

另模拟“远端已创建成功，但第一次 create 响应失败”，第二次调用能通过 list 找回同一 URL，且 create 总次数为 1：

```json
{"first":"GitHubWriteDenied","second":"https://github.com/expected/repo/pull/1","create_calls":1}
```

后一个单场景说明当前实现具备一定恢复能力，但它没有被仓库测试固定；list 失败、create 失败、响应缺 URL、push 失败后重试及多进程并发均没有测试。故“PR 幂等测试包含失败后重试”这一明确要求未满足。

### P1-REV-07 · 中 · 否定语义的 GitHub 授权文本仍被接受

**位置**

- [github_auth.py:15-41](Test3/backend/app/execution/github_auth.py#L15-L41)：只检查文本中是否含有子串 `github_write`，再用正则提取键值，不校验授权语句的肯定语义或精确格式。

**复现证据**

```text
输入：do not authorize github_write owner=expected repo=repo remote=origin base_branch=teamwork-001 feature_branch=feat/review
输出：negated_authorization_accepted= True
```

必填字段存在并不能把否定句变成明确授权。当前应用代码尚未把该 parser 接入真实自动 push/PR 调用，因此本项是适配器授权边界问题，不声称本轮发生了真实远端写入。

### P1-REV-08 · 中 · granted profile 与执行计划没有生产启用来源，端到端场景依赖测试 fixture

**位置**

- [runtime.py:563-570](Test3/backend/app/services/runtime.py#L563-L570)：正常 `create_run()` 不设置 granted profile。
- [runtime.py:601-613](Test3/backend/app/services/runtime.py#L601-L613)：profile/hash setter 明确标注为 internal/test fixture；生产代码没有其他启用调用点。
- [test_execution_grant_api.py:48-54](Test3/backend/tests/integration/test_execution_grant_api.py#L48-L54)：API 测试直接调用 internal setter 制造 granted run。
- [test_granted_v1_sandbox_write.py:43-67](Test3/backend/tests/e2e/test_granted_v1_sandbox_write.py#L43-L67) 与 [test_granted_v1_sandbox_write.py:83-89](Test3/backend/tests/e2e/test_granted_v1_sandbox_write.py#L83-L89)：测试直接设置 profile/hash，并注入生产任务物化不会生成的 `granted_execution`。
- [routes.py:419-430](Test3/backend/app/api/routes.py#L419-L430)：Grant API 只读取 run profile；请求体中的 grant profile 是固定字面值，不会被用来改写 run profile。

**核对结果**

已确认请求中的 `execution_profile="legacy"` 会被 schema 拒绝，未发现新增 HTTP 降级路由；legacy run 也不能通过创建 Grant 自行升级为 granted。因此本项不是“客户端可直接改写 run profile”的绕过。

实际缺口是：正常生产创建流程没有 granted 启用路径，`granted_execution` 也没有生产来源；只有 internal/test setter 和测试注入能建立完整场景。因此现有绿测证明的是“人工布置 granted 状态后的局部函数行为”，不能证明真实生产链路可以进入 granted 模式，更不能证明所有生产任务都会进入受控 worker。该生产可达性缺口同时放大了 P1-REV-01：正常物化任务缺少 `granted_execution`，会落入无 Grant 的 legacy 执行路径。

### P1-REV-09 · 低 · revision 测试含恒真断言，不能单独证明普通进度语义

**位置**

- [test_grant_policy.py:70-79](Test3/backend/tests/unit/test_grant_policy.py#L70-L79)
- [test_grant_refresh.py:39-44](Test3/backend/tests/unit/test_grant_refresh.py#L39-L44)

两处均先把局部变量 `run_revision` 赋为 5，再断言它仍为 5，被测函数从未接收或有机会修改该变量：

```python
run_revision = 5
assert grant_stale_reason(...) is None
assert run_revision == 5
```

该断言恒真，不构成“普通进度不会使授权失效”的行为证据。签名不包含 revision 的断言是有效的；[test_schedule_grant_http.py:140-149](Test3/backend/tests/integration/test_schedule_grant_http.py#L140-L149) 的 HTTP revision bump 也覆盖了一部分守卫语义，但它使用假 `execute_task`，不能替代 P1-REV-01 所需的真实执行边界测试。

---

## 3. 已验证有效或未发现回归的部分

1. **Grant 纯策略本身**：[grant_policy.py:19-42](Test3/backend/app/execution/grant_policy.py#L19-L42) 对授权子集、超集、空请求、revoked/consumed 和 baseline 比较的逻辑与预期一致；revision 不是输入。问题出在执行入口未统一调用它。
2. **直接 WriteSpec 路径**：绝对路径、`../` 和既有符号链接三种临时目录复现均为 `WriteDenied`；没有发现 `normalize_under()` 本身的直接回归。证据写出与测试子进程不在该保护范围内。
3. **profile 降级路由**：未发现新增 HTTP downgrade；legacy run 创建 Grant 返回 403，schema 也拒绝请求中的 `execution_profile="legacy"`。
4. **真实远端副作用**：`live_git.py` 没有 merge/deploy helper，应用生产代码也没有自动调用 push/PR adapter 的接线；本轮未执行真实 push/PR。此结论不排除 P1-REV-01 的 legacy 本地自动 merge。
5. **PR 的一个失败恢复场景**：模拟远端已创建但首次响应失败后，重试可找回原 URL；但该行为未进入仓库测试，且 list 故障仍会触发 create。
6. **下线守卫 diff**：基线到 HEAD 未修改前端退休页面、DeepSeek 退休测试、`app/llm`、`workspace/gitops.py` 或 `tools/sandbox.py`；[runtime.py:1694-1697](Test3/backend/app/services/runtime.py#L1694-L1697) 仍在 Grant 检查前先执行退休拒绝。
7. **既有测试回归**：legacy/退休相关定向测试及完整非 live 后端套件均通过，但这些绿测不覆盖本报告的攻击与故障路径。

## 4. 实际执行的测试

在 `Test3/backend` 中执行，均未选择 live 测试：

```text
P1 相关 12 个测试文件：
59 passed，exit 0

.venv/bin/python -m pytest tests/e2e/test_deepseek_retired.py \
  tests/e2e/test_m1_study_room.py tests/e2e/test_schedule_dependencies.py -q
15 passed，exit 0

.venv/bin/python -m pytest -m 'not live'
250 passed, 2 deselected in 18.93s，exit 0
```

补充说明：

- 第一次 `uv run` 因沙箱无法读取用户 uv cache 而以退出码 2 结束，未运行测试；随后仅对同一离线测试命令开放缓存读取后成功。
- 复现脚本没有写入仓库；所有文件系统逃逸样例均限制在临时目录及其外部临时文件。
- Git/GitHub 复现全部使用假 runner，只记录 argv 或模拟响应；没有真实 push、PR、merge 或 deploy。
- Grant/legacy 回退复现使用 sentinel 取代模型 agent；没有真实模型调用。

## 5. 完整 diff 审查范围

| 类别 | 数量 | 审查内容 |
|---|---:|---|
| 修改的生产文件 | 5 | routes、errors、runtime、models、main |
| 新增生产/迁移文件 | 11 | 0002 migration、execution 包 8 个文件、grant schema、live_git |
| 测试与 OpenAPI 快照 | 14 | P1 unit/integration/e2e、optional live 文件及 snapshot |
| 阶段文档/记录 | 3 | P1-report、evidence sample、PR BLOCKED record |

已逐项核对用户指定的六条重点：服务端 profile 与 Grant 入口、授权子集/越权/普通进度、隔离写入与测试命令、Git 仓库/分支/授权及 PR 幂等、SQLite 迁移恢复与 legacy/下线守卫、测试生产路径和断言有效性。

## 6. 未验证项

1. 未执行真实 GitHub 仓库绑定、push、PR、merge/deploy，也未验证真实远端成功后本地失败、多进程并发幂等；真实 PR 记录仍为 BLOCKED。
2. 未调用真实模型；legacy agent 绕过由生产方法加 sentinel 证明，不涉及真实供应商请求或计费行为。
3. 未验证多个授权任务经真实 worker 连续执行完整 DAG；当前连续调度证据主要使用假 `execute_task`，且 `granted_execution` 没有生产来源。
4. 未验证 granted profile 的真实服务端启用流程，因为当前生产代码没有 internal/test setter 之外的启用调用点。
5. 未覆盖符号链接并发替换等 TOCTOU、多进程 SQLite 写入/崩溃恢复、真实运行数据备份恢复或迁移数据保留；本项仅复现 schema/version 冲突与 profile 恢复 fail-open。
6. 未做浏览器端 UI 回归；前端无本 diff，结论仅基于 diff 与后端退休/legacy 测试。
7. 未审查或进入 P2，未对任何问题实施修复。

---

审查完成，停止于本报告。

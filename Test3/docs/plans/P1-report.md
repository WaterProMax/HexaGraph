# P1 执行授权、隔离执行与真实 PR · 阶段报告

- 基线：`552923d9992a38eb806ff760833bb71ac4b759cf`（`feat/test3-agent-team-v1`）
- 隔离树：`/Users/cenghuanxiao/Desktop/HexaGraph-Test3-agent-v1`
- 运行方式：本地 `uv run pytest` + scripted/假适配器；未 push、未创建 PR、未调用真实/付费模型、未启动或操作现有服务。
- 本报告只登记 P1 本地可执行部分；真实 GitHub 写操作标记 BLOCKED。

## P1-T01 · grant_stale_reason 纯函数

新增：

- `Test3/backend/app/execution/__init__.py`
- `Test3/backend/app/execution/grant_policy.py`
- `Test3/backend/tests/unit/test_grant_policy.py`

实现严格按 contracts.md C.3.2：撤销/消费优先，空请求 → `empty_request`，超集 → `scope_mismatch`，逐 key 比较基线 → `baseline_changed:<key>`；函数不接收也不读取 `run.revision` / `task.revision`。子集合法，不因“只执行授权子集”判 stale。

实际命令与结果：

```text
$ cd Test3/backend && uv run pytest tests/unit/test_grant_policy.py -v
collected 10 items
tests/unit/test_grant_policy.py ..........  [100%]
10 passed in 0.01s
```

签名核验（测试内 `inspect.signature` 断言）：

```text
grant, approved_baseline_hashes, requested_task_codes
```

并发：纯函数无共享可变状态，按任务卡不写并发用例。权限：纯函数无调用者身份，超集用例覆盖范围越权。无网络访问。
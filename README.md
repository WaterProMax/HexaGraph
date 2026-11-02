# HexaGraph
HexaGraph: 6-person Multi-Agent Orchestration powered by LangGraph

## 编排 demo（Issue #4）

一个可跑的六人编排骨架：需求官 → 契约官 → 契约门禁 → 实现官 → 验证官 → 评审官，
带两条条件回流（门禁打回契约官、评审打回实现官）。

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m orchestration.cli
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest orchestration/tests -q
```

- 架构理解：[`Architecture.md`](Architecture.md)
- 开发文档：[`docs/dev-doc.md`](docs/dev-doc.md)
- 契约：[`docs/contract.md`](docs/contract.md)
- 仓库规则：[`AGENTS.md`](AGENTS.md)

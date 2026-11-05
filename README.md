# HexaGraph
HexaGraph: 6-person Multi-Agent Orchestration powered by LangGraph

## 工作流设计

这一分支放「从想法到交付」的完整工作流，实现时以这些文件为准。

| 文件 | 内容 |
|---|---|
| [Design.md](Design.md) | 流程规则：需求阶段、设计规格、任务分解、编排与执行、控制台、变更、环境监听、模型槽位 |
| [Architecture.md](Architecture.md) | 系统架构：模块、数据、接口、目录 |
| [ImplementationPlan.md](ImplementationPlan.md) | 分阶段实施计划（P00–P17）、验收项、百炼模型配置 |
| [第一组--多体讨论工作流设计.docx](第一组--多体讨论工作流设计.docx) | Design.md 的 Word 版 |
| [figures/](figures/) | 流程图源文件和图片 |
| [build_docx.py](build_docx.py) | 由 Design.md 重新生成 docx |

执行阶段的默认上限：任务并发 6，每个任务最多修复 6 轮，每点 150 万令牌，P1 验收通过线 90%。数值在 Design.md 第 15.10、17.4 节，配置键在 ImplementationPlan.md 附录 D。


"""Deterministic document checks. Design.md 6–8, 13–14."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable

from app.schemas.common import FIBONACCI
from app.schemas.docs import (
    DesignDoc,
    Issue,
    ProposalDoc,
    ReviewOpinion,
    ReviewSheet,
    SpecDoc,
    TaskGraph,
)

PROPOSAL_CHAPTERS = (
    "电梯演讲",
    "NABCD",
    "做什么",
    "不做什么",
    "大致怎么实现",
    "功能清单",
    "风险与待定",
    "估算",
)
SPEC_CHAPTERS = ("用户与场景", "功能", "非功能需求", "还没定的问题", "附录")
DESIGN_CHAPTERS = ("概述", "模块", "接口", "数据", "决策", "预案", "附录")


def review_pass(sheets: Iterable[ReviewSheet]) -> bool:
    scores = [sheet.score for sheet in sheets]
    if not scores:
        return False
    if sum(scores) / len(scores) < 3.5:
        return False
    if any(score < 3 for score in scores):
        return False
    if any(op.blocking for sheet in sheets for op in sheet.opinions):
        return False
    return True


def route_review(opinions: Iterable[ReviewOpinion], *, returns: int = 0, max_returns: int = 2) -> str:
    items = list(opinions)
    if returns >= max_returns:
        return "停止"
    if any(op.kind == "争议类" for op in items):
        return "步骤1"
    if any(op.kind == "方案类" for op in items):
        return "步骤2"
    if items and all(op.kind == "验证类" for op in items):
        return "我决定"
    return "步骤2"


def route_design_review(opinions: Iterable[ReviewOpinion], *, rewrites: int = 0, max_rewrites: int = 2) -> str:
    items = list(opinions)
    if any(op.kind == "需求类" for op in items):
        return "变更单"
    if any(op.kind == "设计类" for op in items):
        return "停止" if rewrites >= max_rewrites else "重写"
    if any(op.kind == "验证类" for op in items):
        return "探索任务"
    return "通过"


def estimate_rank(points: int) -> int:
    if points not in FIBONACCI:
        raise ValueError(f"points {points} not in Fibonacci subset")
    return FIBONACCI.index(points)


def reconcile_estimates(dev: int, test: int, *, reestimated: bool = False) -> tuple[int, bool, bool]:
    """Return (value, needs_reestimate, disagreed)."""
    gap = abs(estimate_rank(dev) - estimate_rank(test))
    if gap <= 2:
        return max(dev, test), False, False
    if not reestimated:
        return max(dev, test), True, False
    return max(dev, test), False, True


def check_proposal(doc: ProposalDoc, issues: list[Issue], *, capacity: int) -> list[str]:
    errors: list[str] = []
    chapters = doc.chapters or list(PROPOSAL_CHAPTERS)
    for name in PROPOSAL_CHAPTERS:
        if name not in chapters:
            errors.append(f"缺章节: {name}")
    if len(doc.features) > 12:
        errors.append("功能清单超过 12 项")
    known = {"初步做法"} | {issue.code for issue in issues}
    for feature in doc.features:
        if not feature.sources or any(src not in known and not src.startswith("初步") for src in feature.sources):
            errors.append(f"功能无有效来源: {feature.name}")
    pending = [issue for issue in issues if issue.status in {"待定", "未讨论"}]
    risk_codes = {risk.code for risk in doc.risks}
    for issue in pending:
        if issue.code not in risk_codes:
            errors.append(f"待定/未讨论未列入风险: {issue.code}")
        else:
            risk = next(r for r in doc.risks if r.code == issue.code)
            if not risk.verification or not risk.fallback:
                errors.append(f"{issue.code} 缺少验证办法或预案")
    total = doc.estimate_total or sum(f.points for f in doc.features)
    if total > capacity:
        errors.append(f"估算 {total} 超过容量 {capacity}")
    return errors


def check_spec(doc: SpecDoc, issues: list[Issue], sheets: list[ReviewSheet] | None = None) -> list[str]:
    errors: list[str] = []
    chapters = doc.chapters or list(SPEC_CHAPTERS)
    for name in SPEC_CHAPTERS:
        if name not in chapters:
            errors.append(f"缺章节: {name}")
    scenario_ids = {str(s.get("code") or s.get("id")) for s in doc.scenarios}
    if not any(item.priority == "P0" for item in doc.features):
        errors.append("至少要有一个 P0 功能")
    for item in doc.features:
        if not item.priority or not item.impact or not item.scenario or not item.acceptance or not item.sources:
            errors.append(f"{item.code} 字段不齐全")
        if item.scenario and item.scenario not in scenario_ids:
            errors.append(f"{item.code} 对应场景不存在")
    adopted = [i for i in issues if i.status == "采纳"]
    pending = [i for i in issues if i.status in {"待定", "未讨论"}]
    withdrawn = [i for i in issues if i.status == "撤回"]
    text_blob = _spec_text(doc)
    open_codes = {str(q.get("code")) for q in doc.open_questions}
    for issue in pending:
        if issue.code not in open_codes:
            errors.append(f"{issue.code} 未出现在第 4 章")
    for issue in adopted:
        dest = issue.destination if isinstance(issue.destination, list) else [issue.destination]
        if not any(issue.code in text_blob for _ in dest):
            errors.append(f"采纳条目 {issue.code} 未在去向位置出现")
    for item in doc.features:
        if not item.sources:
            errors.append(f"{item.code} 无来源")
    if sheets:
        ops = [op for sheet in sheets for op in sheet.opinions if not op.blocking]
        follow = {str(row.get("code") or row.get("text")) for row in doc.review_followup}
        for op in ops:
            token = op.code or op.text
            if token not in follow and op.text not in follow:
                errors.append(f"评审意见未落实: {token}")
    out_text = " ".join(str(x) for x in doc.out_of_scope)
    for item in doc.features:
        if item.title and item.title in out_text:
            errors.append(f"本版不做内容出现在功能列表: {item.title}")
    for issue in withdrawn:
        if issue.text and issue.text in text_blob:
            errors.append(f"撤回条目内容出现在规格: {issue.code}")
    pending_codes = {i.code for i in pending}
    for item in doc.features:
        if item.priority == "P0" and any(src in pending_codes for src in item.sources):
            if item.code not in open_codes and not any(item.code in str(q) for q in doc.open_questions):
                errors.append(f"P0 {item.code} 建立在待定条目上但第 4 章未说明")
    return errors


def check_design(doc: DesignDoc, spec: SpecDoc, issues: list[Issue], *, max_modules: int = 10) -> list[str]:
    errors: list[str] = []
    chapters = doc.chapters or list(DESIGN_CHAPTERS)
    for name in DESIGN_CHAPTERS:
        if name not in chapters:
            errors.append(f"缺章节: {name}")
    modules = {m.code: m for m in doc.modules}
    if len(doc.modules) > max_modules:
        errors.append(f"模块数 {len(doc.modules)} 超过 {max_modules}")
    for module in doc.modules:
        if not module.sources:
            errors.append(f"模块无来源: {module.code}")
        for dep in module.depends_on:
            if dep not in modules:
                errors.append(f"{module.code} 依赖不存在: {dep}")
    for iface in doc.interfaces:
        if iface.provider not in modules:
            errors.append(f"接口提供方不存在: {iface.code}")
        if not iface.consumers:
            errors.append(f"接口缺少调用方: {iface.code}")
        for consumer in iface.consumers:
            if consumer not in modules:
                errors.append(f"接口调用方不存在: {iface.code}/{consumer}")
    cycle = _module_cycle(doc)
    if cycle:
        errors.append("模块依赖成环: " + " -> ".join(cycle))
    for item in spec.out_of_scope:
        title = str(item.get("title") or item.get("text") or "")
        if title and any(title in m.responsibility for m in doc.modules):
            errors.append(f"本版不做内容出现在模块职责: {title}")
    p_items = [f for f in spec.features if f.priority in {"P0", "P1"}]
    covered: set[str] = set()
    for module in doc.modules:
        covered.update(module.sources)
    for item in p_items:
        if item.code not in covered:
            errors.append(f"{item.code} 没有对应模块")
    pending = [i for i in issues if i.status in {"待定", "未讨论"}]
    contig = {str(c.get("code")) for c in doc.contingencies}
    for issue in pending:
        if issue.code not in contig:
            errors.append(f"{issue.code} 影响设计但第 6 章无预案")
    return errors


def check_task_graph(graph: TaskGraph, spec: SpecDoc, design: DesignDoc, capacity: int) -> list[str]:
    errors: list[str] = []
    tasks = {t.code: t for t in graph.tasks}
    for task in graph.tasks:
        if not task.acceptance or any(not item.cmd for item in task.acceptance):
            errors.append(f"{task.code} 验收命令为空")
        if task.points > 8:
            errors.append(f"{task.code} 点数超过 8")
        if len(task.write_set) > 8:
            errors.append(f"{task.code} 写集文件超过 8")
        for dep in task.depends_on:
            if dep not in tasks:
                errors.append(f"{task.code} 悬空依赖 {dep}")
        known = {i.code for i in spec.features + spec.nonfunc} | {m.code for m in design.modules} | {
            c.code for c in design.interfaces
        }
        for src in task.sources:
            if src not in known:
                errors.append(f"{task.code} 来源不存在: {src}")
        for ref in task.inputs:
            if ref.startswith("C") and ref not in {c.code for c in design.interfaces}:
                errors.append(f"{task.code} 输入引用不存在: {ref}")
            elif "/" in ref or ref.endswith(".py"):
                produced = any(ref in other.outputs for other in graph.tasks if other.code in task.depends_on)
                if not produced and ref not in {c.code for c in design.interfaces}:
                    errors.append(f"{task.code} 输入引用不存在: {ref}")
    if _task_cycle(graph):
        errors.append("任务图有环: " + " -> ".join(_task_cycle(graph) or []))
    for item in spec.features:
        if item.priority not in {"P0", "P1"}:
            continue
        impl = [t for t in graph.tasks if item.code in t.sources and t.kind in {"impl", "integration"}]
        test = [t for t in graph.tasks if item.code in t.sources and t.kind == "test"]
        if not impl:
            errors.append(f"{item.code} 缺少实现任务")
        if not test:
            errors.append(f"{item.code} 缺少测试任务")
    total = sum(t.points for t in graph.tasks)
    if total > capacity:
        errors.append(f"总点数 {total} 超过容量 {capacity}")
    errors.extend(_write_set_overlap_errors(graph))
    return errors


def critical_path(graph: TaskGraph) -> list[str]:
    tasks = {t.code: t for t in graph.tasks}
    remaining: dict[str, int] = {}

    def walk(code: str) -> int:
        if code in remaining:
            return remaining[code]
        task = tasks[code]
        downstream = [other.code for other in graph.tasks if code in other.depends_on]
        extra = max((walk(d) for d in downstream), default=0)
        remaining[code] = task.points + extra
        return remaining[code]

    for code in tasks:
        walk(code)
    if not remaining:
        return []
    start = max(remaining, key=lambda c: (remaining[c], -{"P0": 3, "P1": 2, "P2": 1}[tasks[c].priority], c))
    path = [start]
    current = start
    while True:
        downs = [o.code for o in graph.tasks if current in o.depends_on]
        if not downs:
            break
        current = max(downs, key=lambda c: remaining[c])
        path.append(current)
    return path


def _write_set_overlap_errors(graph: TaskGraph) -> list[str]:
    errors: list[str] = []
    reachable = _reachable(graph)
    for i, a in enumerate(graph.tasks):
        for b in graph.tasks[i + 1 :]:
            if _overlap(a.write_set, b.write_set):
                if b.code not in reachable[a.code] and a.code not in reachable[b.code]:
                    errors.append(f"写集重叠无依赖: {a.code} / {b.code}")
    return errors


def _overlap(left: list[str], right: list[str]) -> bool:
    for a in left:
        for b in right:
            if a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/"):
                return True
    return False


def _reachable(graph: TaskGraph) -> dict[str, set[str]]:
    edges: dict[str, list[str]] = defaultdict(list)
    for task in graph.tasks:
        for dep in task.depends_on:
            edges[dep].append(task.code)
    result: dict[str, set[str]] = {}
    for task in graph.tasks:
        seen: set[str] = set()
        queue = deque(edges[task.code])
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(edges[node])
        result[task.code] = seen
    return result


def _task_cycle(graph: TaskGraph) -> list[str] | None:
    return _cycle({t.code: t.depends_on for t in graph.tasks})


def _module_cycle(doc: DesignDoc) -> list[str] | None:
    return _cycle({m.code: m.depends_on for m in doc.modules})


def _cycle(graph: dict[str, list[str]]) -> list[str] | None:
    visiting: set[str] = set()
    seen: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> list[str] | None:
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt in visiting:
                return stack[stack.index(nxt) :] + [nxt]
            if nxt not in seen:
                found = dfs(nxt)
                if found:
                    return found
        visiting.remove(node)
        stack.pop()
        seen.add(node)
        return None

    for node in graph:
        if node not in seen:
            found = dfs(node)
            if found:
                return found
    return None


def _spec_text(doc: SpecDoc) -> str:
    parts = [item.title for item in doc.features + doc.nonfunc]
    parts.extend(str(x) for x in doc.out_of_scope)
    parts.extend(str(x) for x in doc.open_questions)
    parts.extend(src for item in doc.features for src in item.sources)
    return " ".join(parts)

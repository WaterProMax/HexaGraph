from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable


class TraceGraph:
    def __init__(self) -> None:
        self.links: list[dict[str, str]] = []

    def link(self, frm: str, to: str, kind: str, version: str = "1.0") -> None:
        self.links.append({"from": frm, "to": to, "kind": kind, "version": version})

    def impact(self, codes: Iterable[str]) -> dict[str, list[str]]:
        codes = list(codes)
        down = self._walk(codes, reverse=False)
        up = self._walk(codes, reverse=True)
        return {
            "codes": sorted(set(codes) | down | up),
            "downstream": sorted(down),
            "upstream": sorted(up),
        }

    def matrix(self) -> list[dict[str, str]]:
        return list(self.links)

    def check(self) -> list[str]:
        errors: list[str] = []
        nodes: set[str] = set()
        outgoing: dict[str, list[str]] = defaultdict(list)
        incoming: set[str] = set()
        for link in self.links:
            nodes.add(link["from"])
            nodes.add(link["to"])
            outgoing[link["from"]].append(link["to"])
            incoming.add(link["to"])
        cycle = _cycle(outgoing)
        if cycle:
            errors.append("环: " + " -> ".join(cycle))
        return errors

    def _walk(self, starts: list[str], *, reverse: bool) -> set[str]:
        edges: dict[str, list[str]] = defaultdict(list)
        for link in self.links:
            if reverse:
                edges[link["to"]].append(link["from"])
            else:
                edges[link["from"]].append(link["to"])
        seen: set[str] = set()
        queue = deque(starts)
        while queue:
            node = queue.popleft()
            for nxt in edges[node]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen


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

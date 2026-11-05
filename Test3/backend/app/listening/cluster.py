from __future__ import annotations

import math
from typing import Sequence


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


def cluster(vectors: list[list[float]], *, threshold: float = 0.78) -> list[list[int]]:
    groups: list[list[int]] = []
    centroids: list[list[float]] = []
    for idx, vec in enumerate(vectors):
        placed = False
        for g_i, center in enumerate(centroids):
            if cosine(vec, center) >= threshold:
                groups[g_i].append(idx)
                centroids[g_i] = [
                    (center[j] * (len(groups[g_i]) - 1) + vec[j]) / len(groups[g_i]) for j in range(len(vec))
                ]
                placed = True
                break
        if not placed:
            groups.append([idx])
            centroids.append(list(vec))
    return groups

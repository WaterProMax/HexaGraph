"""Canonical artifact hashes for the human-approved execution baseline.

Keys are fixed here so P4/P5 reuse the same strings (contracts C.3.1):
``REQUIREMENT``, ``SPEC``, ``DESIGN``, ``PLAN`` and (later) ``DecisionPackage``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.execution.run_profile import store_approved_baseline_hash


def canonical_artifact_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_artifact(value: Any) -> str:
    return hashlib.sha256(canonical_artifact_bytes(value)).hexdigest()


def write_approved_baseline_hash(run: Any, key: str, value: Any) -> str:
    digest = hash_artifact(value)
    store_approved_baseline_hash(run, key, digest)
    return digest


__all__ = ["canonical_artifact_bytes", "hash_artifact", "write_approved_baseline_hash"]
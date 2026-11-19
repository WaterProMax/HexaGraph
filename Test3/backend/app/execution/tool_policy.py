"""Three-layer command authorization for granted execution (F-08).

A granted task may run a command only when all three independent layers agree:

1. platform/bot policy: ``Workbench._whitelist()`` and ``_forbidden()``;
2. the human-approved Grant: ``ExecutionGrant.allowed_tool_refs``;
3. the server-materialized spec: ``granted_execution.command`` and
   ``granted_execution.tool_refs``.

``allowed_tool_refs`` values are command prefixes (the same vocabulary as
``whitelist_prefixes``), matched on whole argv tokens by
``app.tools.sandbox.command_allowed``.  There is no substring matching and an
empty list means "nothing is authorized", never a wildcard.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.errors import GrantRejected
from app.tools.sandbox import command_allowed

DEFAULT_PLATFORM_WHITELIST = ("python", "python3", "uv", "python -m pytest")


def _clean_refs(refs: Iterable[str] | None) -> list[str]:
    cleaned: list[str] = []
    for ref in refs or ():
        if not isinstance(ref, str):
            continue
        text = ref.strip()
        if text:
            cleaned.append(text)
    return cleaned


def authorize_granted_command(
    command: Sequence[str],
    *,
    grant_tool_refs: Iterable[str] | None,
    spec_tool_refs: Iterable[str] | None,
    platform_whitelist: Iterable[str] | None,
    platform_forbidden: Iterable[str] | None = None,
    expected_command: Sequence[str] | None = None,
) -> list[str]:
    """Validate one command against platform, Grant and materialized spec.

    Returns the normalized argv.  Every failure is a ``GrantRejected`` with a
    specific category, raised before any worktree, write or process exists.
    """
    argv = [str(part) for part in (command or ())]
    if not argv:
        raise GrantRejected(
            "spec_command_missing",
            "granted execution has no pinned command",
            status_code=409,
        )
    if expected_command is not None and argv != [str(part) for part in expected_command]:
        raise GrantRejected(
            "spec_command_mismatch",
            "command does not match the materialized execution spec",
            status_code=409,
        )
    grant_refs = _clean_refs(grant_tool_refs)
    if not grant_refs:
        raise GrantRejected(
            "grant_tool_refs_empty",
            "execution grant authorizes no tools",
            status_code=403,
        )
    spec_refs = _clean_refs(spec_tool_refs)
    if not spec_refs:
        raise GrantRejected(
            "spec_tool_refs_missing",
            "materialized execution spec has no tool refs",
            status_code=409,
        )
    if not set(spec_refs) <= set(grant_refs):
        raise GrantRejected(
            "spec_tool_refs_conflict",
            "materialized tool refs are not covered by the grant",
            status_code=409,
        )
    platform_refs = _clean_refs(platform_whitelist)
    if not platform_refs or not command_allowed(argv, platform_refs, _clean_refs(platform_forbidden)):
        raise GrantRejected(
            "platform_tool_denied",
            "command is not allowed by platform policy",
            status_code=403,
        )
    if not command_allowed(argv, grant_refs, None):
        raise GrantRejected(
            "grant_tool_denied",
            "command is not authorized by the execution grant",
            status_code=403,
        )
    if not command_allowed(argv, spec_refs, None):
        raise GrantRejected(
            "spec_tool_denied",
            "command is not covered by the materialized execution spec",
            status_code=409,
        )
    return argv


__all__ = [
    "DEFAULT_PLATFORM_WHITELIST",
    "authorize_granted_command",
]
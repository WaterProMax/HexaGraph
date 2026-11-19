"""Parse the explicit C.7 ``github_write`` authorization sentence.

Authorization is never inferred from environment state or from a model_live
grant. Missing or malformed authorization yields ``None`` / a denial, never an
implicit push.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.errors import GitHubWriteDenied

_FIELD = re.compile(r"([A-Za-z_]+)\s*=\s*([^\s,;]+)")
_REQUIRED = ("owner", "repo", "remote", "base_branch", "feature_branch")


@dataclass(frozen=True)
class GitHubWriteAuth:
    owner: str
    repo: str
    remote: str
    base_branch: str
    feature_branch: str


def parse_github_write_auth(text: str | None) -> GitHubWriteAuth | None:
    if not text or "github_write" not in text:
        return None
    fields = dict(_FIELD.findall(text))
    missing = [key for key in _REQUIRED if not fields.get(key)]
    if missing:
        raise GitHubWriteDenied(f"github_write authorization missing: {', '.join(missing)}")
    return GitHubWriteAuth(
        owner=fields["owner"],
        repo=fields["repo"],
        remote=fields["remote"],
        base_branch=fields["base_branch"],
        feature_branch=fields["feature_branch"],
    )


__all__ = ["GitHubWriteAuth", "parse_github_write_auth"]
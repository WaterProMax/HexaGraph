"""Parse the structured C.7 ``github_write`` grant (F-09).

Authorization is never inferred from natural language, from a substring such as
``github_write``, or from the mere presence of the word "authorize".  Only one
of two exact shapes is accepted:

1. a JSON object with the fixed ``github_write_grant_v1`` schema;
2. its canonical single-line form, field for field in the same order.

Missing or empty input yields ``None``.  Malformed, negated, partial or
unexpected records raise ``GitHubWriteDenied`` so adapters fail closed instead
of pushing.  This module never contacts GitHub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.errors import GitHubWriteDenied

GRANT_TYPE = "github_write_grant_v1"
ALLOWED_VERB = "authorize"

_TEXT_FIELDS = ("owner", "repo", "remote", "base_branch", "feature_branch")
_BOOL_FIELDS = {
    "allow_push": True,
    "allow_pr_create": True,
    "allow_merge": False,
    "allow_deploy": False,
}
_REQUIRED_KEYS = frozenset({"type", "verb", *_TEXT_FIELDS, *_BOOL_FIELDS})

_CANONICAL = re.compile(
    r"github_write_grant_v1 authorize "
    r"owner=(?P<owner>\S+) repo=(?P<repo>\S+) remote=(?P<remote>\S+) "
    r"base_branch=(?P<base_branch>\S+) feature_branch=(?P<feature_branch>\S+) "
    r"allow_push=(?P<allow_push>true|false) allow_pr_create=(?P<allow_pr_create>true|false) "
    r"allow_merge=(?P<allow_merge>true|false) allow_deploy=(?P<allow_deploy>true|false)"
)


@dataclass(frozen=True)
class GitHubWriteAuth:
    owner: str
    repo: str
    remote: str
    base_branch: str
    feature_branch: str


def parse_github_write_auth(text: str | None) -> GitHubWriteAuth | None:
    if text is None:
        return None
    if not isinstance(text, str):
        raise GitHubWriteDenied("github_write authorization must be a structured record")
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith("{"):
        record: dict[str, Any] = _load_json_object(stripped)
    else:
        if "github_write" not in stripped:
            # Plain prose that is not even shaped like a grant attempt is simply
            # absent authorization, not a malformed record.
            return None
        canonical = _parse_canonical(stripped)
        if canonical is None:
            raise GitHubWriteDenied(
                "github_write authorization must be a github_write_grant_v1 record"
            )
        record = canonical

    _validate_record(record)
    return GitHubWriteAuth(
        owner=record["owner"],
        repo=record["repo"],
        remote=record["remote"],
        base_branch=record["base_branch"],
        feature_branch=record["feature_branch"],
    )


def _load_json_object(text: str) -> dict[str, Any]:
    try:
        record = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GitHubWriteDenied("github_write authorization is not valid JSON") from exc
    if not isinstance(record, dict):
        raise GitHubWriteDenied("github_write authorization must be a JSON object")
    return record


def _parse_canonical(text: str) -> dict[str, Any] | None:
    match = _CANONICAL.fullmatch(text)
    if match is None:
        return None
    record: dict[str, Any] = {
        "type": GRANT_TYPE,
        "verb": ALLOWED_VERB,
        **{field: match.group(field) for field in _TEXT_FIELDS},
        **{field: match.group(field) == "true" for field in _BOOL_FIELDS},
    }
    return record


def _validate_record(record: dict[str, Any]) -> None:
    keys = set(record)
    if keys != _REQUIRED_KEYS:
        missing = sorted(_REQUIRED_KEYS - keys)
        extra = sorted(keys - _REQUIRED_KEYS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise GitHubWriteDenied("github_write grant has " + "; ".join(detail))

    if record["type"] != GRANT_TYPE:
        raise GitHubWriteDenied("github_write grant has an unsupported type")
    if record["verb"] != ALLOWED_VERB:
        raise GitHubWriteDenied("github_write grant is not an explicit authorize record")

    for field in _TEXT_FIELDS:
        value = record[field]
        if not isinstance(value, str) or not value.strip():
            raise GitHubWriteDenied(f"github_write grant field is empty: {field}")
        if value != value.strip() or any(ch.isspace() or ord(ch) < 32 for ch in value):
            raise GitHubWriteDenied(f"github_write grant field is not a single token: {field}")

    for field, required in _BOOL_FIELDS.items():
        value = record[field]
        if type(value) is not bool:
            raise GitHubWriteDenied(f"github_write grant flag is not a boolean: {field}")
        if value is not required:
            raise GitHubWriteDenied(f"github_write grant flag is not permitted: {field}")


__all__ = [
    "ALLOWED_VERB",
    "GRANT_TYPE",
    "GitHubWriteAuth",
    "parse_github_write_auth",
]
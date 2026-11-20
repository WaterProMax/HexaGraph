"""Controlled git/GitHub adapter bound to auth, an active Grant and workspace state.

Every write requires all of:

1. a structured ``GitHubWriteAuth`` (F-09) — missing or failed parsing denies;
2. an active ``ExecutionGrant`` for the same run whose owner/repo/remote and
   branches match the authorization record;
3. the workspace's real git state: current branch equals the authorized feature
   branch and the remote URL resolves to the authorized owner/repo.

It only commits an explicit file list, pushes to the authorized feature ref and
creates or reuses a pull request with an explicit ``--repo``.  There is
deliberately no merge, release or force-push helper here, and nothing in this
module reads credentials or contacts a real remote in tests.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth
from app.schemas.execution_grant import ExecutionGrant

Runner = Callable[[list[str], Path], tuple[int, str]]

_PR_LOCK = threading.Lock()
_PROTECTED_BRANCHES = frozenset({"main", "master"})
_BAD_BRANCH_CHARS = frozenset(" ~^:?*[\\")
_BAD_PATH_CHARS = frozenset("*?[")


def _default_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    return completed.returncode, completed.stdout + completed.stderr


@dataclass
class PushResult:
    sha: str
    pushed: bool
    feature_branch: str


class PrLookupStatus(str, Enum):
    ABSENT = "absent"
    EXISTS = "exists"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PrLookup:
    status: PrLookupStatus
    url: str = ""
    error: str = ""


def _require_auth(auth: GitHubWriteAuth | None) -> GitHubWriteAuth:
    if auth is None:
        raise GitHubWriteDenied("missing github_write authorization")
    return auth


def _require_binding(
    auth: GitHubWriteAuth | None,
    grant: ExecutionGrant | None,
    run_id: str,
    workspace: Path,
    run: Runner,
) -> GitHubWriteAuth:
    """Fail closed unless auth, Grant and workspace all agree."""
    auth = _require_auth(auth)
    if grant is None:
        raise GitHubWriteDenied("missing execution grant")
    if not run_id or grant.run_id != run_id:
        raise GitHubWriteDenied("execution grant is bound to another run")
    if grant.status != "active":
        raise GitHubWriteDenied(f"execution grant is not active: {grant.status}")
    if not grant.task_codes:
        raise GitHubWriteDenied("execution grant has no task scope")
    for field in ("owner", "repo", "remote", "base_branch", "feature_branch"):
        value = getattr(auth, field)
        if not isinstance(value, str) or not value.strip():
            raise GitHubWriteDenied(f"github_write authorization field is empty: {field}")
    _check_branch_names(auth.feature_branch, auth.base_branch)

    expected = {
        "owner": grant.repo_owner,
        "repo": grant.repo_name,
        "remote": grant.repo_remote,
        "base_branch": grant.base_branch,
        "feature_branch": grant.feature_branch,
    }
    for field, value in expected.items():
        if getattr(auth, field) != value:
            raise GitHubWriteDenied(f"github_write authorization does not match the grant: {field}")

    expected_owner = auth.owner.lower()
    expected_repo = auth.repo.lower()
    for field, value in (("owner", expected_owner), ("repo", expected_repo)):
        if not value:
            raise GitHubWriteDenied(f"github_write authorization field is empty: {field}")

    code, out = run(["git", "symbolic-ref", "--short", "HEAD"], workspace)
    if code != 0:
        raise GitHubWriteDenied(f"cannot read workspace branch: {out.strip()}")
    if out.strip() != auth.feature_branch:
        raise GitHubWriteDenied("workspace is not on the authorized feature branch")

    code, out = run(["git", "remote", "get-url", auth.remote], workspace)
    if code != 0:
        raise GitHubWriteDenied(f"cannot read remote url for {auth.remote}: {out.strip()}")
    parsed = _parse_remote(out.strip())
    if parsed is None:
        raise GitHubWriteDenied("remote is not a github owner/repo url")
    owner, repo = parsed
    if owner.lower() != expected_owner or repo.lower() != expected_repo:
        raise GitHubWriteDenied("remote owner/repo does not match the authorization")
    return auth


def _check_branch_names(feature_branch: str, base_branch: str) -> None:
    for value in (feature_branch, base_branch):
        if not isinstance(value, str) or not value or value != value.strip():
            raise GitHubWriteDenied("branch name is empty or padded")
        if any(ch.isspace() or ord(ch) < 32 or ch in _BAD_BRANCH_CHARS for ch in value):
            raise GitHubWriteDenied("branch name contains forbidden characters")
    if feature_branch in _PROTECTED_BRANCHES:
        raise GitHubWriteDenied(f"refusing to write to protected branch: {feature_branch}")
    if feature_branch == base_branch:
        raise GitHubWriteDenied("refusing to write to the base branch")


def _parse_remote(url: str) -> tuple[str, str] | None:
    text = url.strip()
    if not text:
        return None
    if "://" in text:
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
        path = parsed.path
    else:
        match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", text)
        if match is None:
            return None
        host = match.group(1).lower()
        path = match.group(2)
    if host not in {"github.com", "www.github.com"}:
        return None
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [part for part in path.split("/") if part]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _explicit_paths(files: Sequence[str]) -> list[str]:
    if not files:
        raise GitHubWriteDenied("commit needs an explicit file list")
    paths: list[str] = []
    for raw in files:
        if not isinstance(raw, str):
            raise GitHubWriteDenied("commit paths must be strings")
        text = raw.strip()
        if not text or text in {".", ".."}:
            raise GitHubWriteDenied("commit path is empty")
        path = Path(text)
        if path.is_absolute():
            raise GitHubWriteDenied(f"commit path is absolute: {text}")
        if ".." in path.parts:
            raise GitHubWriteDenied(f"commit path escapes the workspace: {text}")
        if text.startswith("-") or any(ch in _BAD_PATH_CHARS for ch in text):
            raise GitHubWriteDenied(f"commit path is ambiguous: {text}")
        if "\x00" in text:
            raise GitHubWriteDenied("commit path contains NUL")
        if text not in paths:
            paths.append(text)
    return paths


def commit_files(
    workspace: Path,
    files: Sequence[str],
    message: str,
    *,
    auth: GitHubWriteAuth | None,
    grant: ExecutionGrant | None,
    run_id: str,
    runner: Runner | None = None,
) -> str:
    """Commit an explicit file list on the authorized feature branch only."""
    run = runner or _default_runner
    _require_binding(auth, grant, run_id, workspace, run)
    paths = _explicit_paths(files)
    code, out = run(["git", "add", "--", *paths], workspace)
    if code != 0:
        raise GitHubWriteDenied(f"git add failed: {out.strip()}")
    code, out = run(["git", "commit", "-m", message], workspace)
    if code != 0 and "nothing to commit" not in out:
        raise GitHubWriteDenied(f"git commit failed: {out.strip()}")
    code, out = run(["git", "rev-parse", "HEAD"], workspace)
    if code != 0:
        raise GitHubWriteDenied(f"git rev-parse failed: {out.strip()}")
    return out.strip()


def _read_marker(marker_path: Path) -> dict:
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_marker(marker_path: Path, data: dict) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def push_once(
    *,
    auth: GitHubWriteAuth | None,
    grant: ExecutionGrant | None,
    run_id: str,
    marker_path: Path,
    workspace: Path | None = None,
    runner: Runner | None = None,
) -> PushResult:
    run = runner or _default_runner
    cwd = workspace or Path.cwd()
    auth = _require_binding(auth, grant, run_id, cwd, run)
    assert grant is not None  # narrowed by _require_binding
    code, out = run(["git", "rev-parse", "HEAD"], cwd)
    if code != 0:
        raise GitHubWriteDenied(f"git rev-parse failed: {out.strip()}")
    sha = out.strip()
    marker = _read_marker(marker_path)
    if (
        marker.get("pushed_sha") == sha
        and marker.get("feature_branch") == auth.feature_branch
        and marker.get("grant_id") == grant.grant_id
    ):
        return PushResult(sha=sha, pushed=False, feature_branch=auth.feature_branch)

    refspec = f"HEAD:refs/heads/{auth.feature_branch}"
    if auth.feature_branch in _PROTECTED_BRANCHES or auth.feature_branch == auth.base_branch:
        raise GitHubWriteDenied("refusing to push to a protected or base ref")
    argv = ["git", "push", auth.remote, refspec]
    if "--force" in argv or any(part.startswith("+") for part in argv):
        raise GitHubWriteDenied("refusing to force-push")
    code, out = run(argv, cwd)
    if code != 0:
        raise GitHubWriteDenied(f"git push failed: {out.strip()}")
    _write_marker(
        marker_path,
        {
            "pushed_sha": sha,
            "feature_branch": auth.feature_branch,
            "base_branch": auth.base_branch,
            "grant_id": grant.grant_id,
        },
    )
    return PushResult(sha=sha, pushed=True, feature_branch=auth.feature_branch)


def _existing_pr_url(auth: GitHubWriteAuth, cwd: Path, run: Runner, repo: str) -> PrLookup:
    """Distinguish absent / exists / unknown; unknown must never create."""
    argv = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--head",
        auth.feature_branch,
        "--base",
        auth.base_branch,
        "--state",
        "open",
        "--json",
        "url",
        "--limit",
        "1",
    ]
    try:
        code, out = run(argv, cwd)
    except Exception as exc:  # noqa: BLE001 - any runner failure is "unknown"
        return PrLookup(PrLookupStatus.UNKNOWN, error=f"gh pr list raised: {exc}")
    if code != 0:
        return PrLookup(
            PrLookupStatus.UNKNOWN,
            error=f"gh pr list exited {code}: {out.strip()[:200]}",
        )
    try:
        rows = json.loads(out or "[]")
    except json.JSONDecodeError as exc:
        return PrLookup(PrLookupStatus.UNKNOWN, error=f"gh pr list returned invalid JSON: {exc}")
    if not isinstance(rows, list):
        return PrLookup(PrLookupStatus.UNKNOWN, error="gh pr list did not return a JSON array")
    if not rows:
        return PrLookup(PrLookupStatus.ABSENT)
    first = rows[0]
    if not isinstance(first, dict):
        return PrLookup(PrLookupStatus.UNKNOWN, error="gh pr list entry is not an object")
    url = first.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return PrLookup(PrLookupStatus.UNKNOWN, error="gh pr list entry has no usable url")
    return PrLookup(PrLookupStatus.EXISTS, url=url)


def create_pr_idempotent(
    *,
    auth: GitHubWriteAuth | None,
    grant: ExecutionGrant | None,
    run_id: str,
    workspace: Path | None = None,
    runner: Runner | None = None,
) -> str:
    run = runner or _default_runner
    cwd = workspace or Path.cwd()
    auth = _require_binding(auth, grant, run_id, cwd, run)
    repo = f"{auth.owner}/{auth.repo}"
    # Serialize list+create so two workers cannot open duplicate PRs.
    with _PR_LOCK:
        lookup = _existing_pr_url(auth, cwd, run, repo)
        if lookup.status is PrLookupStatus.EXISTS:
            return lookup.url
        if lookup.status is PrLookupStatus.UNKNOWN:
            raise GitHubWriteDenied(f"cannot determine open pull requests: {lookup.error}")
        code, out = run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--head",
                auth.feature_branch,
                "--base",
                auth.base_branch,
                "--title",
                f"HexaGraph {auth.feature_branch}",
                "--body",
                "Created by the restricted Test3 execution worker.",
            ],
            cwd,
        )
        if code != 0:
            raise GitHubWriteDenied(f"gh pr create failed: {out.strip()}")
        for token in reversed(out.split()):
            candidate = token.strip()
            if candidate.startswith("https://"):
                return candidate
        raise GitHubWriteDenied("gh pr create returned no https URL")


__all__ = ["PushResult", "commit_files", "create_pr_idempotent", "push_once"]
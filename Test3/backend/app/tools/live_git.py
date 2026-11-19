"""Controlled git/GitHub adapter for one authorized feature branch.

It only commits, pushes to the authorized feature branch, and creates or
reuses a pull request. There is deliberately no merge or release helper here.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.errors import GitHubWriteDenied
from app.execution.github_auth import GitHubWriteAuth

Runner = Callable[[list[str], Path], tuple[int, str]]

_PR_LOCK = threading.Lock()


def _default_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    return completed.returncode, completed.stdout + completed.stderr


@dataclass
class PushResult:
    sha: str
    pushed: bool
    feature_branch: str


def _require_auth(auth: GitHubWriteAuth | None) -> GitHubWriteAuth:
    if auth is None:
        raise GitHubWriteDenied("missing github_write authorization")
    return auth


def commit_all(workspace: Path, message: str, *, runner: Runner | None = None) -> str:
    run = runner or _default_runner
    code, out = run(["git", "add", "-A"], workspace)
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
    auth: GitHubWriteAuth | None,
    *,
    marker_path: Path,
    workspace: Path | None = None,
    grant_id: str = "",
    runner: Runner | None = None,
) -> PushResult:
    auth = _require_auth(auth)
    run = runner or _default_runner
    cwd = workspace or Path.cwd()
    code, out = run(["git", "rev-parse", "HEAD"], cwd)
    if code != 0:
        raise GitHubWriteDenied(f"git rev-parse failed: {out.strip()}")
    sha = out.strip()
    marker = _read_marker(marker_path)
    if (
        marker.get("pushed_sha") == sha
        and marker.get("feature_branch") == auth.feature_branch
        and (not grant_id or marker.get("grant_id") in ("", grant_id))
    ):
        return PushResult(sha=sha, pushed=False, feature_branch=auth.feature_branch)

    refspec = f"HEAD:refs/heads/{auth.feature_branch}"
    if refspec == f"HEAD:refs/heads/{auth.base_branch}":
        raise GitHubWriteDenied("refusing to push to base branch")
    argv = ["git", "push", auth.remote, refspec]
    if any(auth.base_branch == part for part in argv):
        raise GitHubWriteDenied("refusing to push to base branch")
    code, out = run(argv, cwd)
    if code != 0:
        raise GitHubWriteDenied(f"git push failed: {out.strip()}")
    _write_marker(
        marker_path,
        {
            "pushed_sha": sha,
            "feature_branch": auth.feature_branch,
            "base_branch": auth.base_branch,
            "grant_id": grant_id,
        },
    )
    return PushResult(sha=sha, pushed=True, feature_branch=auth.feature_branch)


def _existing_pr_url(auth: GitHubWriteAuth, cwd: Path, run: Runner) -> str | None:
    code, out = run(
        ["gh", "pr", "list", "--head", auth.feature_branch, "--base", auth.base_branch, "--state", "open", "--json", "url", "--limit", "1"],
        cwd,
    )
    if code != 0:
        return None
    try:
        rows = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    if isinstance(rows, list) and rows:
        url = str((rows[0] or {}).get("url") or "")
        return url or None
    return None


def create_pr_idempotent(
    auth: GitHubWriteAuth | None,
    *,
    workspace: Path | None = None,
    runner: Runner | None = None,
) -> str:
    auth = _require_auth(auth)
    run = runner or _default_runner
    cwd = workspace or Path.cwd()
    # Serialize list+create so two workers cannot open duplicate PRs.
    with _PR_LOCK:
        existing = _existing_pr_url(auth, cwd, run)
        if existing:
            return existing
        code, out = run(
            [
                "gh",
                "pr",
                "create",
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


__all__ = ["PushResult", "commit_all", "create_pr_idempotent", "push_once"]
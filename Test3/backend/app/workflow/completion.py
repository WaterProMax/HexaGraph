"""Card C: read-only proof that an attempt produced the claimed integration.

The proof is bound to the attempt's frozen ``base_commit`` and
``integration_ref``.  ``write_set`` names the authorized paths; the actual
``git diff base..commit`` must be non-empty and fully inside that set.  The
product commit must be on the recorded task branch and already reachable from
the frozen integration ref.  Unmerged/squashed/cherry-picked work is reported
as not provable and requires a human decision instead of a guessed success.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.execution.run_profile import run_approved_baseline_hashes
from app.workspace.gitops import _git_sync


@dataclass
class VerificationReport:
    ok: bool
    reason: str = ""
    commit: str = ""
    branch: str = ""
    base_commit: str = ""
    integration_ref: str = ""
    branch_binding: str = ""
    changed: list[str] = field(default_factory=list)
    write_set_hit: list[str] = field(default_factory=list)
    ancestry: str = ""
    provenance: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "commit": self.commit,
            "branch": self.branch,
            "base_commit": self.base_commit,
            "integration_ref": self.integration_ref,
            "branch_binding": self.branch_binding,
            "changed": list(self.changed),
            "write_set_hit": list(self.write_set_hit),
            "ancestry": self.ancestry,
            "provenance": list(self.provenance),
        }


def _fail(reason: str, provenance: list[str]) -> VerificationReport:
    return VerificationReport(ok=False, reason=reason, provenance=provenance)


def _normalize_path(raw: str) -> str | None:
    value = str(raw or "").replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("/") or "\x00" in value:
        return None
    if value == "." or value == ".." or value.startswith("../") or "/../" in value:
        return None
    normalized = posixpath.normpath(value)
    if normalized in {".", ".."} or normalized.startswith("../") or normalized.startswith("/"):
        return None
    return normalized


def _read_diff(
    repo: Path, base: str, commit: str, provenance: list[str]
) -> tuple[list[tuple[str, str]] | None, str]:
    code, raw = _git_sync(repo, "diff", "--name-status", "--no-renames", "-z", base, commit)
    provenance.append(f"diff:{code}")
    if code != 0:
        return None, "diff_unreadable"
    parts = raw.split("\x00")
    changes: list[tuple[str, str]] = []
    index = 0
    while index < len(parts):
        status = parts[index].strip()
        index += 1
        if not status:
            continue
        if index >= len(parts):
            return None, "diff_unreadable"
        raw_path = parts[index]
        index += 1
        normalized = _normalize_path(raw_path)
        if normalized is None:
            return None, f"invalid_diff_path:{raw_path}"
        changes.append((status, normalized))
    return changes, ""


def _write_set(
    repo: Path,
    base: str,
    raw_entries: list[str],
    changed_paths: list[str],
) -> tuple[list[tuple[str, bool]] | None, str]:
    entries: list[tuple[str, bool]] = []
    for raw in raw_entries:
        normalized = _normalize_path(raw)
        if normalized is None:
            return None, f"invalid_write_set:{raw}"
        explicit_dir = str(raw).replace("\\", "/").endswith("/")
        is_dir = explicit_dir
        if not is_dir:
            code, kind = _git_sync(repo, "cat-file", "-t", f"{base}:{normalized}")
            is_dir = code == 0 and kind.strip() == "tree"
        if not is_dir and normalized not in changed_paths:
            is_dir = any(path.startswith(f"{normalized}/") for path in changed_paths)
        entries.append((normalized, is_dir))
    if not entries:
        return None, "write_set_missing"
    return entries, ""


def _allowed(path: str, entries: list[tuple[str, bool]]) -> bool:
    for entry, is_dir in entries:
        if path == entry:
            return True
        if is_dir and path.startswith(f"{entry}/"):
            return True
    return False


def verify_task_completion(
    run: Any,
    task: dict[str, Any],
    attempt: dict[str, Any],
    *,
    expected_repo: Path,
) -> VerificationReport:
    provenance: list[str] = []
    if not isinstance(attempt, dict) or not attempt.get("attempt_id"):
        return _fail("attempt_missing", provenance)
    if str(attempt.get("task_code") or "") != str(task.get("code") or ""):
        return _fail("task_code_mismatch", provenance)
    if str(attempt.get("run_id") or "") != str(run.id):
        return _fail("run_id_mismatch", provenance)
    if str(attempt.get("project_id") or "") != str(run.project_id):
        return _fail("project_id_mismatch", provenance)
    if dict(attempt.get("baseline_hashes") or {}) != dict(run_approved_baseline_hashes(run)):
        return _fail("baseline_mismatch", provenance)
    repo = Path(str(attempt.get("repo") or ""))
    try:
        repo_resolved = repo.resolve()
        expected_resolved = Path(expected_repo).resolve()
        recorded_identity = Path(str(attempt.get("repo_identity") or "")).resolve()
        repo_ok = repo_resolved == expected_resolved and recorded_identity == expected_resolved
    except OSError:
        repo_ok = False
    if not repo_ok:
        return _fail("repo_identity_mismatch", provenance)
    if not (repo / ".git").exists():
        return _fail("repo_missing", provenance)
    # attempt["worktree"] is deliberately not read: the proof is the commit
    # graph, and a check must never create, repair or enter a worktree.
    base = str(attempt.get("base_commit") or "")
    integration_ref = str(attempt.get("integration_ref") or "")
    branch = str(attempt.get("branch") or "")
    commit = str(attempt.get("commit") or "")
    if not base or not integration_ref.startswith("refs/") or not branch:
        return _fail("attempt_proof_fields_missing", provenance)
    if not commit:
        return _fail("commit_missing", provenance)
    code, _ = _git_sync(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    provenance.append(f"cat-file:{code}")
    if code != 0:
        return _fail("commit_not_found", provenance)
    code, _ = _git_sync(repo, "cat-file", "-e", f"{base}^{{commit}}")
    provenance.append(f"base-cat-file:{code}")
    if code != 0:
        return _fail("base_commit_not_found", provenance)
    code, _ = _git_sync(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
    provenance.append(f"branch:{code}")
    if code != 0:
        return _fail("branch_missing", provenance)
    code, _ = _git_sync(repo, "merge-base", "--is-ancestor", commit, f"refs/heads/{branch}")
    provenance.append(f"branch-ancestor:{code}")
    branch_binding = "commit_on_branch" if code == 0 else ""
    if code != 0:
        # A no-ff merge commit is not on the task branch, but the task branch
        # is one of its ancestors.  That is a read-only proof the commit came
        # from this branch's work.
        code, _ = _git_sync(repo, "merge-base", "--is-ancestor", f"refs/heads/{branch}", commit)
        provenance.append(f"branch-merged-into-commit:{code}")
        if code == 0:
            branch_binding = "branch_merged_into_commit"
        else:
            return _fail("commit_not_on_task_branch", provenance)
    code, _ = _git_sync(repo, "merge-base", "--is-ancestor", base, commit)
    provenance.append(f"base-ancestor:{code}")
    if code != 0:
        return _fail("base_not_ancestor_of_commit", provenance)
    code, resolved_ref = _git_sync(repo, "rev-parse", "--verify", integration_ref)
    provenance.append(f"integration-ref:{code}")
    if code != 0:
        return _fail("integration_ref_missing", provenance)
    frozen_ref_sha = str(attempt.get("integration_ref_sha") or "")
    if frozen_ref_sha:
        code, _ = _git_sync(repo, "cat-file", "-e", f"{frozen_ref_sha}^{{commit}}")
        provenance.append(f"integration-ref-sha:{code}")
        if code != 0:
            return _fail("integration_ref_missing", provenance)
        code, _ = _git_sync(repo, "merge-base", "--is-ancestor", frozen_ref_sha, resolved_ref.strip())
        provenance.append(f"integration-ref-rewound:{code}")
        if code != 0:
            return _fail("integration_ref_rewound", provenance)
    code, _ = _git_sync(repo, "merge-base", "--is-ancestor", commit, resolved_ref.strip())
    provenance.append(f"integrated:{code}")
    if code != 0:
        return _fail("commit_not_integrated", provenance)
    changes, error = _read_diff(repo, base, commit, provenance)
    if changes is None:
        return _fail(error, provenance)
    if not changes:
        return _fail("no_relevant_changes", provenance)
    changed_paths = [path for _status, path in changes]
    entries, error = _write_set(repo, base, [str(item) for item in (attempt.get("write_set") or [])], changed_paths)
    if entries is None:
        return _fail(error, provenance)
    outside = sorted({path for path in changed_paths if not _allowed(path, entries)})
    if outside:
        return _fail(f"changes_outside_write_set:{','.join(outside)}", provenance)
    return VerificationReport(
        ok=True,
        commit=commit,
        branch=branch,
        base_commit=base,
        integration_ref=integration_ref,
        branch_binding=branch_binding,
        changed=sorted(changed_paths),
        write_set_hit=sorted(changed_paths),
        ancestry=f"{base}..{commit} in {integration_ref}",
        provenance=provenance,
    )


__all__ = ["VerificationReport", "verify_task_completion"]
"""F4: read-only proof that a task attempt produced the claimed work.

String ``status == done`` or ``HEAD == commit`` is not proof.  The validator
checks identity, baseline, repo binding, branch ancestry and that every
``write_set`` path exists in the claimed commit tree.
"""

from __future__ import annotations

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
    write_set_hit: list[str] = field(default_factory=list)
    ancestry: str = ""
    provenance: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "commit": self.commit,
            "branch": self.branch,
            "write_set_hit": list(self.write_set_hit),
            "ancestry": self.ancestry,
            "provenance": list(self.provenance),
        }


def _fail(reason: str, provenance: list[str]) -> VerificationReport:
    return VerificationReport(ok=False, reason=reason, provenance=provenance)


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
        repo_ok = repo.resolve() == Path(expected_repo).resolve()
    except OSError:
        repo_ok = False
    if not repo_ok:
        return _fail("repo_identity_mismatch", provenance)
    if not (repo / ".git").exists():
        return _fail("repo_missing", provenance)
    commit = str(attempt.get("commit") or "")
    if not commit:
        return _fail("commit_missing", provenance)
    code, _ = _git_sync(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    provenance.append(f"cat-file:{code}")
    if code != 0:
        return _fail("commit_not_found", provenance)
    write_set = [str(item) for item in (attempt.get("write_set") or [])]
    if not write_set:
        return _fail("write_set_missing", provenance)
    code, tree = _git_sync(repo, "ls-tree", "-r", "--name-only", commit)
    provenance.append(f"ls-tree:{code}")
    if code != 0:
        return _fail("tree_unreadable", provenance)
    tree_paths = {line.strip() for line in tree.splitlines() if line.strip()}
    missing = [path for path in write_set if path not in tree_paths]
    if missing:
        return _fail(f"write_set_not_in_commit:{','.join(missing)}", provenance)
    branch = str(attempt.get("branch") or "")
    if branch:
        code, _ = _git_sync(repo, "rev-parse", "--verify", f"refs/heads/{branch}")
        provenance.append(f"branch:{code}")
        if code != 0:
            return _fail("branch_missing", provenance)
    target = str(attempt.get("target_branch") or "HEAD")
    code, _ = _git_sync(repo, "merge-base", "--is-ancestor", commit, target)
    provenance.append(f"ancestor:{code}")
    if code != 0:
        return _fail("commit_not_on_target_branch", provenance)
    return VerificationReport(
        ok=True,
        commit=commit,
        branch=branch,
        write_set_hit=write_set,
        ancestry=f"{commit}..{target}",
        provenance=provenance,
    )


__all__ = ["VerificationReport", "verify_task_completion"]
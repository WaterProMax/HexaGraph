from __future__ import annotations

from pathlib import Path

from app.workspace.gitops import changed_files, commit, create_worktree, head_sha, init_repo_sync, is_merged, merge, rollback_merge


def test_commit_treats_clean_worktree_as_noop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_sync(repo, {"README.md": "base\n"})
    before = head_sha(repo)
    assert commit(repo, "identical content") == before
    assert head_sha(repo) == before


def test_git_worktree_merge_conflict_rollback(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_sync(repo, {"README.md": "base\n", "a.txt": "1\n"})
    wt1 = tmp_path / "wt1"
    wt2 = tmp_path / "wt2"
    create_worktree(repo, wt1, "task/T-01")
    (wt1 / "a.txt").write_text("left\n")
    commit(wt1, "left")
    create_worktree(repo, wt2, "task/T-02")
    (wt2 / "a.txt").write_text("right\n")
    commit(wt2, "right")
    first = merge(repo, "task/T-01")
    assert first["ok"]
    assert is_merged(repo, "task/T-01")
    conflict = merge(repo, "task/T-02")
    assert not conflict["ok"]
    assert conflict["conflicts"]
    rollback_merge(repo, first["before"] if not first["ok"] else _head(repo))
    # after successful first merge, rollback using recorded before of conflict
    rollback_merge(repo, conflict["before"])
    assert (repo / "a.txt").read_text() in {"left\n", "1\n"}
    names = changed_files(wt1, "HEAD~1")
    assert names


def _head(repo: Path) -> str:
    import subprocess

    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

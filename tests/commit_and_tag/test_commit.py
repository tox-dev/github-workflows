from __future__ import annotations

import os
lazy from pathlib import Path

import pytest
from conftest import action, run


@pytest.mark.parametrize(
    "annotated",
    [pytest.param("false", id="lightweight"), pytest.param("true", id="annotated")],
)
@pytest.mark.parametrize("branch", [pytest.param("main", id="main"), pytest.param("release", id="release-branch")])
def test_commit_and_tag_pushes_atomically(
    repository: Path, tmp_path: Path, action_scripts: Path, annotated: str, branch: str
) -> None:
    if branch != "main":
        run(repository, "git", "checkout", "-b", branch)
        run(repository, "git", "push", "origin", f"HEAD:{branch}")
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    assert (
        action(
            repository,
            tmp_path,
            action_scripts,
            "validate-release-patch",
            version="0.2.0",
            BRANCH=branch,
        ).returncode
        == 0
    )
    gh = tmp_path / "gh"
    gh.write_text('#!/usr/bin/env bash\nif [[ "$1" == api ]]; then echo 123; fi\n')
    gh.chmod(0o755)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "commit-and-tag",
        version="0.2.0",
        APP_SLUG="release-test",
        TOKEN="test-token",  # ruff: ignore[hardcoded-password-func-arg]  # Local Git fixture never sends this token.
        MESSAGE="release 0.2.0",
        ANNOTATED=annotated,
        BRANCH=branch,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    assert result.returncode == 0, result.stderr
    assert run(repository, "git", "ls-remote", "origin", "refs/tags/0.2.0").stdout.strip()
    assert run(repository, "git", "ls-remote", "origin", f"refs/heads/{branch}").stdout.strip()
    assert run(repository, "git", "cat-file", "-t", "refs/tags/0.2.0").stdout.strip() == (
        "tag" if annotated == "true" else "commit"
    )
    assert run(repository, "git", "log", "-1", "--format=%s").stdout.strip() == "release 0.2.0"
    assert run(repository, "git", "log", "-1", "--format=%an").stdout.strip() == "release-test[bot]"


def test_commit_and_tag_rejects_invalid_tag(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "add", "CHANGELOG.md")
    original_head = run(repository, "git", "rev-parse", "HEAD").stdout
    result = action(repository, tmp_path, action_scripts, "commit-and-tag", version="bad tag")
    assert result.returncode != 0
    assert "invalid release tag" in result.stderr
    assert run(repository, "git", "rev-parse", "HEAD").stdout == original_head


def test_commit_and_tag_rejects_empty_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "commit-and-tag", version="0.2.0")
    assert result.returncode != 0
    assert "expected only a staged release patch" in result.stderr


def test_commit_and_tag_rejects_unstaged_changes(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Staged release.\n")
    run(repository, "git", "add", "CHANGELOG.md")
    (repository / "CHANGELOG.md").write_text("Unstaged changes.\n")
    result = action(repository, tmp_path, action_scripts, "commit-and-tag", version="0.2.0")
    assert result.returncode != 0
    assert "expected only a staged release patch" in result.stderr


def test_commit_and_tag_rejects_untracked_file(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Staged release.\n")
    run(repository, "git", "add", "CHANGELOG.md")
    (repository / "untracked").write_text("unexpected\n")
    result = action(repository, tmp_path, action_scripts, "commit-and-tag", version="0.2.0")
    assert result.returncode != 0
    assert "expected only a staged release patch" in result.stderr


def test_commit_and_tag_rejects_invalid_annotated(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Staged release.\n")
    run(repository, "git", "add", "CHANGELOG.md")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "commit-and-tag",
        version="0.2.0",
        ANNOTATED="maybe",
    )
    assert result.returncode != 0
    assert "annotated must be true or false" in result.stderr


def test_commit_and_tag_keeps_remote_unchanged_on_rejection(
    repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    assert action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0").returncode == 0
    remote = tmp_path / "remote.git"
    before = run(repository, "git", "ls-remote", "origin", "refs/heads/main").stdout
    hook = remote / "hooks/pre-receive"
    hook.write_text('#!/usr/bin/env bash\nwhile read -r old new ref; do [[ "$ref" != refs/tags/* ]] || exit 1; done\n')
    hook.chmod(0o755)
    gh = tmp_path / "gh"
    gh.write_text('#!/usr/bin/env bash\nif [[ "$1" == api ]]; then echo 123; fi\n')
    gh.chmod(0o755)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "commit-and-tag",
        version="0.2.0",
        APP_SLUG="release-test",
        TOKEN="test-token",
        MESSAGE="release 0.2.0",
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    assert result.returncode != 0
    assert run(repository, "git", "ls-remote", "origin", "refs/heads/main").stdout == before
    assert not run(repository, "git", "ls-remote", "origin", "refs/tags/0.2.0").stdout


def test_commit_and_tag_rejects_missing_token_without_remote_change(
    repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    assert action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0").returncode == 0
    before = run(repository, "git", "ls-remote", "origin", "refs/heads/main").stdout
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "commit-and-tag",
        version="0.2.0",
        APP_SLUG="release-test",
        TOKEN="",
        GH_TOKEN="ambient-test-token",  # ruff: ignore[hardcoded-password-func-arg]  # No token reaches GitHub.
    )
    assert result.returncode != 0
    assert "repository App token and slug are required" in result.stderr
    assert run(repository, "git", "ls-remote", "origin", "refs/heads/main").stdout == before
    assert not run(repository, "git", "ls-remote", "origin", "refs/tags/0.2.0").stdout

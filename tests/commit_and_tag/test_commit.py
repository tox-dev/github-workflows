from __future__ import annotations

import os
lazy from pathlib import Path

import pytest

from tests.conftest import action, run


@pytest.mark.parametrize("annotated", [pytest.param("false", id="lightweight"), pytest.param("true", id="annotated")])
def test_commit_and_tag_pushes_atomically(repository: Path, tmp_path: Path, annotated: str) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    assert action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0").returncode == 0
    gh = tmp_path / "gh"
    gh.write_text('#!/usr/bin/env bash\nif [[ "$1" == api ]]; then echo 123; fi\n')
    gh.chmod(0o755)
    result = action(
        repository,
        tmp_path,
        "commit-and-tag/commit.sh",
        version="0.2.0",
        APP_SLUG="release-test",
        GH_TOKEN="test-token",  # ruff: ignore[hardcoded-password-func-arg]  # Local Git fixture never sends this token.
        MESSAGE="release 0.2.0",
        ANNOTATED=annotated,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    assert result.returncode == 0, result.stderr
    assert run(repository, "git", "ls-remote", "origin", "refs/tags/0.2.0").stdout.strip()
    assert run(repository, "git", "cat-file", "-t", "refs/tags/0.2.0").stdout.strip() == (
        "tag" if annotated == "true" else "commit"
    )


def test_commit_and_tag_rejects_invalid_tag(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "add", "CHANGELOG.md")
    original_head = run(repository, "git", "rev-parse", "HEAD").stdout
    result = action(repository, tmp_path, "commit-and-tag/commit.sh", version="bad tag")
    assert result.returncode != 0
    assert "invalid release tag" in result.stderr
    assert run(repository, "git", "rev-parse", "HEAD").stdout == original_head


def test_commit_and_tag_rejects_empty_patch(repository: Path, tmp_path: Path) -> None:
    result = action(repository, tmp_path, "commit-and-tag/commit.sh", version="0.2.0")
    assert result.returncode != 0
    assert "expected only a staged release patch" in result.stderr


def test_commit_and_tag_rejects_unstaged_changes(repository: Path, tmp_path: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Staged release.\n")
    run(repository, "git", "add", "CHANGELOG.md")
    (repository / "CHANGELOG.md").write_text("Unstaged changes.\n")
    result = action(repository, tmp_path, "commit-and-tag/commit.sh", version="0.2.0")
    assert result.returncode != 0
    assert "expected only a staged release patch" in result.stderr


def test_commit_and_tag_rejects_invalid_annotated(repository: Path, tmp_path: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Staged release.\n")
    run(repository, "git", "add", "CHANGELOG.md")
    result = action(repository, tmp_path, "commit-and-tag/commit.sh", version="0.2.0", ANNOTATED="maybe")
    assert result.returncode != 0
    assert "annotated must be true or false" in result.stderr

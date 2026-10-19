from __future__ import annotations

from textwrap import dedent
lazy from pathlib import Path

from tests.conftest import action, run


def test_validate_applies_patch(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "0.2.0" in (repository / "CHANGELOG.md").read_text()
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout.strip()


def test_validate_rejects_stale_branch(repository: Path, tmp_path: Path) -> None:
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        "validate-release-patch/validate.sh",
        version="0.2.0",
        EXPECTED_SHA="0000000000000000000000000000000000000000",
    )
    assert result.returncode != 0
    assert "changed during release preparation" in result.stderr


def test_validate_rejects_dirty_checkout(repository: Path, tmp_path: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Changed before validation.\n")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "clean checkout" in result.stderr


def test_validate_rejects_noop_patch(repository: Path, tmp_path: Path) -> None:
    (tmp_path / "release.patch").write_text(
        dedent("""\
            diff --git a/CHANGELOG.md b/CHANGELOG.md
            --- a/CHANGELOG.md
            +++ b/CHANGELOG.md
            @@ -3 +3 @@
            -<!-- towncrier release notes start -->
            +<!-- towncrier release notes start -->
            """),
    )
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "release patch contains no changes" in result.stderr


def test_validate_rejects_unexpected_path(repository: Path, tmp_path: Path) -> None:
    (repository / "pyproject.toml").write_text((repository / "pyproject.toml").read_text() + "\n# changed\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "unexpected release path" in result.stderr


def test_validate_rejects_missing_heading(repository: Path, tmp_path: Path) -> None:
    (repository / "CHANGELOG.md").write_text("# Changelog\n\nOther notes.\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "has no section" in result.stderr


def test_validate_rejects_embedded_heading(repository: Path, tmp_path: Path) -> None:
    (repository / "CHANGELOG.md").write_text("# Changelog\n\n- Link to ## 0.2.0 (2026-10-19)\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0")
    assert result.returncode != 0
    assert "has no section" in result.stderr


def test_validate_rejects_prek_changes(repository: Path, tmp_path: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n"
        "        entry: bash -c 'if [[ $VALIDATE_REHEARSAL == 1 ]]; then printf changed >> CHANGELOG.md; fi'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Check release tree")
    run(repository, "git", "push", "origin", "main")
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0", VALIDATE_REHEARSAL="1")
    assert result.returncode != 0
    assert "prek failed" in result.stderr


def test_validate_rejects_untracked_prek_output(repository: Path, tmp_path: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n"
        "        entry: bash -c 'if [[ $VALIDATE_REHEARSAL == 1 ]]; then touch extra-output; fi'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Check release tree")
    run(repository, "git", "push", "origin", "main")
    assert action(repository, tmp_path, "prepare-towncrier/prepare.sh", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, "validate-release-patch/validate.sh", version="0.2.0", VALIDATE_REHEARSAL="1")
    assert result.returncode != 0
    assert "prek changed the validated release patch" in result.stderr

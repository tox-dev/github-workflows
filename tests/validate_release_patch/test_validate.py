from __future__ import annotations

from hashlib import sha256
from textwrap import dedent
lazy from pathlib import Path

import pytest
from conftest import action, run


def test_validate_applies_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "0.2.0" in (repository / "CHANGELOG.md").read_text()
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout.strip()


def test_validate_custom_remote_branch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    run(repository, "git", "remote", "add", "release-remote", str(tmp_path / "remote.git"))
    run(repository, "git", "push", "release-remote", "HEAD:release")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        BRANCH="release",
        REMOTE="release-remote",
        EXPECTED_SHA="",
    )
    assert result.returncode == 0, result.stderr
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout.strip()


def track_rst_changelog(repository: Path) -> None:
    (repository / "CHANGELOG.rst").write_text("Changelog\n=========\n")
    project = repository / "pyproject.toml"
    project.write_text(project.read_text().replace('filename = "CHANGELOG.md"', 'filename = "CHANGELOG.rst"'))
    run(repository, "git", "add", "CHANGELOG.rst", "pyproject.toml")
    run(repository, "git", "commit", "-m", "Track RST changelog")
    run(repository, "git", "push", "origin", "main")


@pytest.mark.parametrize(
    "heading",
    [
        pytest.param("0.2.0 (2026-10-20)", id="plain"),
        pytest.param("`0.2.0 <https://github.com/tox-dev/fixture/tree/0.2.0>`_ - 2026-10-20", id="linked"),
    ],
)
def test_validate_rst_heading(repository: Path, tmp_path: Path, action_scripts: Path, heading: str) -> None:
    changelog = repository / "CHANGELOG.rst"
    track_rst_changelog(repository)
    changelog.write_text(
        dedent("""\
            Changelog
            =========

            {heading}
            {underline}

            Changes
            =======

            - Add a feature.
            """).format(heading=heading, underline="=" * len(heading)),
    )
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0", CHANGELOG="CHANGELOG.rst"
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param("<<<<<<< HEAD", id="ours"),
        pytest.param("||||||| base", id="base"),
        pytest.param(">>>>>>> branch", id="theirs"),
    ],
)
def test_validate_rejects_rst_conflict_marker(
    repository: Path, tmp_path: Path, action_scripts: Path, marker: str
) -> None:
    changelog = repository / "CHANGELOG.rst"
    track_rst_changelog(repository)
    changelog.write_text(f"Changelog\n=========\n\n0.2.0\n=====\n\n{marker}\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0", CHANGELOG="CHANGELOG.rst"
    )
    assert result.returncode != 0
    assert "release changelog contains conflict markers" in result.stderr


def test_validate_rejects_unchanged_changelog(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    fragment = repository / "changelog.d/+feature.feature.md"
    fragment.unlink()
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "release patch does not change CHANGELOG.md" in result.stderr


def test_validate_rejects_stale_branch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        EXPECTED_SHA="0000000000000000000000000000000000000000",
    )
    assert result.returncode != 0
    assert "changed during release preparation" in result.stderr


def test_validate_rejects_dirty_checkout(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("Changed before validation.\n")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "clean checkout" in result.stderr


def test_validate_rejects_noop_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
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
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "release patch contains no changes" in result.stderr


def test_validate_rejects_changed_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        EXPECTED_PATCH_SHA="0" * 64,
    )
    assert result.returncode != 0
    assert "release patch differs from the validated artifact" in result.stderr


def test_validate_requires_digest_when_checks_skipped(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0", CHECKS="false")
    assert result.returncode != 0
    assert "skipping release checks requires a validated patch digest" in result.stderr


def test_validate_rejects_unknown_check_mode(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0", CHECKS="sometimes")
    assert result.returncode != 0
    assert "checks must be true or false" in result.stderr


def test_validate_key_job_uses_only_checked_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        CHECKS="false",
        EXPECTED_PATCH_SHA=sha256((tmp_path / "release.patch").read_bytes()).hexdigest(),
        PATH="/usr/bin:/bin",
    )
    assert result.returncode == 0, result.stderr
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout.strip()


def test_validate_rejects_unexpected_path(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "pyproject.toml").write_text((repository / "pyproject.toml").read_text() + "\n# changed\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "unexpected release path" in result.stderr


@pytest.mark.parametrize(
    "fragment",
    [
        pytest.param("evil.py", id="wrong-extension"),
        pytest.param("nested/7.feature.md", id="nested"),
        pytest.param("evil.feature.md", id="unsupported-stem"),
        pytest.param("7.bugfix.md", id="unconfigured-category"),
        pytest.param("7.feature.rst", id="wrong-format"),
    ],
)
def test_validate_rejects_unsupported_fragment_path(
    repository: Path, tmp_path: Path, action_scripts: Path, fragment: str
) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    path = repository / "changelog.d" / fragment
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Unexpected release fragment.\n")
    run(repository, "git", "add", str(path.relative_to(repository)))
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    run(repository, "git", "clean", "-fd")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        CHECKS="false",
        EXPECTED_PATCH_SHA=sha256((tmp_path / "release.patch").read_bytes()).hexdigest(),
    )
    assert result.returncode != 0
    assert "unsupported release fragment" in result.stderr


@pytest.mark.parametrize(
    "file_mode",
    [pytest.param("executable", id="executable"), pytest.param("symlink", id="symlink")],
)
def test_validate_rejects_unsafe_file_mode(
    repository: Path, tmp_path: Path, action_scripts: Path, file_mode: str
) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    if file_mode == "executable":
        (repository / "CHANGELOG.md").chmod(0o755)
    else:
        (repository / "changelog.d").mkdir(exist_ok=True)
        (repository / "changelog.d/+link.feature.md").symlink_to("../CHANGELOG.md")
        run(repository, "git", "add", "changelog.d/+link.feature.md")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "unexpected release file mode" in result.stderr


def test_validate_rejects_nonregular_deleted_fragment(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    fragment = repository / "changelog.d/7.feature.md"
    fragment.symlink_to("../CHANGELOG.md")
    run(repository, "git", "add", "changelog.d/7.feature.md")
    run(repository, "git", "commit", "-m", "Track linked fragment")
    run(repository, "git", "push", "origin", "main")
    (repository / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.0 (2026-10-21)\n\n- Add a feature.\n")
    fragment.unlink()
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        CHECKS="false",
        EXPECTED_PATCH_SHA=sha256((tmp_path / "release.patch").read_bytes()).hexdigest(),
    )
    assert result.returncode != 0
    assert "unexpected previous release file mode" in result.stderr


def test_validate_rejects_removed_changelog(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").unlink()
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "unexpected release file mode in CHANGELOG.md" in result.stderr


def test_validate_rejects_missing_heading(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("# Changelog\n\nOther notes.\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "has no valid section" in result.stderr


def test_validate_rejects_embedded_heading(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").write_text("# Changelog\n\n- Link to ## 0.2.0 (2026-10-19)\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "--binary").stdout)
    run(repository, "git", "restore", ".")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "has no valid section" in result.stderr


def test_validate_rejects_prek_changes(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n"
        "        entry: bash -c 'if [[ $VALIDATE_REHEARSAL == 1 ]]; then printf changed >> CHANGELOG.md; fi'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Check release tree")
    run(repository, "git", "push", "origin", "main")
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        VALIDATE_REHEARSAL="1",
    )
    assert result.returncode != 0
    assert "prek failed" in result.stderr


def test_validate_rejects_untracked_prek_output(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: release-check\n"
        "        name: release-check\n"
        "        entry: bash -c 'if [[ $VALIDATE_REHEARSAL == 1 ]]; then touch extra-output; fi'\n"
        "        language: system\n        pass_filenames: false\n",
    )
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Check release tree")
    run(repository, "git", "push", "origin", "main")
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
        VALIDATE_REHEARSAL="1",
    )
    assert result.returncode != 0
    assert "prek changed the validated release patch" in result.stderr

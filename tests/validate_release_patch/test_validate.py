from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from conftest import action, run


def test_validate_applies_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert "0.2.0" in (repository / "CHANGELOG.md").read_text()
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout.strip()


def test_validate_applies_patch_in_fresh_worktree(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    source_staged = run(repository, "git", "diff", "--cached", "--name-only").stdout
    validation = tmp_path / "validation"
    run(repository, "git", "worktree", "add", "--detach", str(validation), "HEAD")
    result = action(validation, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode == 0, result.stderr
    assert run(validation, "git", "diff", "--cached", "--name-only").stdout.strip()
    assert run(repository, "git", "diff", "--cached", "--name-only").stdout == source_staged


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
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode == 0, result.stderr


def test_validate_key_job_uses_only_checked_patch(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    assert action(repository, tmp_path, action_scripts, "prepare-towncrier", version="0.2.0").returncode == 0
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
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
        pytest.param("nested/7.feature.md", id="nested"),
        pytest.param("7.feature.md", id="added-valid-fragment"),
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
    )
    assert result.returncode != 0
    assert "unexpected release path status" in result.stderr


def test_validate_rejects_renamed_fragment_source(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    source = repository / "changelog.d/template.jinja"
    source.write_text("Add a feature.\n")
    run(repository, "git", "add", str(source.relative_to(repository)))
    run(repository, "git", "commit", "-m", "Track release template")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "mv", str(source.relative_to(repository)), "changelog.d/1.feature.md")
    (repository / "CHANGELOG.md").write_text("# Changelog\n\n## 0.2.0 (2026-10-22)\n\n- Add a feature.\n")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-release-patch",
        version="0.2.0",
    )
    assert result.returncode != 0
    assert "unexpected release path status" in result.stderr


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
        (repository / "CHANGELOG.md").unlink()
        (repository / "CHANGELOG.md").symlink_to("pyproject.toml")
        run(repository, "git", "add", "CHANGELOG.md")
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert ("unexpected release path" if file_mode == "symlink" else "unexpected release file mode") in result.stderr


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
    )
    assert result.returncode != 0
    assert "unexpected previous release file mode" in result.stderr


def test_validate_rejects_removed_changelog(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    (repository / "CHANGELOG.md").unlink()
    (tmp_path / "release.patch").write_text(run(repository, "git", "diff", "HEAD", "--binary").stdout)
    run(repository, "git", "reset", "--hard", "HEAD")
    result = action(repository, tmp_path, action_scripts, "validate-release-patch", version="0.2.0")
    assert result.returncode != 0
    assert "unexpected release path" in result.stderr

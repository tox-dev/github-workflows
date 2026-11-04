from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
from conftest import action, run

GH_STUB: Final[str] = "#!/usr/bin/env bash\necho 42\n"


@pytest.fixture
def gh_stub(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(GH_STUB)
    script.chmod(0o755)
    return bin_dir


@pytest.fixture
def plugin_repository(repository: Path) -> Path:
    (repository / "gradle.properties").write_text("pluginVersion=1.2.3\nkeep=yes\n")
    run(repository, "git", "add", "gradle.properties")
    run(repository, "git", "commit", "-m", "Add plugin version")
    return repository


def _prepare(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    gh_stub: Path,
    tag: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    outputs: dict[str, str] = {}
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "prepare-jetbrains-post-release",
        outputs,
        version=tag,
        TAG=tag,
        APP_SLUG="tox-dev-plugin-release",
        GITHUB_TOKEN="token",
        OUTPUT_DIR=str(tmp_path / "post-release"),
        PATH=f"{gh_stub}:{os.environ['PATH']}",
    )
    return result, outputs


def test_commits_next_patch_version_and_writes_manifest(
    action_scripts: Path,
    plugin_repository: Path,
    tmp_path: Path,
    gh_stub: Path,
) -> None:
    base = run(plugin_repository, "git", "rev-parse", "HEAD").stdout.strip()
    result, outputs = _prepare(plugin_repository, tmp_path, action_scripts, gh_stub, "v1.2.3")
    assert result.returncode == 0, result.stderr
    candidate = run(plugin_repository, "git", "rev-parse", "HEAD").stdout.strip()
    assert outputs == {
        "base-commit": base,
        "candidate-commit": candidate,
        "branch": "post-release-v1.2.3",
        "next-version": "1.2.4-dev",
    }
    assert (plugin_repository / "gradle.properties").read_text() == "pluginVersion=1.2.4-dev\nkeep=yes\n"
    blob = run(plugin_repository, "git", "rev-parse", "HEAD:gradle.properties").stdout.strip()
    post_release = tmp_path / "post-release"
    assert (post_release / "paths.tsv").read_text() == f"gradle.properties\t{blob}\n"
    assert (post_release / "body.md").read_text() == "Set the next development version after v1.2.3.\n"
    assert (post_release / "candidate.bundle").is_file()
    assert run(plugin_repository, "git", "log", "-1", "--format=%an <%ae>%n%s").stdout.splitlines() == [
        "tox-dev-plugin-release[bot] <42+tox-dev-plugin-release[bot]@users.noreply.github.com>",
        "Bump version to 1.2.4-dev after v1.2.3",
    ]


def test_leaves_candidate_empty_when_version_already_matches(
    action_scripts: Path,
    plugin_repository: Path,
    tmp_path: Path,
    gh_stub: Path,
) -> None:
    (plugin_repository / "gradle.properties").write_text("pluginVersion=1.2.4-dev\n")
    run(plugin_repository, "git", "commit", "-am", "Already bumped")
    result, outputs = _prepare(plugin_repository, tmp_path, action_scripts, gh_stub, "v1.2.3")
    assert result.returncode == 0, result.stderr
    assert outputs["candidate-commit"] == ""
    assert not (tmp_path / "post-release/candidate.bundle").exists()


@pytest.mark.parametrize("tag", ["v1.2.3-beta.1", "1.2", "v1.2.3.4"])
def test_rejects_tags_without_plain_patch_version(
    action_scripts: Path,
    plugin_repository: Path,
    tmp_path: Path,
    gh_stub: Path,
    tag: str,
) -> None:
    result, outputs = _prepare(plugin_repository, tmp_path, action_scripts, gh_stub, tag)
    assert result.returncode != 0
    assert outputs == {}

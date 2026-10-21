from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import action, run


def test_validator_uses_locked_metadata_group() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    check = next(
        step for step in workflow["jobs"]["validate"]["steps"] if step.get("uses") == "$/validate-python-distribution"
    )
    assert workflow["on"]["workflow_call"]["inputs"]["validation-group"]["default"] == "pkg-meta"
    assert check["with"]["validation-group"] == "${{ inputs.validation-group }}"
    assert set(workflow["jobs"]) == {"source-check", "validate"}


def test_pr_rehearsal_checks_out_exact_head_and_uses_candidate_version() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    for job in workflow["jobs"].values():
        assert job["steps"][0]["with"]["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    steps = workflow["jobs"]["validate"]["steps"]
    assert workflow["jobs"]["validate"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    verify = next(step for step in steps if step.get("name") == "Verify the exact release tag")
    assert verify["if"] == "github.event_name != 'pull_request'"
    candidate = next(step for step in steps if step.get("id") == "candidate")
    assert candidate["if"] == "github.event_name == 'pull_request'"
    assert candidate["uses"] == "$/prepare-towncrier"
    validate = next(step for step in steps if step.get("uses") == "$/validate-release-patch")
    assert validate["with"]["expected-sha"] == "${{ steps.fixture.outputs.sha }}"
    render = next(step for step in steps if step.get("uses") == "$/render-release-notes")
    assert render["with"]["tag"] == "${{ steps.candidate.outputs.version || github.ref_name }}"


def test_pr_rehearsal_builds_a_local_tag(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    steps = workflow["jobs"]["validate"]["steps"]
    fixture = next(step for step in steps if step.get("name") == "Squash pull request with a validation fragment")
    remote = next(step for step in steps if step.get("name") == "Create the local release remote")
    tag = next(step for step in steps if step.get("name") == "Tag the local release candidate")
    head = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    base = run(repository, "git", "rev-parse", "HEAD^").stdout.strip()
    environment = os.environ | {
        "BASE_SHA": base,
        "HEAD_SHA": head,
        "PR_NUMBER": "2",
        "FRAGMENTS": "changelog.d",
        "CHANGELOG": "CHANGELOG.md",
        "FORMAT": "markdown",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "fixture-output"),
    }
    prepared = subprocess.run(
        ["bash", "-c", fixture["run"]], cwd=repository, env=environment, capture_output=True, text=True, check=False
    )
    assert prepared.returncode == 0, prepared.stderr
    source = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    created = subprocess.run(
        ["bash", "-c", remote["run"]], cwd=repository, env=environment, capture_output=True, text=True, check=False
    )
    assert created.returncode == 0, created.stderr
    assert (
        action(
            repository,
            tmp_path,
            action_scripts,
            "prepare-towncrier",
            version="",
            FORMAT="none",
            LINK_FRAGMENTS="true",
            GITHUB_REPOSITORY="tox-dev/github-workflows",
            REPOSITORY="tox-dev/github-workflows",
            PATCH=str(tmp_path / "release-validation.patch"),
        ).returncode
        == 0
    )
    version = (tmp_path / "output").read_text().split("version=", 1)[1].splitlines()[0]
    run(repository, "git", "reset", "--hard", "HEAD")
    assert (
        action(
            repository,
            tmp_path,
            action_scripts,
            "validate-release-patch",
            version=version,
            PATCH=str(tmp_path / "release-validation.patch"),
            BRANCH="release-validation",
            REMOTE="release-validation-origin",
            EXPECTED_SHA=source,
            GITHUB_REPOSITORY="tox-dev/github-workflows",
            REPOSITORY="tox-dev/github-workflows",
        ).returncode
        == 0
    )
    tagged = subprocess.run(
        ["bash", "-c", tag["run"]],
        cwd=repository,
        env=environment | {"VERSION": version},
        capture_output=True,
        text=True,
        check=False,
    )
    assert tagged.returncode == 0, tagged.stderr
    assert (
        run(repository, "git", "rev-parse", f"refs/tags/{version}^{{commit}}").stdout.strip()
        == run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    )
    assert version in (repository / "CHANGELOG.md").read_text()


def test_pr_rehearsal_rejects_a_changed_head(repository: Path, tmp_path: Path) -> None:
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    fixture = next(
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("name") == "Squash pull request with a validation fragment"
    )
    result = subprocess.run(
        ["bash", "-c", fixture["run"]],
        cwd=repository,
        env=os.environ
        | {
            "BASE_SHA": run(repository, "git", "rev-parse", "HEAD^").stdout.strip(),
            "HEAD_SHA": "0" * 40,
            "PR_NUMBER": "11",
            "FRAGMENTS": "changelog.d",
            "CHANGELOG": "CHANGELOG.md",
            "FORMAT": "markdown",
            "RUNNER_TEMP": str(tmp_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert run(repository, "git", "rev-parse", "HEAD").stdout.strip() != "0" * 40


@pytest.mark.parametrize(
    ("tag_kind", "event_ref", "accepted"),
    [
        pytest.param("lightweight", "refs/tags/0.2.0", True, id="lightweight-tag"),
        pytest.param("annotated", "refs/tags/0.2.0", True, id="annotated-tag"),
        pytest.param("branch", "refs/tags/0.2.0", False, id="same-name-branch"),
        pytest.param("lightweight", "refs/heads/main", False, id="branch-event"),
    ],
)
def test_validator_requires_exact_tag(repository: Path, tag_kind: str, event_ref: str, accepted: bool) -> None:
    if tag_kind == "branch":
        run(repository, "git", "branch", "0.2.0")
    elif tag_kind == "annotated":
        run(repository, "git", "tag", "-a", "-m", "Release", "0.2.0")
    else:
        run(repository, "git", "tag", "0.2.0")
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    verify = next(
        step for step in workflow["jobs"]["validate"]["steps"] if step.get("name") == "Verify the exact release tag"
    )
    result = subprocess.run(
        ["bash", "-c", verify["run"]],
        cwd=repository,
        env=os.environ | {"GITHUB_REF": event_ref, "TAG": "0.2.0"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr

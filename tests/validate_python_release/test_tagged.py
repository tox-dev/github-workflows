from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import run


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

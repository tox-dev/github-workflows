from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import run


def test_validator_isolates_release_tools_from_build() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]["workflow_call"]["inputs"]) == {
        "source",
        "artifact-prefix",
        "changelog",
        "artifact-base-url",
        "artifact-label",
        "local-tool-source",
    }
    assert set(workflow["jobs"]) == {"source-check", "constraints", "build", "validate"}
    assert workflow["jobs"]["build"]["needs"] == "constraints"
    assert not any(step.get("uses", "").startswith("$/install-") for step in workflow["jobs"]["build"]["steps"])
    assert workflow["jobs"]["validate"]["needs"] == "build"
    assert any(step.get("uses") == "$/install-locked-tools" for step in workflow["jobs"]["validate"]["steps"])


@pytest.mark.parametrize(
    ("tag_kind", "event_ref", "accepted"),
    [
        pytest.param("lightweight", "refs/tags/0.2.0", True, id="lightweight-tag"),
        pytest.param("annotated", "refs/tags/0.2.0", True, id="annotated-tag"),
        pytest.param("lightweight", "refs/heads/0.2.0", False, id="branch-event-on-tagged-commit"),
        pytest.param("branch", "refs/tags/0.2.0", False, id="same-name-branch"),
        pytest.param("off-main", "refs/tags/0.2.0", False, id="tagged-off-main-commit"),
    ],
)
def test_validator_requires_exact_tag(repository: Path, tag_kind: str, event_ref: str, accepted: bool) -> None:
    if tag_kind == "branch":
        run(repository, "git", "branch", "0.2.0")
    elif tag_kind == "off-main":
        run(repository, "git", "switch", "-c", "release-candidate")
        run(repository, "git", "commit", "--allow-empty", "-m", "Unmerged change")
        run(repository, "git", "tag", "0.2.0")
    elif tag_kind == "annotated":
        run(repository, "git", "tag", "-a", "-m", "Release", "0.2.0")
    else:
        run(repository, "git", "tag", "0.2.0")
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    verify = next(
        step for step in workflow["jobs"]["build"]["steps"] if step.get("name") == "Verify the exact release tag"
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


@pytest.mark.parametrize(
    ("tag", "filenames", "accepted"),
    [
        pytest.param("1.2.3", ("example-1.2.3-py3-none-any.whl", "example-1.2.3.tar.gz"), True, id="matching"),
        pytest.param("v1.2.3", ("example-1.2.3-py3-none-any.whl", "example-1.2.3.tar.gz"), True, id="v-prefix"),
        pytest.param("1.2.3", ("example-1.2.4-py3-none-any.whl", "example-1.2.3.tar.gz"), False, id="wrong-wheel"),
        pytest.param("1.2.3", ("example-1.2.3-py3-none-any.whl", "example-1.2.4.tar.gz"), False, id="wrong-sdist"),
        pytest.param(
            "1.2.3",
            ("example-1.2.3-py3-none-any.whl", "example-1.2.3.tar.gz", "unexpected.txt"),
            False,
            id="extra-file",
        ),
    ],
)
def test_validator_matches_built_version_to_tag(
    tmp_path: Path, tag: str, filenames: tuple[str, ...], accepted: bool
) -> None:
    (tmp_path / "dist").mkdir()
    for filename in filenames:
        (tmp_path / "dist" / filename).touch()
    workflow = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )
    check = next(
        step for step in workflow["jobs"]["build"]["steps"] if step.get("name") == "Match distribution version to tag"
    )
    result = subprocess.run(
        ["bash", "-c", check["run"]],
        cwd=tmp_path,
        env=os.environ | {"TAG": tag},
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr

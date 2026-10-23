from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import run


@pytest.fixture(scope="module")
def release_workflow() -> dict[str, Any]:
    return yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text()
    )


def run_release_step(
    workflow: dict[str, Any], job: str, name: str, repository: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    step = next(item for item in workflow["jobs"][job]["steps"] if item.get("name") == name)
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=repository,
        env=os.environ | environment,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture
def build_constraints(build_repository: Path, tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    path = tmp_path / "build-constraints.txt"
    result = subprocess.run(
        [sys.executable, str(source / "tools/build_constraints.py"), str(path), str(build_repository / "pylock.toml")],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return path


def test_validator_isolates_release_tools_from_build() -> None:
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/validate-python-release.yaml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]["workflow_call"]["inputs"]) == {"source", "artifact-prefix"}
    assert set(workflow["jobs"]) == {"source-check", "constraints", "build", "validate"}
    assert workflow["jobs"]["build"]["needs"] == "constraints"
    assert not any(step.get("uses", "").startswith("$/install-") for step in workflow["jobs"]["build"]["steps"])
    assert workflow["jobs"]["validate"]["needs"] == "build"
    assert not any(step.get("uses") == "$/install-locked-tools" for step in workflow["jobs"]["validate"]["steps"])
    validator = next(
        step for step in workflow["jobs"]["validate"]["steps"] if step.get("name") == "Install distribution validators"
    )
    assert "twine>=7" in validator["run"]
    assert "check-wheel-contents>=0.6.3" in validator["run"]


def test_validator_builds_reproducible_distributions_and_checks_them(
    build_repository: Path, build_constraints: Path, tmp_path: Path, release_workflow: dict[str, Any]
) -> None:
    assert "hatchling==" in build_constraints.read_text()
    environment = {"RUNNER_TEMP": str(tmp_path), "SOURCE": "."}
    interpreter = run_release_step(
        release_workflow, "build", "Select build interpreter", build_repository, **environment
    )
    assert interpreter.returncode == 0, interpreter.stderr
    outputs: list[dict[str, bytes]] = []
    for _ in range(2):
        result = run_release_step(release_workflow, "build", "Build wheel and sdist", build_repository, **environment)
        assert result.returncode == 0, result.stderr
        outputs.append(
            {path.name: path.read_bytes() for path in (build_repository / "dist").iterdir() if path.suffix != ""}
        )
        shutil.rmtree(build_repository / "dist")
    assert set(outputs[0]) == {"fixture-0.2.0-py3-none-any.whl", "fixture-0.2.0.tar.gz"}
    assert outputs[0] == outputs[1]
    for name, content in outputs[0].items():
        path = build_repository / "dist" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    validators = run_release_step(
        release_workflow, "validate", "Install distribution validators", build_repository, **environment
    )
    assert validators.returncode == 0, validators.stderr
    for name in ("Check distribution metadata", "Check wheel contents"):
        result = run_release_step(release_workflow, "validate", name, build_repository, **environment)
        assert result.returncode == 0, result.stderr


def test_validator_rejects_nonempty_distribution_directory(tmp_path: Path, release_workflow: dict[str, Any]) -> None:
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "old.whl").write_bytes(b"old")
    result = run_release_step(release_workflow, "build", "Require empty distribution directory", tmp_path)
    assert result.returncode != 0


def test_validator_rejects_backend_hash_mismatch(
    build_repository: Path, build_constraints: Path, tmp_path: Path, release_workflow: dict[str, Any]
) -> None:
    lines = build_constraints.read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith("hatchling=="):
            lines[index] = " ".join(
                "--hash=sha256:" + "0" * 64 if part.startswith("--hash=sha256:") else part for part in line.split()
            )
    build_constraints.write_text("\n".join(lines) + "\n")
    environment = {"RUNNER_TEMP": str(tmp_path), "SOURCE": ".", "UV_CACHE_DIR": str(tmp_path / "uv-cache")}
    interpreter = run_release_step(
        release_workflow, "build", "Select build interpreter", build_repository, **environment
    )
    assert interpreter.returncode == 0, interpreter.stderr
    result = run_release_step(release_workflow, "build", "Build wheel and sdist", build_repository, **environment)
    assert result.returncode != 0
    assert "Hash mismatch" in result.stderr


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

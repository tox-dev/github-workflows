from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

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


def test_release_workflow_leaves_distribution_checks_to_the_package(release_workflow: dict[str, Any]) -> None:
    assert set(release_workflow["jobs"]) == {"build"}


def test_build_exports_constraints_after_checking_the_tag(release_workflow: dict[str, Any]) -> None:
    names = [step.get("name", step.get("uses", "")) for step in release_workflow["jobs"]["build"]["steps"]]

    assert names.index("Verify the exact release tag") < names.index("$/install-locked-tools")
    assert names.index("$/install-locked-tools") < names.index("Build wheel and sdist")


def test_validator_builds_reproducible_distributions(
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
        pytest.param("branch", "refs/tags/0.2.0", False, id="same-name-branch"),
        pytest.param("off-main", "refs/tags/0.2.0", False, id="tagged-off-main-commit"),
    ],
)
@pytest.mark.parametrize(
    "location",
    [
        pytest.param("check-tagged-source/action.yml", id="source-check"),
        pytest.param("validate-python-release:build", id="build"),
        pytest.param("release:source", id="self-release"),
    ],
)
def test_validator_requires_exact_tag(
    repository: Path, tag_kind: str, event_ref: str, accepted: bool, location: str
) -> None:
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
    verify = _tag_check(location)
    result = subprocess.run(
        ["bash", "-c", verify["run"]],
        cwd=repository,
        env=os.environ
        | {
            "GITHUB_REF": event_ref,
            "TAG": "0.2.0",
            "GITHUB_SHA": run(repository, "git", "rev-parse", "HEAD").stdout.strip(),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted, result.stderr


@pytest.mark.parametrize(
    ("location", "accepted"),
    [
        pytest.param("check-tagged-source/action.yml", True, id="source-check"),
        pytest.param("validate-python-release:build", False, id="build"),
        pytest.param("release:source", False, id="self-release"),
    ],
)
def test_validator_branch_event_on_tagged_commit(repository: Path, location: str, *, accepted: bool) -> None:
    run(repository, "git", "tag", "0.2.0")

    result = _run_tag_check(repository, location, "refs/heads/main", run(repository, "git", "rev-parse", "HEAD").stdout)

    assert (result.returncode == 0) is accepted, result.stderr


def test_source_check_rejects_dispatch_off_the_tag(repository: Path) -> None:
    run(repository, "git", "tag", "0.2.0")
    run(repository, "git", "commit", "--allow-empty", "-m", "Later change")
    run(repository, "git", "push", "origin", "main")

    result = _run_tag_check(
        repository,
        "check-tagged-source/action.yml",
        "refs/heads/main",
        run(repository, "git", "rev-parse", "HEAD").stdout,
    )

    assert result.returncode != 0


def test_source_check_reads_the_dispatched_tag() -> None:
    assert (
        _tag_check("check-tagged-source/action.yml")["env"]["TAG"]
        == "${{ github.event.inputs.tag || github.ref_name }}"
    )


def _run_tag_check(repository: Path, location: str, event_ref: str, event_sha: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", _tag_check(location)["run"]],
        cwd=repository,
        env=os.environ | {"GITHUB_REF": event_ref, "TAG": "0.2.0", "GITHUB_SHA": event_sha.strip()},
        text=True,
        capture_output=True,
        check=False,
    )


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


@pytest.mark.parametrize(
    "location",
    ["check-tagged-source/action.yml", "validate-python-release:build", "release:source"],
    ids=["source-check", "build", "self-release"],
)
def test_validator_requires_tag_at_the_event_commit(repository: Path, location: str) -> None:
    run(repository, "git", "tag", "0.2.0")
    event_commit = run(repository, "git", "rev-parse", "HEAD").stdout.strip()
    run(repository, "git", "commit", "--allow-empty", "-m", "Later change")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "tag", "-f", "0.2.0")

    result = subprocess.run(
        ["bash", "-c", _tag_check(location)["run"]],
        cwd=repository,
        env=os.environ | {"GITHUB_REF": "refs/tags/0.2.0", "TAG": "0.2.0", "GITHUB_SHA": event_commit},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0


def _tag_check(location: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    if location.endswith(".yml"):
        steps = yaml.safe_load((root / location).read_text())["runs"]["steps"]
    else:
        workflow, job = location.split(":")
        steps = yaml.safe_load((root / ".github/workflows" / f"{workflow}.yaml").read_text())["jobs"][job]["steps"]
    return cast("dict[str, Any]", next(step for step in steps if step.get("name") == "Verify the exact release tag"))

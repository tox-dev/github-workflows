from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


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


def test_build_exports_constraints_before_building(release_workflow: dict[str, Any]) -> None:
    names = [step["name"] for step in release_workflow["jobs"]["build"]["steps"]]

    assert names.index("📦 Export locked build constraints") < names.index("🏗️ Build wheel and sdist")


def test_validator_builds_reproducible_distributions(
    build_repository: Path, build_constraints: Path, tmp_path: Path, release_workflow: dict[str, Any]
) -> None:
    assert "hatchling==" in build_constraints.read_text()
    environment = {"RUNNER_TEMP": str(tmp_path), "SOURCE": "."}
    interpreter = run_release_step(
        release_workflow, "build", "🐍 Select build interpreter", build_repository, **environment
    )
    assert interpreter.returncode == 0, interpreter.stderr
    outputs: list[dict[str, bytes]] = []
    for _ in range(2):
        result = run_release_step(release_workflow, "build", "🏗️ Build wheel and sdist", build_repository, **environment)
        assert result.returncode == 0, result.stderr
        outputs.append(
            {path.name: path.read_bytes() for path in (build_repository / "dist").iterdir() if path.suffix != ""}
        )
        shutil.rmtree(build_repository / "dist")
    assert set(outputs[0]) == {"fixture-0.2.0-py3-none-any.whl", "fixture-0.2.0.tar.gz"}
    assert outputs[0] == outputs[1]


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
        release_workflow, "build", "🐍 Select build interpreter", build_repository, **environment
    )
    assert interpreter.returncode == 0, interpreter.stderr
    result = run_release_step(release_workflow, "build", "🏗️ Build wheel and sdist", build_repository, **environment)
    assert result.returncode != 0
    assert "Hash mismatch" in result.stderr

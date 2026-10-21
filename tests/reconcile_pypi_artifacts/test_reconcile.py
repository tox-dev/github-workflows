from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import pytest
import yaml
from conftest import run


def execute(script: Path, directory: Path, **settings: str) -> subprocess.CompletedProcess[str]:
    command = ["bash", str(script)]
    if (coverage_binary := os.getenv("KCOV_BIN")) is not None:
        output = Path(os.environ["KCOV_OUTPUT"])
        output.mkdir(parents=True, exist_ok=True)
        command = [coverage_binary, f"--include-path={script.parent}", str(output / uuid4().hex), str(script)]
    return subprocess.run(
        command,
        cwd=directory,
        env=os.environ | settings,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture
def distribution(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "codex_fixture_never_publish-999999-py3-none-any.whl").write_bytes(b"release fixture")
    return dist


def test_stage_selects_missing_artifact(distribution: Path, tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    environment = {
        "PROJECT": "codex-fixture-never-publish",
        "VERSION": "999999",
        "DIST": str(distribution),
        "MODE": "stage",
        "LOCK": str(source / "pylock.toml"),
        "PYTHON_VERSION": "3.15",
        "LOCAL_TOOL_SOURCE": "false",
        "RUNNER_TEMP": str(tmp_path),
        "MISSING_DIR": str(tmp_path / "missing"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
    for index in range(4):
        result = execute(action_scripts / f"reconcile-pypi-artifacts-{index}.sh", source, **environment)
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text().splitlines() == [
        "missing_count=1",
        f"path={tmp_path}/pypi-missing-names.txt",
    ]
    assert (tmp_path / "missing" / next(distribution.iterdir()).name).read_bytes() == b"release fixture"
    assert (tmp_path / "pypi-missing-names.txt").read_text() == f"{next(distribution.iterdir()).name}\n"


@pytest.mark.parametrize("mode", ["invalid", "verify"])
def test_invalid_input_fails_before_install(
    distribution: Path, tmp_path: Path, action_scripts: Path, mode: str
) -> None:
    result = execute(
        action_scripts / "reconcile-pypi-artifacts-0.sh",
        tmp_path,
        PROJECT="codex-fixture-never-publish",
        VERSION="999999",
        DIST=str(distribution if mode == "invalid" else tmp_path / "missing"),
        MODE=mode,
    )
    assert result.returncode != 0


def test_verify_checks_complete_pypi_release(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    install = execute(
        action_scripts / "reconcile-pypi-artifacts-1.sh",
        source,
        RUNNER_TEMP=str(tmp_path),
        LOCK=str(source / "pylock.toml"),
        PYTHON_VERSION="3.15",
        LOCAL_TOOL_SOURCE="false",
    )
    assert install.returncode == 0, install.stderr
    with urlopen("https://pypi.org/pypi/release-creator/0.4.1/json", timeout=30) as response:
        payload = json.load(response)
    dist = tmp_path / "dist"
    dist.mkdir()
    for item in payload["urls"]:
        with urlopen(item["url"], timeout=30) as response:
            (dist / item["filename"]).write_bytes(response.read())
    result = execute(
        action_scripts / "reconcile-pypi-artifacts-4.sh",
        tmp_path,
        RUNNER_TEMP=str(tmp_path),
        PROJECT="release-creator",
        VERSION="0.4.1",
        DIST=str(dist),
        WAIT_SECONDS="0",
    )
    assert result.returncode == 0, result.stderr


def test_local_source_install_uses_checked_out_project(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    with (source / "pyproject.toml").open("rb") as stream:
        pinned = tomllib.load(stream)["dependency-groups"]["release"][0].rsplit("@", 1)[-1]
    project = tmp_path / "release-creator"
    run(tmp_path, "git", "clone", "--quiet", "https://github.com/tox-dev/release-creator", str(project))
    run(project, "git", "checkout", "--quiet", pinned)
    result = execute(
        action_scripts / "reconcile-pypi-artifacts-1.sh",
        project,
        RUNNER_TEMP=str(tmp_path),
        LOCK=str(project / "pylock.toml"),
        PYTHON_VERSION="3.15",
        LOCAL_TOOL_SOURCE="true",
    )
    assert result.returncode == 0, result.stderr
    version = run(tmp_path, str(tmp_path / "pypi-reconcile/bin/release-creator"), "--help").stdout
    assert "artifacts" in version
    workflow = yaml.safe_load((source / ".github/workflows/prepare-towncrier-release.yaml").read_text())
    for job in ("assemble", "validate"):
        for step in workflow["jobs"][job]["steps"]:
            if step.get("name") in {"Install locked release tools", "Install the tagged release tool"}:
                script = tmp_path / "prepare-install.sh"
                script.write_text(step["run"])
                result = execute(
                    script,
                    project,
                    PYTHON_VERSION="3.15",
                    LOCK=str(project / "pylock.toml"),
                    GITHUB_PATH=str(tmp_path / "path"),
                )
                assert result.returncode == 0, result.stderr
        assert "artifacts" in run(project, str(project / ".venv/bin/release-creator"), "--help").stdout

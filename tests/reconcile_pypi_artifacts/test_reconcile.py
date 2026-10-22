from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from urllib.request import urlopen

import pytest
import yaml
from conftest import run


def execute(script: Path, directory: Path, **settings: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=directory,
        env=os.environ
        | {"GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "reconcile-pypi-artifacts")}
        | settings,
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
    result = execute(action_scripts / "reconcile-pypi-artifacts-0.sh", source, **environment)
    assert result.returncode == 0, result.stderr
    install_reconcile(action_scripts, source, tmp_path)
    for index in (3, 4):
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
    install_reconcile(action_scripts, source, tmp_path)
    with urlopen("https://pypi.org/pypi/release-creator/0.4.1/json", timeout=30) as response:
        payload = json.load(response)
    dist = tmp_path / "dist"
    dist.mkdir()
    for item in payload["urls"]:
        with urlopen(item["url"], timeout=30) as response:
            (dist / item["filename"]).write_bytes(response.read())
    result = execute(
        action_scripts / "reconcile-pypi-artifacts-5.sh",
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
    with (source / "pylock.toml").open("rb") as stream:
        version = next(
            item["version"] for item in tomllib.load(stream)["packages"] if item["name"] == "release-creator"
        )
    project = tmp_path / "release-creator"
    run(tmp_path, "git", "clone", "--quiet", "https://github.com/tox-dev/release-creator", str(project))
    run(project, "git", "checkout", "--quiet", version)
    install_reconcile(action_scripts, project, tmp_path, local_source=True)
    version = run(tmp_path, str(tmp_path / "pypi-reconcile/bin/release-creator"), "--help").stdout
    assert "artifacts" in version
    workflow = yaml.safe_load((source / ".github/workflows/prepare-towncrier-release.yaml").read_text())
    for job in ("assemble", "validate"):
        runner_temp = tmp_path / job
        runner_temp.mkdir()
        steps = workflow["jobs"][job]["steps"]
        assert any(step.get("uses") == "$/install-locked-tools" for step in steps)
        install_locked_tools(
            action_scripts, project, runner_temp, project / ".venv", "release fix build project-runtime"
        )
        script = tmp_path / "prepare-install.sh"
        script.write_text(next(step["run"] for step in steps if step.get("name") == "Install the tagged release tool"))
        result = execute(script, project)
        assert result.returncode == 0, result.stderr
        assert "artifacts" in run(project, str(project / ".venv/bin/release-creator"), "--help").stdout
        shutil.rmtree(project / ".venv")


def install_reconcile(action_scripts: Path, repository: Path, tmp_path: Path, *, local_source: bool = False) -> None:
    install_locked_tools(
        action_scripts,
        repository,
        tmp_path,
        tmp_path / "pypi-reconcile",
        "release build project-runtime" if local_source else "release",
    )
    if local_source:
        result = execute(
            action_scripts / "reconcile-pypi-artifacts-2.sh",
            repository,
            RUNNER_TEMP=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr


def install_locked_tools(action_scripts: Path, repository: Path, runner_temp: Path, venv: Path, groups: str) -> None:
    source = Path(__file__).resolve().parents[2]
    for index in range(3):
        result = execute(
            action_scripts / f"install-locked-tools-{index}.sh",
            repository,
            LOCK=str(repository / "pylock.toml"),
            DEPENDENCY_GROUPS=groups,
            PYTHON_VERSION="3.15",
            RUNNER_TEMP=str(runner_temp),
            VENV=str(venv),
            GITHUB_ACTION_PATH=str(source / "install-locked-tools"),
        )
        assert result.returncode == 0, result.stderr

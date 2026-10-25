from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest
import yaml
from conftest import action, run

_STEPS: Final = yaml.safe_load((Path(__file__).resolve().parents[2] / "refresh-release-lock/action.yml").read_text())[
    "runs"
]["steps"]
_LOCK: Final = (
    'lock-version = "1.0"\ncreated-by = "nab"\nrequires-python = ">=3.15"\npackages = []\n'
    'environments = ["python_version == \\"3.15\\""]\n[tool.nab]\ncreated-at = 2026-10-01T00:00:00Z\n'
)


@pytest.fixture
def fake_uv(tmp_path: Path) -> Path:
    executable = tmp_path / "bin/uv"
    executable.parent.mkdir()
    executable.write_text(
        f'#!{sys.executable}\nimport json, os, pathlib, sys\npathlib.Path(os.environ["RUNNER_TEMP"], "uv-call.json")'
        ".write_text(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ)}))\n"
    )
    executable.chmod(0o755)
    return executable


@pytest.fixture
def lock_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "0.1.0"\nrequires-python = ">=3.15"\ndependencies = []\n'
        '[dependency-groups]\nrelease = ["packaging"]\n'
        '[tool.nab]\nuploaded-prior-to = "P7D"\nbase-group = "project-runtime"\n'
    )
    run(project, "git", "init", "-b", "main")
    run(project, "git", "config", "user.name", "Release test")
    run(project, "git", "config", "user.email", "release@example.org")
    return project


def test_refresh_rejects_secondary_options_without_lock(tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "refresh-release-lock",
        version="",
        ADDITIONAL_LOCK_GROUPS="build",
    )

    assert result.returncode != 0
    assert "secondary matrix inputs require additional-lock" in result.stderr


@pytest.mark.parametrize(("mode", "upgrade"), [("check", []), ("refresh", ["--upgrade"])])
def test_refresh_locks_every_group_and_extra_with_nab(
    tmp_path: Path, action_scripts: Path, fake_uv: Path, mode: str, upgrade: list[str]
) -> None:
    (tmp_path / "pylock.toml").write_text(_LOCK)

    result = _run_step(action_scripts, "Resolve all project groups and extras", tmp_path, fake_uv, MODE=mode)

    assert result.returncode == 0, result.stderr
    call = _uv_call(tmp_path)
    assert call["argv"] == [
        "run",
        "--no-project",
        "--python",
        f"{tmp_path}/lock-tools",
        "nab",
        "lock",
        "--all-groups",
        "--all-extras",
        "--no-cache",
        *upgrade,
    ]


@pytest.mark.parametrize("step", ["Resolve all project groups and extras", "Resolve optional Nab matrix"])
def test_refresh_hides_certificate_overrides_from_nab(
    tmp_path: Path, action_scripts: Path, fake_uv: Path, step: str
) -> None:
    (tmp_path / "pylock.toml").write_text(_LOCK)
    (tmp_path / "pylock.build.toml").write_text(_LOCK)

    result = _run_step(
        action_scripts,
        step,
        tmp_path,
        fake_uv,
        MODE="check",
        ADDITIONAL_LOCK="pylock.build.toml",
        ADDITIONAL_GROUPS="",
        ADDITIONAL_SELECTION="build-or-groups",
        MATRIX_PYTHON=">=3.15",
        MATRIX_PLATFORMS="linux_x86_64",
        MATRIX_IMPLEMENTATIONS="cpython",
        SSL_CERT_FILE=str(tmp_path / "ca.pem"),
        SSL_CERT_DIR=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert not {"SSL_CERT_FILE", "SSL_CERT_DIR"} & _uv_call(tmp_path)["env"].keys()


def test_refresh_rejects_unknown_mode(tmp_path: Path, action_scripts: Path, fake_uv: Path) -> None:
    result = _run_step(action_scripts, "Resolve all project groups and extras", tmp_path, fake_uv, MODE="other")

    assert result.returncode != 0
    assert "invalid lock mode: other" in result.stderr


def test_refresh_check_accepts_current_lock(
    lock_project: Path, nab_executable: Path, tmp_path: Path, action_scripts: Path
) -> None:
    _commit_lock(lock_project, nab_executable)

    result = action(lock_project, tmp_path, action_scripts, "refresh-release-lock", version="", MODE="check")

    assert result.returncode == 0, result.stderr
    assert run(lock_project, "git", "status", "--porcelain").stdout == ""


def test_refresh_check_rejects_stale_lock(
    lock_project: Path, nab_executable: Path, tmp_path: Path, action_scripts: Path
) -> None:
    _commit_lock(lock_project, nab_executable)
    project = lock_project / "pyproject.toml"
    project.write_text(project.read_text().replace("dependencies = []", 'dependencies = ["six"]'))

    result = action(lock_project, tmp_path, action_scripts, "refresh-release-lock", version="", MODE="check")

    assert result.returncode != 0
    assert "regenerated Nab lock differs from the committed lock" in result.stderr


def test_refresh_writes_patch_for_stale_lock(
    lock_project: Path, nab_executable: Path, tmp_path: Path, action_scripts: Path
) -> None:
    _commit_lock(lock_project, nab_executable)
    project = lock_project / "pyproject.toml"
    project.write_text(project.read_text().replace("dependencies = []", 'dependencies = ["six"]'))
    outputs: dict[str, str] = {}

    result = action(lock_project, tmp_path, action_scripts, "refresh-release-lock", outputs, version="", MODE="refresh")

    assert result.returncode == 0, result.stderr
    assert outputs["changed"] == "true"
    patch = (tmp_path / "lock.patch").read_text()
    assert "diff --git a/pylock.toml b/pylock.toml" in patch
    assert 'name = "six"' in patch
    assert "diff --git a/pyproject.toml" not in patch


def _commit_lock(project: Path, nab: Path) -> None:
    result = subprocess.run(
        [str(nab), "lock", "--all-groups", "--all-extras", "--no-cache"],
        cwd=project,
        env={name: value for name, value in os.environ.items() if not name.startswith("SSL_CERT")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    run(project, "git", "add", ".")
    run(project, "git", "commit", "-m", "Lock the project")


def _run_step(
    action_scripts: Path, name: str, root: Path, fake_uv: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    index = next(index for index, step in enumerate(_STEPS) if step.get("name") == name)
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", str(action_scripts / f"refresh-release-lock-{index}.sh")],
        cwd=root,
        env=os.environ
        | {
            "PATH": f"{fake_uv.parent}{os.pathsep}{os.environ['PATH']}",
            "RUNNER_TEMP": str(root),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "refresh-release-lock"),
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _uv_call(root: Path) -> dict[str, Any]:
    return json.loads((root / "uv-call.json").read_text())


def test_refresh_installs_nab_under_cutoff(lock_project: Path, tmp_path: Path, action_scripts: Path) -> None:
    run(lock_project, "git", "add", ".")
    run(lock_project, "git", "commit", "-m", "Add the project")

    result = action(
        lock_project,
        tmp_path,
        action_scripts,
        "refresh-release-lock",
        version="",
        EXCLUDE_NEWER="2026-10-01T00:00:00Z",
        EXCLUDE_NEWER_PACKAGE="",
    )

    assert result.returncode != 0
    assert "nab>=0.0.22" in result.stderr


@pytest.mark.parametrize("commit", ["abc123", "g" * 40, "a" * 41], ids=["short", "not-hex", "long"])
def test_refresh_rejects_invalid_nab_commit(tmp_path: Path, action_scripts: Path, commit: str) -> None:
    result = action(tmp_path, tmp_path, action_scripts, "refresh-release-lock", version="", NAB_GIT_COMMIT=commit)

    assert result.returncode != 0
    assert "nab-git-commit must be a full 40-character commit SHA" in result.stderr


_NAB_COMMIT: Final = "0123456789abcdef0123456789abcdef01234567"
_NAB_SOURCE: Final = f"git+https://github.com/notatallshaw/nab@{_NAB_COMMIT}"


@pytest.mark.parametrize(
    ("commit", "requirements"),
    [
        pytest.param("", ["nab>=0.0.22"], id="release"),
        pytest.param(
            _NAB_COMMIT,
            [
                f"nab @ {_NAB_SOURCE}",
                f"nab-index @ {_NAB_SOURCE}#subdirectory=nab-index",
                f"nab-markersets @ {_NAB_SOURCE}#subdirectory=nab-markersets",
                f"nab-project @ {_NAB_SOURCE}#subdirectory=nab-project",
                f"nab-provider @ {_NAB_SOURCE}#subdirectory=nab-provider",
                f"nab-resolver @ {_NAB_SOURCE}#subdirectory=nab-resolver",
            ],
            id="git-commit-workspace",
        ),
    ],
)
def test_refresh_installs_selected_nab(
    tmp_path: Path, action_scripts: Path, commit: str, requirements: list[str]
) -> None:
    installer = tmp_path / "tools/install_live_tools.sh"
    installer.parent.mkdir()
    installer.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$RUNNER_TEMP/installed"\n')
    installer.chmod(0o755)
    (tmp_path / "action").mkdir()

    result = _run_step(
        action_scripts,
        "Install Nab",
        tmp_path,
        tmp_path / "bin/uv",
        GITHUB_ACTION_PATH=str(tmp_path / "action"),
        NAB_GIT_COMMIT=commit,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "installed").read_text().splitlines() == [f"{tmp_path}/lock-tools", *requirements]


@pytest.mark.parametrize(
    ("path", "steps"),
    [
        pytest.param("validate-news/action.yml", ("runs", "steps"), id="validate-news"),
        pytest.param("check-tagged-source/action.yml", ("runs", "steps"), id="check-tagged-source"),
        pytest.param(".github/workflows/prepare-towncrier-release.yaml", ("jobs", "lock", "steps"), id="prepare"),
        pytest.param(".github/workflows/upgrade-release-tools.yaml", ("jobs", "generate-lock", "steps"), id="upgrade"),
        pytest.param(".github/workflows/validate-python-release.yaml", ("jobs", "lock", "steps"), id="python-release"),
    ],
)
def test_refresh_callers_forward_nab_commit(path: str, steps: tuple[str, ...]) -> None:
    document = yaml.safe_load((Path(__file__).resolve().parents[2] / path).read_text())
    inputs = document["inputs"] if "runs" in document else document[True]["workflow_call"]["inputs"]
    for key in steps:
        document = document[key]
    refresh = next(step for step in document if step.get("uses") == "$/refresh-release-lock")

    assert inputs["nab-git-commit"]["default"] == ""
    assert refresh["with"]["nab-git-commit"] == "${{ inputs.nab-git-commit }}"


@pytest.mark.parametrize("mode", ["check", "refresh"])
def test_refresh_rejects_changed_primary_environments(tmp_path: Path, action_scripts: Path, mode: str) -> None:
    (tmp_path / "pylock.toml").write_text(_LOCK)
    retargeting = tmp_path / "bin/uv"
    retargeting.parent.mkdir()
    retargeting.write_text(
        f"#!{sys.executable}\nimport pathlib\nlock = pathlib.Path('pylock.toml')\n"
        "lock.write_text(lock.read_text().replace('3.15', '3.14'))\n"
    )
    retargeting.chmod(0o755)

    result = _run_step(action_scripts, "Resolve all project groups and extras", tmp_path, retargeting, MODE=mode)

    assert result.returncode != 0
    assert "regenerated Nab lock changed its target environments" in result.stderr

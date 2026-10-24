from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from conftest import action, run
from packaging.version import Version


def test_refresh_rejects_unknown_lock_producer(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "test"\nrequires-python = ">=3.15"\npackages = []\n'
    )

    result = action(tmp_path, tmp_path, action_scripts, "refresh-release-lock", version="")

    assert result.returncode != 0
    assert "lock has no recognized producer" in result.stderr


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


def test_refresh_rejects_native_uv_lock_for_nab(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pylock.toml").write_text('[tool.nab]\ncommand-line = ["nab", "lock"]\n')

    result = action(tmp_path, tmp_path, action_scripts, "refresh-release-lock", version="", KEEP_UV_LOCK="true")

    assert result.returncode != 0
    assert "keep-uv-lock requires a release-creator lock" in result.stderr


@pytest.mark.parametrize("mode", ["check", "refresh"])
def test_refresh_uses_the_locked_resolver(tmp_path: Path, action_scripts: Path, mode: str) -> None:
    source = Path(__file__).resolve().parents[2]
    steps = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())["runs"]["steps"]
    resolver = next(step for step in steps if step.get("with", {}).get("groups") == "release-resolver")
    assert resolver["if"] == "steps.producer.outputs.name == 'release-creator'"
    assert resolver["with"]["lock-source"] == "shared"
    assert resolver["with"]["venv"] == "${{ runner.temp }}/release-resolver"
    packages = tomllib.loads((source / "pylock.toml").read_text())["packages"]
    pinned = next(package for package in packages if package["name"] == "uv")
    assert Version(pinned["version"]) >= Version("0.13.5")
    project = tomllib.loads((source / "pyproject.toml").read_text())
    assert project["dependency-groups"]["release-resolver"] == [f"uv=={pinned['version']}"]
    assert all(artifact["hashes"]["sha256"] for artifact in pinned["wheels"])

    executable = tmp_path / "release-resolver/bin/uv"
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >"$RUNNER_TEMP/selected-uv"\n')
    executable.chmod(0o755)
    resolve_step = next(
        index for index, step in enumerate(steps) if step.get("name") == "Resolve all project groups and extras"
    )
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", str(action_scripts / f"refresh-release-lock-{resolve_step}.sh")],
        cwd=tmp_path,
        env=os.environ | {"MODE": mode, "KEEP_UV_LOCK": "false", "RUNNER_TEMP": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "selected-uv").read_text().strip() == str(executable)


@pytest.mark.parametrize("keep_uv_lock", [False, True], ids=["pylock-only", "native-uv-lock"])
@pytest.mark.parametrize("mode", ["check", "refresh"])
def test_refresh_passes_native_lock_flag(tmp_path: Path, action_scripts: Path, mode: str, keep_uv_lock: bool) -> None:
    source = Path(__file__).resolve().parents[2]
    steps = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())["runs"]["steps"]
    index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Resolve all project groups and extras"
    )
    executable = tmp_path / "release-resolver/bin/uv"
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >"$RUNNER_TEMP/argv"\n')
    executable.chmod(0o755)

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", str(action_scripts / f"refresh-release-lock-{index}.sh")],
        cwd=tmp_path,
        env=os.environ | {"MODE": mode, "KEEP_UV_LOCK": str(keep_uv_lock).lower(), "RUNNER_TEMP": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    arguments = (tmp_path / "argv").read_text().splitlines()
    assert ("--keep-uv-lock" in arguments) is keep_uv_lock
    assert ("--check" in arguments) is (mode == "check")


@pytest.mark.parametrize("mode", ["check", "refresh"])
def test_refresh_includes_native_uv_lock_in_diff(tmp_path: Path, action_scripts: Path, mode: str) -> None:
    source = Path(__file__).resolve().parents[2]
    steps = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())["runs"]["steps"]
    index = next(index for index, step in enumerate(steps) if step.get("id") == "lock")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1.0"\n')
    (tmp_path / "pylock.toml").write_text('lock-version = "1.0"\n')
    (tmp_path / "uv.lock").write_text("version = 1\n")
    run(tmp_path, "git", "init", "-b", "main")
    run(tmp_path, "git", "config", "user.name", "Test")
    run(tmp_path, "git", "config", "user.email", "test@example.org")
    run(tmp_path, "git", "add", ".")
    run(tmp_path, "git", "commit", "-m", "Add locks")
    (tmp_path / "uv.lock").write_text("version = 2\n")

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", str(action_scripts / f"refresh-release-lock-{index}.sh")],
        cwd=tmp_path,
        env=os.environ
        | {
            "MODE": mode,
            "KEEP_UV_LOCK": "true",
            "ADDITIONAL_LOCK": "",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode != 0) is (mode == "check"), result.stderr
    if mode == "refresh":
        assert "diff --git a/uv.lock b/uv.lock" in (tmp_path / "lock.patch").read_text()
        assert (tmp_path / "output").read_text() == "changed=true\n"

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("groups", "module"),
    [
        pytest.param("release", "yaml", id="release"),
        pytest.param("release test", "pytest", id="multiple-groups"),
        pytest.param("release\ntest", "pytest", id="multiline-groups"),
    ],
)
def test_install_locked_tools_installs_groups(tmp_path: Path, action_scripts: Path, groups: str, module: str) -> None:
    source = Path(__file__).resolve().parents[2]
    environment = tmp_path / "tools"
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups=groups,
        venv=environment,
    )
    assert result.returncode == 0, result.stderr
    imported = subprocess.run(
        [str(environment / "bin/python"), "-c", "import importlib, sys; importlib.import_module(sys.argv[1])", module],
        text=True,
        capture_output=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr


def test_backend_constraints_match_shared_lock(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    generated = subprocess.run(
        [
            str(Path(sys.executable).with_name("release-creator")),
            "build-constraints",
            "--lock",
            str(source / "pylock.toml"),
            "--group",
            "build",
            "--python-version",
            "3.15",
            "--output",
            str(tmp_path / "constraints.txt"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    assert (tmp_path / "constraints.txt").read_bytes() == (source / "release-build-constraints.txt").read_bytes()


def test_install_locked_tools_rejects_backend_hash_mismatch(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    action_root = tmp_path / "action"
    action_root.mkdir()
    (tmp_path / "pylock.toml").write_bytes((source / "pylock.toml").read_bytes())
    constraints = (source / "release-build-constraints.txt").read_text()
    (tmp_path / "release-build-constraints.txt").write_text(
        "\n".join(f"{line.split()[0]} --hash=sha256:{'0' * 64}" for line in constraints.splitlines()) + "\n"
    )
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="release",
        venv=tmp_path / "tools",
        action_root=action_root,
        extra_env={"UV_CACHE_DIR": str(tmp_path / "cache")},
    )
    assert result.returncode != 0
    assert "Hash mismatch" in result.stderr


def test_install_locked_tools_rejects_empty_groups(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="",
        venv=tmp_path / "tools",
    )
    assert result.returncode != 0


def test_install_locked_tools_ignores_resolution_cutoff_for_hashed_lock(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="release",
        venv=tmp_path / "tools",
        extra_env={"UV_EXCLUDE_NEWER": "1 week"},
    )
    assert result.returncode == 0, result.stderr


def install(
    repository: Path,
    action_scripts: Path,
    tmp_path: Path,
    *,
    lock: Path,
    groups: str,
    venv: Path,
    action_root: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    source = Path(__file__).resolve().parents[2]
    environment = (
        os.environ
        | {
            "LOCK": str(lock),
            "DEPENDENCY_GROUPS": groups,
            "PYTHON_VERSION": "3.15",
            "VENV": str(venv),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_ACTION_PATH": str(action_root or source / "install-locked-tools"),
        }
        | (extra_env or {})
    )
    for index in range(3):
        result = subprocess.run(
            ["bash", str(action_scripts / f"install-locked-tools-{index}.sh")],
            cwd=repository,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return result
    return result

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
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


@pytest.mark.parametrize(
    ("group", "present", "absent"),
    [
        pytest.param("release-check", "prek", "release-creator", id="source-check"),
        pytest.param("release-news", "towncrier", "prek", id="pr-news"),
        pytest.param("release-validate", "release-creator", "towncrier", id="patch-validation"),
        pytest.param("release-shell", "yq", "release-creator", id="inline-shell"),
    ],
)
def test_install_locked_tools_selects_job_tools(
    tmp_path: Path, action_scripts: Path, group: str, present: str, absent: str
) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups=group,
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin" / present).exists()
    assert not (tmp_path / "tools/bin" / absent).exists()


def test_backend_constraints_match_shared_lock(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    executable = shutil.which("release-creator")
    assert executable is not None
    generated = subprocess.run(
        [
            executable,
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


def test_install_locked_tools_rejects_exporter_hash_mismatch(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    action_root = tmp_path / "action"
    action_root.mkdir()
    lock = (source / "pylock.toml").read_text()
    package = next(package for package in tomllib.loads(lock)["packages"] if package["name"] == "release-creator")
    (tmp_path / "pylock.toml").write_text(lock.replace(package["wheels"][0]["hashes"]["sha256"], "0" * 64, 1))
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


def test_install_locked_tools_rejects_missing_group(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="relesae",
        venv=tmp_path / "tools",
    )
    assert "missing lock dependency groups: relesae" in result.stderr


def test_install_locked_tools_reuses_exporter(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    for target in ("notes", "validators"):
        result = install(
            source,
            action_scripts,
            tmp_path,
            lock=source / "pylock.toml",
            groups="release-notes",
            venv=tmp_path / target,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "validators/bin/release-creator").is_file()


def test_install_locked_tools_uses_managed_python(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("bash", "uv"):
        executable = shutil.which(name)
        assert executable is not None
        (tools / name).symlink_to(executable)
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="release-check",
        venv=tmp_path / "tools",
        extra_env={"PATH": str(tools)},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin/prek").is_file()


def test_install_locked_tools_exporter_does_not_build_pyyaml(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="release-notes",
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    imported = subprocess.run(
        [str(tmp_path / "lock-exporter/bin/python"), "-c", "import yaml"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert "No module named 'yaml'" in imported.stderr


def test_install_locked_tools_accepts_tool_only_lock(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = tmp_path / "pylock.tool-only.toml"
    lock.write_text((source / "pylock.toml").read_text().replace('    "build",\n', "", 1))
    result = install(source, action_scripts, tmp_path, lock=lock, groups="release-notes", venv=tmp_path / "tools")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin/release-creator").is_file()


def test_install_locked_tools_ignores_resolution_cutoff_for_hashed_lock(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        lock=source / "pylock.toml",
        groups="release",
        venv=tmp_path / "tools",
        extra_env={"UV_EXCLUDE_NEWER": "1970-01-01T00:00:00Z"},
    )
    assert result.returncode == 0, result.stderr


def test_shared_lock_respects_seven_day_cutoff() -> None:
    source = Path(__file__).resolve().parents[2]
    cutoff = datetime.now(UTC) - timedelta(days=7)
    packages = tomllib.loads((source / "pylock.toml").read_text())["packages"]
    younger = {
        package["name"]
        for package in packages
        if package["name"] != "release-creator"
        and (
            times := [
                artifact["upload-time"]
                for artifact in [package.get("sdist", {}), *package.get("wheels", [])]
                if "upload-time" in artifact
            ]
        )
        and min(times) > cutoff
    }
    assert younger == set()


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

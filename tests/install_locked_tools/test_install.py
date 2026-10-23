from __future__ import annotations

import shutil
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import action


@pytest.mark.parametrize(
    ("groups", "module"),
    [
        pytest.param("release-news", "yaml", id="release-news"),
        pytest.param("release-check release-notes", "release_creator", id="multiple-groups"),
        pytest.param("release-check\nrelease-notes", "release_creator", id="multiline-groups"),
    ],
)
def test_install_locked_tools_installs_groups(tmp_path: Path, action_scripts: Path, groups: str, module: str) -> None:
    source = Path(__file__).resolve().parents[2]
    environment = tmp_path / "tools"
    result = install(
        source,
        action_scripts,
        tmp_path,
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
        pytest.param("release-hooks", "release-creator", "towncrier", id="action-tests"),
        pytest.param("release-hook-check", "yq", "towncrier", id="hook-cooldown"),
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
        groups=group,
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin" / present).exists()
    assert not (tmp_path / "tools/bin" / absent).exists()


def test_backend_constraints_match_shared_lock(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    generated = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            "packaging>=26.1",
            "python",
            str(source / "tools/build_constraints.py"),
            str(tmp_path / "constraints.txt"),
            str(source / "pylock.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    constraints = (tmp_path / "constraints.txt").read_text()
    assert "cython==" in constraints
    assert "setuptools==" in constraints
    assert "--hash=sha256:" in constraints


def test_install_lock_tools_rejects_hash_mismatch(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    action_root = tmp_path / "install-nab"
    action_root.mkdir()
    lock = (source / "pylock.toml").read_text()
    package = next(package for package in tomllib.loads(lock)["packages"] if package["name"] == "nab")
    (tmp_path / "pylock.toml").write_text(lock.replace(package["wheels"][0]["hashes"]["sha256"], "0" * 64, 1))
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "install-nab",
        version="0.2.0",
        GITHUB_ACTION_PATH=str(action_root),
        UV_CACHE_DIR=str(tmp_path / "cache"),
    )
    assert result.returncode != 0
    assert "Hash mismatch" in result.stderr


def test_install_locked_tools_rejects_empty_groups(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        groups="",
        venv=tmp_path / "tools",
    )
    assert result.returncode != 0
    assert "at least one dependency group is required" in result.stderr


def test_install_locked_tools_rejects_missing_group(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        groups="relesae",
        venv=tmp_path / "tools",
    )
    assert result.returncode != 0
    assert "missing lock dependency groups: relesae" in result.stderr


def test_install_locked_tools_shared_group_ignores_missing_caller_group(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = (source / "pylock.toml").read_text().replace('    "release-attestations",\n', "", 1)
    (tmp_path / "pylock.toml").write_text(lock)
    assert "release-attestations" not in tomllib.loads(lock)["dependency-groups"]
    result = install(
        tmp_path,
        action_scripts,
        tmp_path,
        groups="release-attestations",
        venv=tmp_path / "tools",
        lock_source="shared",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin/pypi-attestations").is_file()


def test_install_locked_tools_rejects_unknown_lock_source(tmp_path: Path, action_scripts: Path) -> None:
    result = install(
        Path(__file__).resolve().parents[2],
        action_scripts,
        tmp_path,
        groups="release-notes",
        venv=tmp_path / "tools",
        lock_source="unknown",
    )
    assert result.returncode != 0
    assert "unknown lock source: unknown" in result.stderr


def test_install_locked_tools_reuses_exporter(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    for target in ("notes", "validators"):
        result = install(
            source,
            action_scripts,
            tmp_path,
            groups="release-notes",
            venv=tmp_path / target,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "validators/bin/release-creator").is_file()


def test_install_locked_tools_uses_managed_python(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("bash", "sha256sum", "uv"):
        executable = shutil.which(name)
        assert executable is not None
        (tools / name).symlink_to(executable)
    result = install(
        source,
        action_scripts,
        tmp_path,
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
        groups="release-notes",
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    imported = subprocess.run(
        [str(tmp_path / "lock-tools/bin/python"), "-c", "import yaml"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert "No module named 'yaml'" in imported.stderr


def test_install_locked_tools_merges_shared_and_caller_build_constraints(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    (tmp_path / "pylock.toml").write_bytes((source / "pylock.toml").read_bytes())
    (tmp_path / "pylock.toml").write_text(
        (tmp_path / "pylock.toml").read_text()
        + """
[[packages]]
name = "probe-only"
version = "1.0"
marker = '\"build\" in dependency_groups'
index = "https://pypi.org/simple/"
[[packages.wheels]]
name = "probe_only-1.0-py3-none-any.whl"
url = "https://files.pythonhosted.org/probe_only-1.0-py3-none-any.whl"
hashes.sha256 = """
        + f'"{"0" * 64}"\n',
    )
    result = install(
        tmp_path,
        action_scripts,
        tmp_path,
        groups="release-notes",
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    assert "probe-only==1.0 " in next(tmp_path.glob("build-constraints-*.txt")).read_text()


def test_install_locked_tools_accepts_lock_without_build_group(
    tmp_path: Path, action_scripts: Path, nab_executable: Path
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "tool-only"\nversion = "0.1.0"\nrequires-python = ">=3.15"\n'
        '[dependency-groups]\nrelease-check = ["prek>=0.2"]\n'
        '[tool.nab]\nbase-group = "project-runtime"\ndefault-groups = []\n',
    )
    generated = subprocess.run(
        [str(nab_executable), "lock", "--groups", "release-check", "--output", "pylock.toml"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    assert "build" not in tomllib.loads((tmp_path / "pylock.toml").read_text())["dependency-groups"]
    result = install(tmp_path, action_scripts, tmp_path, groups="release-check", venv=tmp_path / "tools")
    assert result.returncode == 0, result.stderr
    assert "setuptools==" in next(tmp_path.glob("build-constraints-*.txt")).read_text()


def test_install_locked_tools_ignores_resolution_cutoff_for_hashed_lock(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(
        source,
        action_scripts,
        tmp_path,
        groups="release-notes",
        venv=tmp_path / "tools",
        extra_env={"UV_EXCLUDE_NEWER": "1970-01-01T00:00:00Z"},
    )
    assert result.returncode == 0, result.stderr
    locked_version = next(
        package["version"]
        for package in tomllib.loads((source / "pylock.toml").read_text())["packages"]
        if package["name"] == "release-creator"
    )
    installed_version = subprocess.run(
        [
            str(tmp_path / "tools/bin/python"),
            "-c",
            "from importlib.metadata import version; print(version('release-creator'))",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert installed_version == locked_version


def test_shared_lock_records_upload_times() -> None:
    packages = tomllib.loads((Path(__file__).resolve().parents[2] / "pylock.toml").read_text())["packages"]
    missing = {
        package["name"]
        for package in packages
        if not any("upload-time" in artifact for artifact in [package.get("sdist", {}), *package.get("wheels", [])])
    }
    assert not missing, f"packages without upload times: {sorted(missing)}"


def test_shared_lock_respects_seven_day_cutoff() -> None:
    source = Path(__file__).resolve().parents[2]
    policy = tomllib.loads((source / "pyproject.toml").read_text())["tool"]["nab"]
    floors = {
        name: datetime.fromisoformat(settings["uploaded-prior-to"])
        for name, settings in policy.get("packages", {}).items()
        if "uploaded-prior-to" in settings
    }
    for rule in policy.get("package-rules", []):
        floors.update(dict.fromkeys(rule["match"], datetime.fromisoformat(rule["uploaded-prior-to"])))
    lock = tomllib.loads((source / "pylock.toml").read_text())
    cutoff = datetime.now(UTC) - timedelta(days=7)
    packages = lock["packages"]
    younger = {
        package["name"]
        for package in packages
        if (
            times := [
                artifact["upload-time"]
                for artifact in [package.get("sdist", {}), *package.get("wheels", [])]
                if "upload-time" in artifact
            ]
        )
        and max(times) > floors.get(package["name"], cutoff)
    }
    assert not younger, f"packages newer than the seven-day cutoff: {sorted(younger)}"


def install(
    repository: Path,
    action_scripts: Path,
    tmp_path: Path,
    *,
    groups: str,
    venv: Path,
    lock_source: str = "caller",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return action(
        repository,
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="",
        GROUPS=groups,
        VENV=str(venv),
        LOCK_SOURCE=lock_source,
        **(extra_env or {}),
    )

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import tomlkit
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
        pytest.param("release-validate", "release-creator", "yq", id="patch-validation"),
        pytest.param("release-shell", "yq", "release-creator", id="inline-shell"),
        pytest.param("release-hooks", "release-creator", "yq", id="action-tests"),
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
    action_root = tmp_path / "install-locked-tools"
    action_root.mkdir()
    lock = (source / "pylock.toml").read_text()
    package = next(package for package in tomllib.loads(lock)["packages"] if package["name"] == "nab")
    (tmp_path / "pylock.toml").write_text(lock.replace(package["wheels"][0]["hashes"]["sha256"], "0" * 64, 1))
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "install-locked-tools",
        version="0.2.0",
        GITHUB_ACTION_PATH=str(action_root),
        UV_CACHE_DIR=str(tmp_path / "cache"),
    )
    assert result.returncode != 0
    assert "Hash mismatch" in result.stderr


def test_install_locked_tools_reuses_existing_environment(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    environment = {"GROUPS": "lock-tools", "VENV": str(tmp_path / "lock-tools"), "LOCK_SOURCE": "shared"}
    first = action(source, tmp_path, action_scripts, "install-locked-tools", version="", **environment)
    second = action(source, tmp_path, action_scripts, "install-locked-tools", version="", **environment)
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert (tmp_path / "lock-tools" / ("Scripts/nab.exe" if os.name == "nt" else "bin/nab")).is_file()


def test_install_locked_tools_exposes_release_commands(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    environment = tmp_path / "tools"
    result = install(source, action_scripts, tmp_path, groups="release-check", venv=environment)

    assert result.returncode == 0, result.stderr
    overlay = Path((tmp_path / "github-path").read_text().splitlines()[-1])
    suffix = ".exe" if os.name == "nt" else ""
    assert (overlay / f"prek{suffix}").is_file()
    command = subprocess.run([str(overlay / f"prek{suffix}"), "--version"], capture_output=True, text=True, check=False)
    assert command.returncode == 0, command.stderr


def test_install_locked_tools_preserves_runner_python(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    result = install(source, action_scripts, tmp_path, groups="release-check", venv=tmp_path / "tools")

    assert result.returncode == 0, result.stderr
    overlay = Path((tmp_path / "github-path").read_text().splitlines()[-1])
    assert not any(command.name.casefold().startswith(("python", "pip", "uv")) for command in overlay.iterdir())
    original = shutil.which(Path(sys.executable).name, path=f"{overlay}{os.pathsep}{Path(sys.executable).parent}")
    assert original is not None
    assert Path(original).resolve() == Path(sys.executable).resolve()


def test_install_locked_tools_exposes_separate_environments(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    for group in ("release-check", "release-news"):
        result = install(source, action_scripts, tmp_path, groups=group, venv=tmp_path / group)
        assert result.returncode == 0, result.stderr

    overlays = [Path(line) for line in (tmp_path / "github-path").read_text().splitlines()]
    suffix = ".exe" if os.name == "nt" else ""
    assert overlays[0] != overlays[1]
    assert (overlays[0] / f"prek{suffix}").is_file()
    assert (overlays[1] / f"towncrier{suffix}").is_file()


def test_install_locked_tools_reuses_windows_shaped_environment(tmp_path: Path, action_scripts: Path) -> None:
    subprocess.run(["uv", "venv", "--python", "3.15", str(tmp_path / "lock-tools")], check=True, capture_output=True)
    (tmp_path / "lock-tools" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")).unlink()
    result = subprocess.run(
        ["bash", str(action_scripts / "install-locked-tools-0.sh")],
        env=os.environ | {"RUNNER_TEMP": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "lock-tools/pyvenv.cfg").is_file()


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


@pytest.mark.parametrize("local_source", [False, True], ids=["locked-caller", "local-source"])
def test_install_locked_tools_checks_caller_release_creator(tmp_path: Path, local_source: bool) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["release-prepare"]\ncreated-by = "test"\npackages = []\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
    )
    source = Path(__file__).resolve().parents[2]
    command = [
        "python",
        str(source / "tools/check_lock_groups.py"),
        str(lock),
        "release-prepare",
        "--shared-lock",
        str(source / "pylock.toml"),
    ]
    if local_source:
        command.append("--local-tool-source")
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    assert (result.returncode == 0) is local_source, result.stderr


def test_local_tool_source_accepts_versionless_package(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(item for item in document["packages"] if item["name"] == "release-creator")
    for field in ("version", "index", "sdist", "wheels"):
        package.pop(field)
    package["directory"] = {"path": "."}
    (tmp_path / "pylock.toml").write_text(tomlkit.dumps(document))
    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(tmp_path / "pylock.toml"),
            "release-prepare",
            "--shared-lock",
            str(source / "pylock.toml"),
            "--local-tool-source",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("replace", "message"),
    [
        pytest.param(
            ("created-at = 2026-10-23", "created-at = 2099-10-23"),
            "created in the future",
            id="future-creation",
        ),
        pytest.param(
            ("upload-time = 2026-", "upload-time = 2099-"),
            "uncooled artifact",
            id="recent-artifact",
        ),
    ],
)
def test_install_locked_tools_rejects_uncooled_lock(tmp_path: Path, replace: tuple[str, str], message: str) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = (source / "pylock.toml").read_text()
    assert replace[0] in lock
    (tmp_path / "pylock.toml").write_text(lock.replace(*replace))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(tmp_path / "pylock.toml"), "release-check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_install_locked_tools_checks_build_group_with_selected_groups(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    package["wheels"][0]["upload-time"] = datetime(2099, 1, 1, tzinfo=UTC)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-news"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uncooled artifact" in result.stderr


@pytest.mark.parametrize("change", ["missing", "naive"], ids=["missing", "naive"])
def test_install_locked_tools_rejects_undated_artifact(tmp_path: Path, change: str) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    if change == "missing":
        del package["wheels"][0]["upload-time"]
    else:
        package["wheels"][0]["upload-time"] = datetime(2026, 10, 1)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-news"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uncooled artifact" in result.stderr


def test_install_locked_tools_skips_unselected_package(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "release-creator")
    package["wheels"][0]["upload-time"] = datetime(2099, 1, 1, tzinfo=UTC)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source_kind", ["foreign-host", "insecure-url", "local-path"], ids=["foreign-host", "insecure-url", "local-path"]
)
def test_install_locked_tools_rejects_non_pypi_artifact(tmp_path: Path, source_kind: str) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    artifact = package["wheels"][0]
    if source_kind == "foreign-host":
        artifact["url"] = artifact["url"].replace("files.pythonhosted.org", "example.org")
    elif source_kind == "insecure-url":
        artifact["url"] = artifact["url"].replace("https://", "http://")
    else:
        del artifact["url"]
        artifact["path"] = "cython.whl"
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-news"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "non-PyPI artifact" in result.stderr


def test_install_locked_tools_rejects_artifact_version_mismatch(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "setuptools")
    artifact = package["wheels"][0]
    artifact["url"] = artifact["url"].replace("84.0.0", "0.0.0")
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-news"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "artifact differs from package version" in result.stderr


def test_install_locked_tools_rejects_unreviewed_version_under_reviewed_floor(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "release-creator")
    package["version"] = "0.6.3"
    for artifact in [package["sdist"], *package["wheels"]]:
        artifact["name"] = artifact["name"].replace("0.6.7", "0.6.3")
        artifact["url"] = artifact["url"].replace("0.6.7", "0.6.3")
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-news"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uncooled artifact" in result.stderr


@pytest.mark.parametrize("version", ["0.6.0", "0.6.4"])
def test_install_locked_tools_rejects_caller_below_shared_floor(tmp_path: Path, version: str) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "release-creator")
    package["version"] = version
    for artifact in [package["sdist"], *package["wheels"]]:
        artifact["name"] = artifact["name"].replace("0.6.7", version)
        artifact["url"] = artifact["url"].replace("0.6.7", version)
        artifact["upload-time"] = datetime(2026, 10, 15, tzinfo=UTC)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(lock),
            "release-news",
            "--shared-lock",
            str(source / "pylock.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "relock: release-creator 0.6.7 required" in result.stderr


def test_install_locked_tools_constraints_only_checks_lock_age(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    (tmp_path / "pylock.toml").write_text(
        (source / "pylock.toml").read_text().replace("created-at = 2026-10-23", "created-at = 2099-10-23", 1)
    )
    result = action(tmp_path, tmp_path, action_scripts, "install-locked-tools", version="")
    assert result.returncode != 0
    assert "created in the future" in result.stderr


def test_install_locked_tools_constraints_only_accepts_no_build_group(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pylock.toml").write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\ncreated-by = "test"\n'
        'dependency-groups = ["project-runtime"]\npackages = []\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
    )
    result = action(tmp_path, tmp_path, action_scripts, "install-locked-tools", version="")
    assert result.returncode == 0, result.stderr
    assert "setuptools==" in next(tmp_path.glob("build-constraints-*.txt")).read_text()


def test_caller_version_check_uses_shared_package_marker(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    shared = tmp_path / "shared.toml"
    lock = (source / "pylock.toml").read_text()
    marker = next(
        package["marker"] for package in tomllib.loads(lock)["packages"] if package["name"] == "release-creator"
    )
    shared.write_text(lock.replace(marker.replace('"', '\\"'), '\\"release-shell\\" in dependency_groups'))
    caller = tmp_path / "caller.toml"
    caller.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["release-shell"]\ncreated-by = "test"\npackages = []\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
    )
    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(caller),
            "release-shell",
            "--shared-lock",
            str(shared),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "relock: release-creator" in result.stderr


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
upload-time = 2026-10-01T00:00:00Z
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


def test_install_locked_tools_accepts_lock_without_build_group(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((source / "pylock.toml").read_text())
    document["dependency-groups"].remove("build")
    (tmp_path / "pylock.toml").write_text(tomlkit.dumps(document))
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

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
import tomlkit
from conftest import CALLER, action


@pytest.mark.parametrize(
    ("groups", "module"),
    [
        pytest.param("release-news", "yaml", id="release-news"),
        pytest.param("release-check release-notes", "release_creator", id="multiple-groups"),
        pytest.param("release-check\nrelease-notes", "release_creator", id="multiline-groups"),
    ],
)
def test_install_locked_tools_installs_groups(
    tmp_path: Path, action_scripts: Path, groups: str, module: str, caller: Path
) -> None:
    environment = tmp_path / "tools"
    result = install(
        caller,
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
    tmp_path: Path, action_scripts: Path, group: str, present: str, absent: str, caller: Path
) -> None:
    result = install(
        caller,
        action_scripts,
        tmp_path,
        groups=group,
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin" / present).exists()
    assert not (tmp_path / "tools/bin" / absent).exists()


def test_install_locked_tools_reuses_existing_environment(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    environment = {"GROUPS": "lock-tools", "VENV": str(tmp_path / "lock-tools")}
    first = action(caller, tmp_path, action_scripts, "install-locked-tools", version="", **environment)
    second = action(caller, tmp_path, action_scripts, "install-locked-tools", version="", **environment)
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert (tmp_path / "lock-tools" / ("Scripts/nab.exe" if os.name == "nt" else "bin/nab")).is_file()


def test_install_locked_tools_keeps_reader_after_nab_sync(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    first = install(caller, action_scripts, tmp_path, groups="lock-tools", venv=tmp_path / "lock-tools")
    second = install(caller, action_scripts, tmp_path, groups="release-news", venv=tmp_path / "news-tools")

    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    reader = tmp_path / "lock-reader" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    imported = subprocess.run([str(reader), "-c", "import certifi"], capture_output=True, text=True, check=False)
    assert imported.returncode == 0, imported.stderr


def test_install_locked_tools_exposes_release_commands(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    environment = tmp_path / "tools"
    result = install(caller, action_scripts, tmp_path, groups="release-check", venv=environment)

    assert result.returncode == 0, result.stderr
    overlay = Path((tmp_path / "github-path").read_text().splitlines()[-1])
    suffix = ".exe" if os.name == "nt" else ""
    assert (overlay / f"prek{suffix}").is_file()
    command = subprocess.run([str(overlay / f"prek{suffix}"), "--version"], capture_output=True, text=True, check=False)
    assert command.returncode == 0, command.stderr


def test_install_locked_tools_uses_minimal_reader(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    result = install(caller, action_scripts, tmp_path, groups="release-check", venv=tmp_path / "tools")

    assert result.returncode == 0, result.stderr
    reader = tmp_path / "lock-reader" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    packages = subprocess.run(
        [str(reader), "-c", "import importlib.util; print(importlib.util.find_spec('nab') is None)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert packages.returncode == 0, packages.stderr
    assert packages.stdout.strip() == "True"


def test_install_locked_tools_preserves_runner_python(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    result = install(caller, action_scripts, tmp_path, groups="release-check", venv=tmp_path / "tools")

    assert result.returncode == 0, result.stderr
    overlay = Path((tmp_path / "github-path").read_text().splitlines()[-1])
    assert not any(command.name.casefold().startswith(("python", "pip", "uv")) for command in overlay.iterdir())
    original = shutil.which(Path(sys.executable).name, path=f"{overlay}{os.pathsep}{Path(sys.executable).parent}")
    assert original is not None
    assert Path(original).resolve() == Path(sys.executable).resolve()


def test_install_locked_tools_exposes_separate_environments(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    for group in ("release-check", "release-news"):
        result = install(caller, action_scripts, tmp_path, groups=group, venv=tmp_path / group)
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


def test_install_locked_tools_rejects_missing_group(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    result = install(
        caller,
        action_scripts,
        tmp_path,
        groups="relesae",
        venv=tmp_path / "tools",
    )
    assert result.returncode != 0
    assert "missing lock dependency groups: relesae" in result.stderr


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        pytest.param(
            "future-creation",
            "created in the future",
            id="future-creation",
        ),
        pytest.param(
            "recent-artifact",
            "uncooled artifact",
            id="recent-artifact",
        ),
    ],
)
def test_install_locked_tools_rejects_uncooled_lock(tmp_path: Path, kind: str, message: str) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    if kind == "future-creation":
        document["tool"]["release-creator"]["created-at"] = datetime(2099, 10, 23, tzinfo=UTC)
    else:
        package = next(package for package in document["packages"] if package["name"] == "cython")
        package["wheels"][0]["upload-time"] = datetime(2099, 10, 23, tzinfo=UTC)
    (tmp_path / "pylock.toml").write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(tmp_path / "pylock.toml"), "release-check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_install_locked_tools_rejects_unknown_lock_producer(tmp_path: Path) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\ncreated-by = "test"\n'
        'dependency-groups = ["release-check"]\npackages = []\n'
    )

    result = subprocess.run(
        ["python", str(Path(__file__).resolve().parents[2] / "tools/check_lock_groups.py"), str(lock), "release-check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "lock has no recognized producer" in result.stderr


def test_install_locked_tools_checks_build_group_with_selected_groups(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    package["wheels"][0]["upload-time"] = datetime(2099, 1, 1, tzinfo=UTC)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(lock),
            "release-news",
            "--project",
            str(CALLER / "pyproject.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uncooled artifact" in result.stderr


@pytest.mark.parametrize("change", ["missing", "naive"], ids=["missing", "naive"])
def test_install_locked_tools_rejects_undated_artifact(tmp_path: Path, change: str) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    if change == "missing":
        del package["wheels"][0]["upload-time"]
    else:
        package["wheels"][0]["upload-time"] = datetime(2026, 10, 1)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(lock),
            "release-news",
            "--project",
            str(CALLER / "pyproject.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "uncooled artifact" in result.stderr


def test_install_locked_tools_skips_unselected_package(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
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
    ("group", "accepted"),
    [pytest.param("release-check", True, id="release"), pytest.param("test", False, id="test")],
)
def test_install_locked_tools_uses_full_lock_provenance_and_selected_groups(
    tmp_path: Path, group: str, accepted: bool
) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    document["dependency-groups"].append("test")
    package = next(package for package in document["packages"] if package["name"] == "release-creator")
    package["marker"] = '"test" in dependency_groups'
    package["wheels"][0]["url"] = package["wheels"][0]["url"].replace("files.pythonhosted.org", "example.org")
    for artifact in [package["sdist"], *package["wheels"]]:
        artifact["upload-time"] = datetime(2026, 10, 1, tzinfo=UTC)
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), group],
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "non-PyPI artifact" in result.stderr


@pytest.mark.parametrize(
    "source_kind", ["foreign-host", "insecure-url", "local-path"], ids=["foreign-host", "insecure-url", "local-path"]
)
def test_install_locked_tools_rejects_non_pypi_artifact(tmp_path: Path, source_kind: str) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    artifact = package["wheels"][0]
    if source_kind == "foreign-host":
        artifact["url"] = artifact["url"].replace("files.pythonhosted.org", "example.org")
    elif source_kind == "insecure-url":
        artifact["url"] = artifact["url"].replace("https://", "http://")
    else:
        artifact["path"] = artifact.pop("url").rsplit("/", 1)[-1]
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


def test_install_locked_tools_checks_exact_group_marker(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "cython")
    package["marker"] = '"release-check" in dependency_groups and "build" not in dependency_groups'
    package["wheels"][0]["url"] = package["wheels"][0]["url"].replace("files.pythonhosted.org", "example.org")
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-check"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "non-PyPI artifact" in result.stderr


def test_install_locked_tools_rejects_artifact_version_mismatch(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    package = next(package for package in document["packages"] if package["name"] == "setuptools")
    artifact = package["wheels"][0]
    artifact["url"] = artifact["url"].replace(str(package["version"]), "0.0.0")
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))

    result = subprocess.run(
        ["python", str(source / "tools/check_lock_groups.py"), str(lock), "release-news"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "package version" in result.stderr


@pytest.mark.parametrize(
    ("policy", "accepted"),
    [
        pytest.param("", False, id="no-override"),
        pytest.param(
            "[tool.nab.packages.release-creator]\nuploaded-prior-to = 2026-10-25T07:08:32Z\n", True, id="package"
        ),
        pytest.param(
            '[tool.nab.packages.release-creator]\nuploaded-prior-to = "2026-10-25T07:08:32+00:00"\n', True, id="text"
        ),
        pytest.param(
            '[[tool.nab.package-rules]]\nmatch = ["release_creator"]\nuploaded-prior-to = 2026-10-25T07:08:32Z\n',
            True,
            id="rule",
        ),
        pytest.param('[tool.nab.packages.release-creator]\nuploaded-prior-to = "P0D"\n', True, id="duration"),
        pytest.param("[tool.nab.packages.release-creator]\nuploaded-prior-to = false\n", True, id="disabled"),
        pytest.param(
            "[tool.nab.packages.release-creator]\nuploaded-prior-to = 2026-10-25T07:08:30Z\n", False, id="too-early"
        ),
        pytest.param('[tool.nab.packages.release-creator]\nuploaded-prior-to = "P3D"\n', False, id="long-duration"),
        pytest.param("[tool.nab.packages.towncrier]\nuploaded-prior-to = false\n", False, id="other-package"),
    ],
)
def test_install_locked_tools_honours_caller_package_cutoff(tmp_path: Path, policy: str, accepted: bool) -> None:
    source = Path(__file__).resolve().parents[2]
    project = tmp_path / "pyproject.toml"
    project.write_text(f"{policy}[tool.nab.packages.uv]\nuploaded-prior-to = 2026-10-22T01:32:34Z\n")

    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(CALLER / "pylock.toml"),
            "release-news",
            "--project",
            str(project),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "uncooled artifact" in result.stderr


@pytest.mark.parametrize(
    "value",
    [pytest.param("2026-10-25T07:08:32", id="naive"), pytest.param("soon", id="text"), pytest.param("7", id="number")],
)
def test_install_locked_tools_rejects_invalid_caller_cutoff(tmp_path: Path, value: str) -> None:
    source = Path(__file__).resolve().parents[2]
    project = tmp_path / "pyproject.toml"
    project.write_text(
        "[tool.nab.packages.release-creator]\nuploaded-prior-to = " + (value if value == "7" else f'"{value}"') + "\n"
    )

    result = subprocess.run(
        [
            "python",
            str(source / "tools/check_lock_groups.py"),
            str(CALLER / "pylock.toml"),
            "release-news",
            "--project",
            str(project),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "invalid Nab cutoff for release-creator" in result.stderr


def test_install_locked_tools_constraints_only_checks_lock_age(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes((CALLER / "pyproject.toml").read_bytes())
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    document["tool"]["release-creator"]["created-at"] = datetime(2099, 10, 23, tzinfo=UTC)
    (tmp_path / "pylock.toml").write_text(tomlkit.dumps(document))
    result = action(tmp_path, tmp_path, action_scripts, "install-locked-tools", version="")
    assert result.returncode != 0
    assert "created in the future" in result.stderr


def test_install_locked_tools_constraints_only_accepts_no_build_group(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.nab]\nuploaded-prior-to = "P7D"\n')
    (tmp_path / "pylock.toml").write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\ncreated-by = "test"\n'
        'dependency-groups = ["project-runtime"]\npackages = []\n'
        "[tool.nab]\ncreated-at = 2026-10-19T00:00:00Z\n"
    )
    result = action(tmp_path, tmp_path, action_scripts, "install-locked-tools", version="")
    assert result.returncode == 0, result.stderr
    assert next(tmp_path.glob("build-constraints-*.txt")).read_text() == ""


def test_install_locked_tools_reuses_exporter(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    for target in ("notes", "validators"):
        result = install(
            caller,
            action_scripts,
            tmp_path,
            groups="release-notes",
            venv=tmp_path / target,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "validators/bin/release-creator").is_file()


def test_install_locked_tools_uses_managed_python(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("bash", "sha256sum", "uv"):
        executable = shutil.which(name)
        assert executable is not None
        (tools / name).symlink_to(executable)
    result = install(
        caller,
        action_scripts,
        tmp_path,
        groups="release-check",
        venv=tmp_path / "tools",
        extra_env={"PATH": str(tools)},
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "tools/bin/prek").is_file()


def test_install_locked_tools_exporter_does_not_build_pyyaml(
    tmp_path: Path, action_scripts: Path, caller: Path
) -> None:
    result = install(
        caller,
        action_scripts,
        tmp_path,
        groups="release-notes",
        venv=tmp_path / "tools",
    )
    assert result.returncode == 0, result.stderr
    imported = subprocess.run(
        [str(tmp_path / "lock-reader/bin/python"), "-c", "import yaml"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert "No module named 'yaml'" in imported.stderr


def test_install_locked_tools_accepts_lock_without_build_group(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes((CALLER / "pyproject.toml").read_bytes())
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    document["dependency-groups"].remove("build")
    (tmp_path / "pylock.toml").write_text(tomlkit.dumps(document))
    result = install(tmp_path, action_scripts, tmp_path, groups="release-check", venv=tmp_path / "tools")
    assert result.returncode == 0, result.stderr
    assert next(tmp_path.glob("build-constraints-*.txt")).read_text() == ""


def test_install_locked_tools_ignores_resolution_cutoff_for_hashed_lock(
    tmp_path: Path, action_scripts: Path, caller: Path
) -> None:
    result = install(
        caller,
        action_scripts,
        tmp_path,
        groups="release-notes",
        venv=tmp_path / "tools",
        extra_env={"UV_EXCLUDE_NEWER": "1970-01-01T00:00:00Z"},
    )
    assert result.returncode == 0, result.stderr
    locked_version = next(
        package["version"]
        for package in tomllib.loads((CALLER / "pylock.toml").read_text())["packages"]
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


def install(
    repository: Path,
    action_scripts: Path,
    tmp_path: Path,
    *,
    groups: str,
    venv: Path,
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
        **(extra_env or {}),
    )


def test_install_locked_tools_installs_reader_under_cutoff(tmp_path: Path, action_scripts: Path, caller: Path) -> None:
    result = install(
        caller,
        action_scripts,
        tmp_path,
        groups="release-check",
        venv=tmp_path / "tools",
        extra_env={"EXCLUDE_NEWER": "2020-01-01T00:00:00Z", "UV_CACHE_DIR": str(tmp_path / "cache")},
    )

    assert result.returncode != 0
    assert "certifi>=2026.7.22" in result.stderr

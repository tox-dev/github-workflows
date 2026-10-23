from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import tomlkit
from conftest import action


def test_export_build_constraints_uses_checked_in_locks(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    (tmp_path / "pylock.toml").write_bytes((source / "pylock.toml").read_bytes())
    result = action(tmp_path, tmp_path, action_scripts, "install-locked-tools", version="")
    assert result.returncode == 0, result.stderr
    output = next(tmp_path.glob("build-constraints-*.txt"))
    constraints = output.read_text()
    assert "cython==" in constraints
    assert "setuptools==" in constraints
    assert "pytest==" not in constraints
    assert f"path={output}\n" in (tmp_path / "output").read_text()


@pytest.mark.parametrize(
    "platform",
    [
        pytest.param("macos_x86_64", id="macos-intel"),
        pytest.param("windows_arm64", id="windows-arm"),
    ],
)
def test_export_build_constraints_covers_release_runners(tmp_path: Path, platform: str) -> None:
    source = Path(__file__).resolve().parents[2]
    output = tmp_path / "constraints.txt"
    result = subprocess.run(
        [
            sys.executable,
            str(source / "tools/build_constraints.py"),
            "--target-platform",
            platform,
            "--targets",
            "3.15.0:cpython",
            str(output),
            str(source / "pylock.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "setuptools==" in output.read_text()


@pytest.mark.parametrize(
    ("version", "accepted"),
    [pytest.param("81.0.0", True, id="compatible"), pytest.param("79.0.0", False, id="incompatible")],
)
def test_export_build_constraints_prefers_compatible_caller_build_pin(
    tmp_path: Path, version: str, accepted: bool
) -> None:
    source = Path(__file__).resolve().parents[2]
    shared = source / "pylock.toml"
    caller = tmp_path / "pylock.toml"
    document = tomlkit.parse(shared.read_text())
    for package in document["packages"]:
        if package["name"] == "setuptools":
            package["version"] = version
            for wheel in package["wheels"]:
                wheel["name"] = wheel["name"].replace("84.0.0", version)
                wheel["url"] = wheel["url"].replace("84.0.0", version)
            package["sdist"]["name"] = package["sdist"]["name"].replace("84.0.0", version)
            package["sdist"]["url"] = package["sdist"]["url"].replace("84.0.0", version)
    caller.write_text(tomlkit.dumps(document))
    output = tmp_path / "constraints.txt"
    result = subprocess.run(
        [
            sys.executable,
            str(source / "tools/build_constraints.py"),
            "--shared-policy",
            str(source / "pyproject.toml"),
            str(output),
            str(shared),
            str(caller),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) == accepted
    if accepted:
        assert f"setuptools=={version} " in output.read_text()
    else:
        assert "violates setuptools>=80" in result.stderr


@pytest.mark.parametrize(
    ("platform", "targets"),
    [
        pytest.param("macos_arm64", "3.15.0:cpython 3.11.0:pypy", id="macos-pypy"),
        pytest.param("windows_arm64", "3.15.0:cpython", id="windows-arm"),
    ],
)
def test_export_build_constraints_selects_explicit_targets(tmp_path: Path, platform: str, targets: str) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = tmp_path / "pylock.build.toml"
    write_matrix_lock(lock)
    output = tmp_path / "constraints.txt"
    result = subprocess.run(
        [
            sys.executable,
            str(source / "tools/build_constraints.py"),
            "--target-platform",
            platform,
            "--targets",
            targets,
            str(output),
            str(lock),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"example==1.0 --hash=sha256:{'0' * 64}\n"


def test_export_build_constraints_action_selects_secondary_lock(tmp_path: Path, action_scripts: Path) -> None:
    write_matrix_lock(tmp_path / "pylock.build.toml")

    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "export-build-constraints",
        version="",
        LOCK="pylock.build.toml",
        TARGET_PLATFORM="macos_arm64",
        TARGETS="3.15.0:cpython",
    )

    assert result.returncode == 0, result.stderr
    output = Path((tmp_path / "output").read_text().splitlines()[-1].removeprefix("path="))
    assert output.read_text() == f"example==1.0 --hash=sha256:{'0' * 64}\n"


def test_export_build_constraints_rejects_different_target_versions(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = tmp_path / "pylock.build.toml"
    write_matrix_lock(lock)
    lock.write_text(
        lock.read_text().replace('version = "1.0"', 'version = "1.0"\nmarker = \'implementation_name == "pypy"\'')
        + dedent(
            """\
            [[packages]]
            name = "example"
            version = "2.0"
            marker = 'implementation_name == "cpython"'
            index = "https://pypi.org/simple/"
            [[packages.wheels]]
            name = "example-2.0-py3-none-any.whl"
            url = "https://files.pythonhosted.org/example-2.0-py3-none-any.whl"
            hashes.sha256 = "1111111111111111111111111111111111111111111111111111111111111111"
            """,
        ),
    )
    result = subprocess.run(
        [
            sys.executable,
            str(source / "tools/build_constraints.py"),
            "--target-platform",
            "macos_arm64",
            "--targets",
            "3.15.0:cpython 3.11.0:pypy",
            str(tmp_path / "constraints.txt"),
            str(lock),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "versions differ across requested targets" in result.stderr


@pytest.mark.parametrize(
    ("version", "selected"),
    [
        pytest.param("3.15.1", True, id="full-version-selected"),
        pytest.param("3.15.0", False, id="full-version-excluded"),
    ],
)
def test_export_build_constraints_uses_full_python_version(tmp_path: Path, version: str, selected: bool) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = tmp_path / "pylock.build.toml"
    write_matrix_lock(lock)
    lock.write_text(
        lock.read_text().replace(
            'index = "https://pypi.org/simple/"',
            'marker = \'python_full_version >= "3.15.1"\'\nindex = "https://pypi.org/simple/"',
        ),
    )
    output = tmp_path / "constraints.txt"
    result = subprocess.run(
        [
            sys.executable,
            str(source / "tools/build_constraints.py"),
            "--target-platform",
            "macos_arm64",
            "--targets",
            f"{version}:cpython",
            str(output),
            str(lock),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert ("example==1.0" in output.read_text()) == selected


def write_matrix_lock(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            lock-version = "1.0"
            created-by = "test"
            requires-python = ">=3.11"
            environments = [
              'python_version == "3.11" and sys_platform == "darwin" and platform_machine == "arm64" and implementation_name == "pypy"',
              'python_version == "3.15" and sys_platform == "darwin" and platform_machine == "arm64" and implementation_name == "cpython"',
              'python_version == "3.15" and sys_platform == "win32" and platform_machine == "ARM64" and implementation_name == "cpython"',
            ]
            [[packages]]
            name = "example"
            version = "1.0"
            index = "https://pypi.org/simple/"
            [[packages.wheels]]
            name = "example-1.0-py3-none-any.whl"
            url = "https://files.pythonhosted.org/example-1.0-py3-none-any.whl"
            hashes.sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
            """,
        ),
    )

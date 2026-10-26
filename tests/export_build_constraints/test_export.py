from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from textwrap import dedent

import pytest
import tomlkit
from conftest import CALLER, action


def test_export_build_constraints_uses_checked_in_locks(tmp_path: Path, action_scripts: Path) -> None:
    (tmp_path / "pylock.toml").write_bytes((CALLER / "pylock.toml").read_bytes())
    (tmp_path / "pyproject.toml").write_bytes((CALLER / "pyproject.toml").read_bytes())
    outputs: dict[str, str] = {}
    result = action(tmp_path, tmp_path, action_scripts, "export-build-constraints", outputs, version="")
    assert result.returncode == 0, result.stderr
    output = Path(outputs["path"])
    constraints = output.read_text()
    assert "cython==" in constraints
    assert "setuptools==" in constraints
    assert "pytest==" not in constraints
    assert output == next(tmp_path.glob("build-constraints-*.txt"))


def test_export_build_constraints_accepts_tool_only_project_without_build_group(
    tmp_path: Path, action_scripts: Path
) -> None:
    (tmp_path / "pyproject.toml").write_bytes((CALLER / "pyproject.toml").read_bytes())
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    document["dependency-groups"].remove("build")
    (tmp_path / "pylock.toml").write_text(tomlkit.dumps(document))
    outputs: dict[str, str] = {}

    result = action(tmp_path, tmp_path, action_scripts, "export-build-constraints", outputs, version="")

    assert result.returncode == 0, result.stderr
    assert Path(outputs["path"]).read_text() == ""


def test_export_build_constraints_writes_empty_file_without_build_selection(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    document = tomlkit.parse((CALLER / "pylock.toml").read_text())
    document["dependency-groups"].remove("build")
    lock = tmp_path / "pylock.toml"
    lock.write_text(tomlkit.dumps(document))
    output = tmp_path / "constraints.txt"

    result = subprocess.run(
        [sys.executable, str(source / "tools/build_constraints.py"), str(output), str(lock)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text() == ""


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
            str(CALLER / "pylock.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "setuptools==" in output.read_text()


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


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param("local-package", "must be an index version", id="local-package"),
        pytest.param("missing-hash", "has no SHA256 hash", id="missing-hash"),
    ],
)
def test_export_build_constraints_rejects_untrusted_build_packages(tmp_path: Path, change: str, message: str) -> None:
    source = Path(__file__).resolve().parents[2]
    lock = tmp_path / "pylock.build.toml"
    write_matrix_lock(lock)
    content = lock.read_text()
    if change == "local-package":
        content = content.replace('index = "https://pypi.org/simple/"', 'directory = { path = "." }')
        content = content.replace("[[packages.wheels]]", "")
        content = (
            content[: content.index('name = "example-1.0-py3-none-any.whl"')]
            + "[tool.nab]\ncreated-at = 2026-10-23T00:00:00Z\n"
        )
    else:
        content = content.replace('hashes.sha256 = "' + "0" * 64 + '"', 'hashes.sha512 = "' + "0" * 128 + '"')
    lock.write_text(content)

    result = subprocess.run(
        [
            sys.executable,
            str(source / "tools/build_constraints.py"),
            "--target-platform",
            "macos_arm64",
            "--targets",
            "3.15.0:cpython",
            str(tmp_path / "constraints.txt"),
            str(lock),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_export_build_constraints_action_selects_secondary_lock(tmp_path: Path, action_scripts: Path) -> None:
    expected = write_published_matrix_lock(tmp_path / "pylock.build.toml")

    outputs: dict[str, str] = {}
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "export-build-constraints",
        outputs,
        version="",
        LOCK="pylock.build.toml",
        TARGET_PLATFORM="macos_arm64",
        TARGETS="3.15.0:cpython",
    )

    assert result.returncode == 0, result.stderr
    output = Path(outputs["path"])
    assert output.read_text() == expected


def test_build_constraints_import_has_no_cli_side_effect() -> None:
    script = Path(__file__).resolve().parents[2] / "tools/build_constraints.py"
    result = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(script)!r}, run_name='imported')"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


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


def write_published_matrix_lock(path: Path) -> str:
    write_matrix_lock(path)
    (path.parent / "pyproject.toml").write_bytes((CALLER / "pyproject.toml").read_bytes())
    package = next(
        package
        for package in tomllib.loads((CALLER / "pylock.toml").read_text())["packages"]
        if package["name"] == "packaging"
    )
    document = tomlkit.parse(path.read_text())
    document["packages"][0]["name"] = package["name"]
    document["packages"][0]["version"] = package["version"]
    document["packages"][0]["wheels"] = package["wheels"]
    document["packages"][0]["sdist"] = package["sdist"]
    path.write_text(tomlkit.dumps(document))
    hashes = {artifact["hashes"]["sha256"] for artifact in [*package["wheels"], package["sdist"]]}
    return f"packaging=={package['version']} {' '.join(f'--hash=sha256:{digest}' for digest in sorted(hashes))}\n"


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
            upload-time = 2026-10-01T00:00:00Z
            hashes.sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
            [tool.nab]
            created-at = 2026-10-23T00:00:00Z
            """,
        ),
    )

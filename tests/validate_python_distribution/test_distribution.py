from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from conftest import action, run


@pytest.fixture
def distribution(source_project: Path, nab_executable: Path) -> tuple[Path, Path]:
    project = source_project / "pyproject.toml"
    project.write_text(
        project.read_text() + '\n[dependency-groups]\npkg-meta = ["check-wheel-contents>=0.6.3", "twine>=7"]\n',
    )
    run(
        source_project,
        str(nab_executable),
        "lock",
        "--python",
        "3.15",
        "--groups",
        "pkg-meta",
    )
    output = source_project / "dist"
    run(source_project, "uv", "build", "--python", "3.15", "--sdist", "--wheel", "--out-dir", str(output))
    return source_project, output


def test_validate_python_distribution_accepts_built_files(
    distribution: tuple[Path, Path], tmp_path: Path, action_scripts: Path
) -> None:
    repository = distribution[0]
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-python-distribution",
        version="0.2.0",
    )
    assert result.returncode == 0, result.stderr
    assert "PASSED" in result.stdout


def test_validate_python_distribution_rejects_invalid_sdist(
    distribution: tuple[Path, Path], tmp_path: Path, action_scripts: Path
) -> None:
    repository, output = distribution
    next(output.glob("*.tar.gz")).write_bytes(b"invalid sdist")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-python-distribution",
        version="0.2.0",
    )
    assert result.returncode != 0


def test_validate_python_distribution_rejects_bad_wheel_contents(
    distribution: tuple[Path, Path], tmp_path: Path, action_scripts: Path
) -> None:
    repository, output = distribution
    wheel = next(output.glob("*.whl"))
    with ZipFile(wheel) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    record = next(name for name in contents if name.endswith(".dist-info/RECORD"))
    contents["fixture/compiled.pyc"] = b"invalid bytecode"
    contents[record] += b"fixture/compiled.pyc,,\n"
    with ZipFile(wheel, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-python-distribution",
        version="0.2.0",
    )
    assert result.returncode != 0
    assert "W001" in result.stdout

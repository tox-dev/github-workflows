from __future__ import annotations

from textwrap import dedent
from zipfile import ZipFile
lazy from pathlib import Path

import pytest
from conftest import action, run


@pytest.fixture
def distribution(repository: Path, tmp_path: Path) -> tuple[Path, Path]:
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        + dedent(
            """
            [project]
            name = "fixture"
            version = "0.2.0"
            requires-python = ">=3.15"

            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"

            [dependency-groups]
            pkg-meta = ["check-wheel-contents>=0.6.3", "twine>=7"]
            """,
        ),
    )
    package = repository / "src/fixture"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Fixture package."""\n')
    run(repository, "release-creator", "locks", "--output", "pylock.toml", "--tool-python", ">=3.15")
    output = tmp_path / "dist"
    run(repository, "uv", "build", "--python", "3.15", "--sdist", "--wheel", "--out-dir", str(output))
    return repository, output


def test_validate_python_distribution_accepts_built_files(
    distribution: tuple[Path, Path], tmp_path: Path, action_scripts: Path
) -> None:
    repository, output = distribution
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-python-distribution",
        version="0.2.0",
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        VALIDATION_GROUP="pkg-meta",
        OUT_DIR=str(output),
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
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        VALIDATION_GROUP="pkg-meta",
        OUT_DIR=str(output),
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
        LOCK="pylock.toml",
        PYTHON_VERSION="3.15",
        VALIDATION_GROUP="pkg-meta",
        OUT_DIR=str(output),
    )
    assert result.returncode != 0
    assert "W001" in result.stdout

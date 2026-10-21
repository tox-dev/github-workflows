from __future__ import annotations

from textwrap import dedent
lazy from pathlib import Path

import pytest
from conftest import action, run


@pytest.fixture
def build_repository(repository: Path) -> Path:
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
            """,
        ),
    )
    package = repository / "src/fixture"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('"""Fixture package."""\n')
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add package source")
    run(repository, "git", "push", "origin", "main")
    return repository


def test_build_python_distribution_creates_wheel_and_sdist(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        PYTHON_VERSION="3.15",
        SOURCE=".",
        OUT_DIR=str(tmp_path / "dist"),
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert {path.name for path in (tmp_path / "dist").iterdir() if path.suffix in {".whl", ".gz"}} == {
        "fixture-0.2.0-py3-none-any.whl",
        "fixture-0.2.0.tar.gz",
    }


def test_build_python_distribution_rejects_dirty_source(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    (build_repository / "pyproject.toml").write_text((build_repository / "pyproject.toml").read_text() + "\n")
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        PYTHON_VERSION="3.15",
        SOURCE=".",
        OUT_DIR=str(tmp_path / "dist"),
        RUNNER_TEMP=str(tmp_path),
    )
    assert "tagged source is dirty" in result.stderr


def test_build_python_distribution_does_not_run_hooks(
    build_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    config = build_repository / ".pre-commit-config.yaml"
    config.write_text(config.read_text().replace("entry: bash -c true", "entry: bash -c 'touch generated-file'"))
    run(build_repository, "git", "add", ".")
    run(build_repository, "git", "commit", "-m", "Create an untracked output")
    result = action(
        build_repository,
        tmp_path,
        action_scripts,
        "build-python-distribution",
        version="0.2.0",
        PYTHON_VERSION="3.15",
        SOURCE=".",
        OUT_DIR=str(tmp_path / "dist"),
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert not (build_repository / "generated-file").exists()

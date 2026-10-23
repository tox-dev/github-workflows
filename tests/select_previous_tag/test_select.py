from pathlib import Path

import pytest
from conftest import action, run


def test_select_previous_tag_uses_version_order(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    for tag in ("0.2.0", "0.10.0", "1.0.0"):
        run(repository, "git", "tag", tag)
    result = action(repository, tmp_path, action_scripts, "select-previous-tag", version="1.0.0", TAG="1.0.0")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "previous=0.10.0\n"


def test_select_previous_tag_accepts_first_release(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "select-previous-tag", version="0.1.0", TAG="0.1.0")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "previous=\n"


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("1.1.0", id="bare-version"),
        pytest.param("pyproject-fmt/1.1.0", id="qualified-tag"),
    ],
)
def test_select_previous_tag_scopes_package(
    repository: Path, tmp_path: Path, action_scripts: Path, target: str
) -> None:
    for tag in ("pyproject-fmt/1.0.0", "pyproject-fmt/1.1.0", "tox-toml-fmt/1.0.5"):
        run(repository, "git", "tag", tag)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "select-previous-tag",
        version=target,
        TAG=target,
        PACKAGE="pyproject-fmt",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "previous=pyproject-fmt/1.0.0\n"


@pytest.mark.parametrize(
    ("stable_only", "previous"),
    [
        pytest.param("false", "v1.1.0rc1", id="include-prerelease"),
        pytest.param("true", "v1.0.0", id="stable-only"),
    ],
)
def test_select_previous_tag_filters_prereleases(
    repository: Path, tmp_path: Path, action_scripts: Path, stable_only: str, previous: str
) -> None:
    for tag in ("v1.0.0", "v1.1.0rc1", "v1.1.0"):
        run(repository, "git", "tag", tag)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "select-previous-tag",
        version="v1.1.0",
        TAG="v1.1.0",
        STABLE_ONLY=stable_only,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"previous={previous}\n"


def test_select_previous_tag_requires_current_tag(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(repository, tmp_path, action_scripts, "select-previous-tag", version="0.2.0", TAG="0.2.0")
    assert result.returncode != 0
    assert not (tmp_path / "output").exists()

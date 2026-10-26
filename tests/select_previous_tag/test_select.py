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


def test_select_previous_tag_includes_prerelease(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    for tag in ("v1.0.0", "v1.1.0rc1", "v1.1.0"):
        run(repository, "git", "tag", tag)

    result = action(repository, tmp_path, action_scripts, "select-previous-tag", version="v1.1.0", TAG="v1.1.0")

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "previous=v1.1.0rc1\n"


def test_select_previous_tag_scopes_namespaced_tags(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    for tag in ("pyproject-fmt/1.1.0", "tox-toml-fmt/5.0.0", "pyproject-fmt/1.2.0"):
        run(repository, "git", "tag", tag)

    result = action(
        repository,
        tmp_path,
        action_scripts,
        "select-previous-tag",
        version="pyproject-fmt/1.2.0",
        TAG="pyproject-fmt/1.2.0",
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "previous=pyproject-fmt/1.1.0\n"


@pytest.mark.parametrize(
    ("tag", "explanation"),
    [
        pytest.param("1.0.0", "Previous release tag: 0.10.0 (newest release tag before 1.0.0)", id="previous"),
        pytest.param("0.1.0", "Previous release tag: none (0.1.0 is the first release)", id="first"),
    ],
)
def test_select_previous_tag_explains_choice(
    repository: Path, tmp_path: Path, action_scripts: Path, tag: str, explanation: str
) -> None:
    for existing in ("0.2.0", "0.10.0", "1.0.0"):
        run(repository, "git", "tag", existing)

    result = action(repository, tmp_path, action_scripts, "select-previous-tag", version=tag, TAG=tag)

    assert explanation in result.stdout.splitlines()

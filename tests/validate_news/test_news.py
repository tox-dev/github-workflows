from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import action, run


@pytest.mark.parametrize(
    ("bot", "skip", "accepted"),
    [
        pytest.param("false", "false", False, id="human-needs-fragment"),
        pytest.param("true", "false", True, id="bot-needs-no-fragment"),
        pytest.param("false", "true", True, id="human-can-skip-news"),
    ],
)
def test_validate_news_without_fragment(
    repository: Path, tmp_path: Path, action_scripts: Path, bot: str, skip: str, accepted: bool
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR=bot,
        SKIP_NEWS=skip,
    )
    assert (result.returncode == 0) == accepted
    if not accepted:
        assert "add a changelog fragment" in result.stderr


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("+addition.feature.md", id="named"),
        pytest.param("+addition.feature.1.md", id="named-multiple"),
        pytest.param("123.feature.2.md", id="numbered-multiple"),
    ],
)
def test_validate_news_checks_bot_fragment(repository: Path, tmp_path: Path, action_scripts: Path, name: str) -> None:
    (repository / "changelog.d" / name).write_text("Add another feature.\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add news")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR="true",
        SKIP_NEWS="true",
    )
    assert result.returncode == 0, result.stderr


def test_validate_news_reads_rst_categories(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        .replace('directory = "changelog.d"', 'directory = "docs/changelog"')
        .replace('filename = "CHANGELOG.md"', 'filename = "CHANGELOG.rst"')
        .replace('directory = "feature", name = "Added"', 'directory = "fix", name = "Fixed"')
    )
    (repository / "docs").mkdir()
    (repository / "docs/changelog").mkdir()
    (repository / "docs/changelog/+repair.fix.rst").write_text("Repair a user-facing bug.\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add RST news")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR="false",
        SKIP_NEWS="false",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("name", "content", "error"),
    [
        pytest.param("+addition.unknown.md", "Add a feature.\n", "unsupported changelog fragment", id="category"),
        pytest.param("addition.feature.md", "Add a feature.\n", "unsupported changelog fragment", id="name"),
        pytest.param("+addition.feature.x.md", "Add a feature.\n", "unsupported changelog fragment", id="ordinal"),
        pytest.param("+addition.feature.md", " \n", "empty changelog fragment", id="empty"),
    ],
)
def test_validate_news_rejects_bad_fragment(
    repository: Path, tmp_path: Path, action_scripts: Path, name: str, content: str, error: str
) -> None:
    (repository / "changelog.d" / name).write_text(content)
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add news")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR="true",
        SKIP_NEWS="false",
    )
    assert result.returncode != 0
    assert error in result.stderr


def test_validate_news_requires_pr_base(repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="",
        BOT_AUTHOR="true",
        SKIP_NEWS="false",
    )
    assert result.returncode != 0
    assert "news validation needs a PR base" in result.stderr


def test_validate_news_forwards_secondary_lock_inputs() -> None:
    config = yaml.safe_load((Path(__file__).resolve().parents[2] / "validate-news/action.yml").read_text())
    refresh = next(step for step in config["runs"]["steps"] if step.get("uses") == "$/refresh-release-lock")
    secondary = [name for name in config["inputs"] if name.startswith("additional-")]

    assert secondary
    assert all(refresh["with"][name] == "${{ inputs." + name + " }}" for name in secondary)
    assert refresh["with"]["mode"] == "check"
    assert refresh["with"]["keep-uv-lock"] == "${{ inputs.keep-uv-lock }}"


@pytest.mark.parametrize(
    ("additional_lock", "keep_uv_lock", "changed_path", "changed"),
    [
        pytest.param("pylock.zipapp.toml", False, "pylock.zipapp.toml", "true", id="selected-secondary-lock"),
        pytest.param("", False, "pylock.zipapp.toml", "false", id="unselected-secondary-lock"),
        pytest.param("", False, "pyproject.toml", "true", id="root-project"),
        pytest.param("", False, ".github/workflows/release.yaml", "true", id="workflow-repin"),
        pytest.param("", False, "README.md", "false", id="unrelated"),
        pytest.param("", False, "nab.toml", "true", id="nab-policy"),
        pytest.param("", False, "meta/pyproject.toml", "true", id="workspace-member"),
        pytest.param("", True, "uv.lock", "true", id="selected-native-uv-lock"),
        pytest.param("", False, "uv.lock", "false", id="unselected-native-uv-lock"),
    ],
)
def test_validate_news_detects_release_input_change(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    additional_lock: str,
    keep_uv_lock: bool,
    changed_path: str,
    changed: str,
) -> None:
    (repository / "pyproject.toml").write_text(
        (repository / "pyproject.toml").read_text() + "\n[dependency-groups]\nrelease-news = []\n"
    )
    (repository / "pylock.toml").write_text(
        '[tool.nab]\ncommand-line = ["nab", "lock", "--groups", "release-news", "--output", "pylock.toml"]\n'
    )
    (repository / "pylock.zipapp.toml").write_text("lock-version = '1.0'\n")
    (repository / "uv.lock").write_text("version = 1\n")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add release locks")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "checkout", "-b", "change-secondary-lock")
    (repository / changed_path).parent.mkdir(parents=True, exist_ok=True)
    (repository / changed_path).write_text(
        "[tool.nab]\nuploaded-prior-to = false\n"
        if changed_path == "nab.toml"
        else (repository / changed_path).read_text() + "\n"
        if changed_path == "pyproject.toml"
        else "lock-version = '1.0'\ncreated-by = 'test'\n"
    )
    run(repository, "git", "add", changed_path)
    run(repository, "git", "commit", "-m", "Refresh secondary lock")
    output = tmp_path / "lock-change-output"

    result = subprocess.run(
        ["bash", str(action_scripts / "validate-news-2.sh")],
        cwd=repository,
        env=os.environ
        | {
            "BASE_REF": "main",
            "ADDITIONAL_LOCK": additional_lock,
            "KEEP_UV_LOCK": str(keep_uv_lock).lower(),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "validate-news"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"changed={changed}\n" in output.read_text()

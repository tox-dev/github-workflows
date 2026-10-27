from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
import yaml
from conftest import action, run
from pytest_httpserver import HTTPServer

_STEPS: Final = yaml.safe_load((Path(__file__).resolve().parents[2] / "validate-news/action.yml").read_text())["runs"][
    "steps"
]


def _current_labels(github_api: tuple[HTTPServer, dict[str, str]], skip: str) -> dict[str, str]:
    server, environment = github_api
    labels = [{"name": "documentation"}, *([{"name": "skip news"}] if skip == "true" else [])]
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7", method="GET").respond_with_json({"labels": labels})
    return environment


def _script(action_scripts: Path, step_id: str) -> Path:
    return action_scripts / f"validate-news-{next(i for i, step in enumerate(_STEPS) if step.get('id') == step_id)}.sh"


@pytest.mark.parametrize(
    ("bot", "skip", "accepted"),
    [
        pytest.param("false", "false", False, id="human-needs-fragment"),
        pytest.param("true", "false", True, id="bot-needs-no-fragment"),
        pytest.param("false", "true", True, id="human-can-skip-news"),
    ],
)
def test_validate_news_without_fragment(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    bot: str,
    skip: str,
    accepted: bool,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR=bot,
        **_current_labels(github_api, skip),
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
def test_validate_news_checks_bot_fragment(
    repository: Path, tmp_path: Path, action_scripts: Path, name: str, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
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
        **_current_labels(github_api, "true"),
    )
    assert result.returncode == 0, result.stderr


def test_validate_news_reads_rst_categories(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
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
        **_current_labels(github_api, "false"),
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
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    name: str,
    content: str,
    error: str,
    github_api: tuple[HTTPServer, dict[str, str]],
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
        **_current_labels(github_api, "false"),
    )
    assert result.returncode != 0
    assert error in result.stderr


def test_validate_news_requires_pr_base(
    repository: Path, tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="",
        BOT_AUTHOR="true",
        **_current_labels(github_api, "false"),
    )
    assert result.returncode != 0
    assert "origin/" in result.stderr


@pytest.mark.parametrize(
    ("additional_lock", "changed_path", "changed"),
    [
        pytest.param("pylock.zipapp.toml", "pylock.zipapp.toml", "true", id="selected-secondary-lock"),
        pytest.param("", "pylock.zipapp.toml", "true", id="unselected-secondary-lock"),
        pytest.param("", "pylock.toml", "true", id="primary-lock"),
        pytest.param("", "pyproject.toml", "true", id="root-project"),
        pytest.param("", ".github/workflows/release.yaml", "false", id="workflow-repin"),
        pytest.param("", "README.md", "false", id="unrelated"),
        pytest.param("", "nab.toml", "true", id="nab-policy"),
        pytest.param("", "meta/pyproject.toml", "true", id="workspace-member"),
        pytest.param("", "uv.lock", "false", id="native-uv-lock"),
    ],
)
def test_validate_news_detects_release_input_change(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    additional_lock: str,
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
        if changed_path in {"pylock.toml", "pyproject.toml"}
        else "lock-version = '1.0'\ncreated-by = 'test'\n"
    )
    run(repository, "git", "add", changed_path)
    run(repository, "git", "commit", "-m", "Refresh secondary lock")
    output = tmp_path / "lock-change-output"

    result = subprocess.run(
        ["bash", str(_script(action_scripts, "lock-change"))],
        cwd=repository,
        env=os.environ
        | {
            "BASE_REF": "main",
            "ADDITIONAL_LOCK": additional_lock,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "validate-news"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"changed={changed}\n" in output.read_text()


@pytest.mark.parametrize(
    ("nab_config", "additional_lock", "accepted"),
    [
        pytest.param("pyproject.toml", "", False, id="pyproject-nab-table"),
        pytest.param("nab.toml", "", False, id="nab-toml"),
        pytest.param("", "pylock.zipapp.toml", False, id="secondary-lock"),
        pytest.param("", "", True, id="no-lock-producer"),
    ],
)
def test_validate_news_checks_removed_release_lock(
    repository: Path, tmp_path: Path, action_scripts: Path, nab_config: str, additional_lock: str, accepted: bool
) -> None:
    (repository / "pylock.toml").write_text("lock-version = '1.0'\n")
    match nab_config:
        case "pyproject.toml":
            project = repository / "pyproject.toml"
            project.write_text(project.read_text() + '\n[tool.nab]\nuploaded-prior-to = "P7D"\n')
        case "nab.toml":
            (repository / "nab.toml").write_text('uploaded-prior-to = "P7D"\n')
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Add release lock")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "checkout", "-b", "remove-lock")
    run(repository, "git", "rm", "-q", "pylock.toml")
    run(repository, "git", "commit", "-m", "Remove release lock")

    result = subprocess.run(
        ["bash", str(_script(action_scripts, "lock-change"))],
        cwd=repository,
        env=os.environ
        | {
            "BASE_REF": "main",
            "ADDITIONAL_LOCK": additional_lock,
            "GITHUB_OUTPUT": str(tmp_path / "lock-change-output"),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "validate-news"),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted, result.stderr
    assert ("the release lock was removed" in result.stderr) is not accepted


@pytest.mark.parametrize(
    ("change", "accepted"),
    [
        pytest.param('dependencies = ["six"]', False, id="stale-lock"),
        pytest.param("dependencies = []  # unchanged", True, id="current-lock"),
    ],
)
def test_validate_news_checks_changed_release_inputs_against_the_lock(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    nab_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    accepted: bool,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    monkeypatch.delenv("SSL_CERT_FILE")
    project = repository / "pyproject.toml"
    project.write_text(
        project.read_text()
        + '\n[project]\nname = "fixture"\nversion = "0.2.0"\nrequires-python = ">=3.15"\ndependencies = []\n'
        + '\n[tool.nab]\nuploaded-prior-to = "P7D"\nbase-group = "project-runtime"\n'
    )
    run(repository, str(nab_executable), "lock", "--all-groups", "--all-extras", "--no-cache")
    run(repository, "git", "add", ".")
    run(repository, "git", "commit", "-m", "Lock the project")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "checkout", "-b", "add-dependency")
    project.write_text(project.read_text().replace("dependencies = []", change))
    run(repository, "git", "commit", "-am", "Change the project")

    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        **_current_labels(github_api, "true"),
    )

    assert (result.returncode == 0) is accepted, result.stderr
    assert ("regenerated Nab lock differs from the committed lock" in result.stderr) is not accepted


def test_validate_news_skips_lock_removal_guard_without_deletion(
    repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text() + '\n[tool.nab]\nuploaded-prior-to = "P7D"\n')
    run(repository, "git", "commit", "-am", "Configure Nab without a lock")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "checkout", "-b", "change-project")
    project.write_text(project.read_text() + "\n")
    run(repository, "git", "commit", "-am", "Change the project")
    output = tmp_path / "lock-change-output"

    result = subprocess.run(
        ["bash", str(_script(action_scripts, "lock-change"))],
        cwd=repository,
        env=os.environ | {"BASE_REF": "main", "ADDITIONAL_LOCK": "", "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text() == "changed=false\n"


@pytest.mark.parametrize(
    ("path", "content", "fragments", "config"),
    [
        pytest.param("changelog.d/+other.feature.md", "Add more.\n", "true", "false", id="fragment"),
        pytest.param("README.md", "Read me.\n", "false", "false", id="unrelated"),
        pytest.param("pyproject.toml", None, "false", "false", id="project-without-towncrier-change"),
        pytest.param("pyproject.toml", "", "false", "true", id="towncrier-table"),
        pytest.param("towncrier.toml", "[tool.towncrier]\n", "false", "true", id="towncrier-file"),
    ],
)
def test_validate_news_detects_news_input_change(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    path: str,
    content: str | None,
    fragments: str,
    config: str,
) -> None:
    run(repository, "git", "checkout", "-b", "change-news-input")
    target = repository / path
    if content is None:
        target.write_text(target.read_text() + "\n[project]\nname = 'fixture'\n")
    elif path == "pyproject.toml":
        target.write_text(target.read_text().replace('name = "fixture"', 'name = "renamed"'))
    else:
        target.write_text(content)
    run(repository, "git", "add", path)
    run(repository, "git", "commit", "-m", "Change a news input")
    output = tmp_path / "news-change-output"

    result = subprocess.run(
        ["bash", str(_script(action_scripts, "news-change"))],
        cwd=repository,
        env=os.environ | {"BASE_REF": "main", "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"fragments={fragments}\nconfig={config}\n"


@pytest.mark.parametrize(
    ("touched", "accepted"),
    [
        pytest.param("README.md", True, id="untouched-config-skipped"),
        pytest.param("pyproject.toml", False, id="touched-config-checked"),
    ],
)
def test_validate_news_checks_towncrier_config_only_when_touched(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    touched: str,
    accepted: bool,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    project = repository / "pyproject.toml"
    project.write_text(project.read_text().replace('directory = "changelog.d"\n', 'package = "fixture"\n'))
    run(repository, "git", "commit", "-am", "Drop the fragment directory")
    run(repository, "git", "push", "origin", "main")
    run(repository, "git", "checkout", "-b", "change-news-input")
    target = repository / touched
    target.write_text(
        target.read_text().replace('name = "fixture"', 'name = "renamed"') if touched == "pyproject.toml" else "Read.\n"
    )
    run(repository, "git", "add", touched)
    run(repository, "git", "commit", "-m", "Touch a file")

    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        **_current_labels(github_api, "true"),
    )

    assert (result.returncode == 0) is accepted, result.stderr
    assert ("set an explicit Towncrier fragment directory" in result.stderr) is not accepted


@pytest.mark.parametrize(
    ("bot", "skip", "explanation"),
    [
        pytest.param("true", "false", "News requirement: waived for a bot author", id="bot"),
        pytest.param("false", "true", "News requirement: waived by the skip news label", id="skip-news"),
        pytest.param("true", "true", "Fragment check skipped: nothing changed in changelog.d", id="fragments"),
        pytest.param("true", "true", "Lock check skipped: no lock inputs changed", id="lock"),
    ],
)
def test_validate_news_explains_choices(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    bot: str,
    skip: str,
    explanation: str,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "validate-news",
        version="0.2.0",
        BASE_REF="main",
        BOT_AUTHOR=bot,
        **_current_labels(github_api, skip),
    )

    assert explanation in result.stdout

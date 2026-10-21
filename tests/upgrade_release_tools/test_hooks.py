from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from conftest import run


@pytest.fixture
def hook_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n    hooks:\n      - id: test\n        name: test\n"
        "        entry: python -c 'pass'\n        language: python\n"
        "        additional_dependencies: [mdformat-gfm==0.1.0]\n"
    )
    run(repository, "git", "init", "-b", "main")
    run(repository, "git", "add", ".")
    run(repository, "git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "Initial")
    return repository


def test_hook_refresh_resolves_exact_pin(hook_repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    installed = execute(hook_repository, action_scripts / "refresh-hook-pins-0.sh", tmp_path, PYTHON_VERSION="3.15")
    assert installed.returncode == 0, installed.stderr
    refreshed = execute(
        hook_repository,
        action_scripts / "refresh-hook-pins-2.sh",
        tmp_path,
        CONFIG=".pre-commit-config.yaml",
        PYTHON_VERSION="3.15",
        CUTOFF="2026-10-14T00:00:00Z",
    )
    assert refreshed.returncode == 0, refreshed.stderr
    checked = execute(
        hook_repository, action_scripts / "refresh-hook-pins-3.sh", tmp_path, CONFIG=".pre-commit-config.yaml"
    )
    assert checked.returncode == 0, checked.stderr
    config = yaml.safe_load((hook_repository / ".pre-commit-config.yaml").read_text())
    assert config["repos"][0]["hooks"][0]["additional_dependencies"] == ["mdformat-gfm==1.0.0"]


@pytest.mark.parametrize(
    ("path", "accepted"),
    [(None, True), (".pre-commit-config.yaml", True), ("other.txt", False)],
    ids=["clean", "hook-config", "other-file"],
)
def test_hook_refresh_checks_paths(
    hook_repository: Path, tmp_path: Path, action_scripts: Path, path: str | None, accepted: bool
) -> None:
    if path is not None:
        (hook_repository / path).write_text("updated\n")
    result = execute(
        hook_repository, action_scripts / "refresh-hook-pins-4.sh", tmp_path, CONFIG=".pre-commit-config.yaml"
    )
    assert (result.returncode == 0) == accepted
    assert ("unexpected path" in result.stderr) == (not accepted)


@pytest.mark.parametrize("changed", [False, True], ids=["unchanged", "changed"])
def test_hook_refresh_emits_patch(hook_repository: Path, tmp_path: Path, action_scripts: Path, changed: bool) -> None:
    if changed:
        (hook_repository / ".pre-commit-config.yaml").write_text("repos: []\n")
    result = execute(
        hook_repository,
        action_scripts / "refresh-hook-pins-5.sh",
        tmp_path,
        CONFIG=".pre-commit-config.yaml",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"changed={str(changed).lower()}\n"
    assert (tmp_path / "hooks.patch").exists() == changed


def test_hook_refresh_uses_seven_day_cutoff(hook_repository: Path, tmp_path: Path, action_scripts: Path) -> None:
    result = execute(
        hook_repository,
        action_scripts / "refresh-hook-pins-1.sh",
        tmp_path,
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    assert result.returncode == 0, result.stderr
    cutoff = datetime.fromisoformat((tmp_path / "output").read_text().removeprefix("timestamp=").strip())
    assert abs(datetime.now(UTC) - cutoff - timedelta(days=7)) < timedelta(minutes=1)


def execute(repository: Path, script: Path, temporary: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=repository,
        env=os.environ
        | {
            "RUNNER_TEMP": str(temporary),
            "GITHUB_ACTION_PATH": str(Path(__file__).resolve().parents[2] / "refresh-hook-pins"),
        }
        | environment,
        text=True,
        capture_output=True,
        check=False,
    )

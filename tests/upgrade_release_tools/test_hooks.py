from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import action, run


@pytest.fixture
def hook_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "pylock.toml").write_text(
        'lock-version = "1.0"\ncreated-by = "test"\nrequires-python = ">=3.15"\npackages = []\n',
    )
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
    result = action(
        hook_repository,
        tmp_path,
        action_scripts,
        "refresh-hook-pins",
        version="",
    )
    assert result.returncode == 0, result.stderr
    config = yaml.safe_load((hook_repository / ".pre-commit-config.yaml").read_text())
    dependencies = config["repos"][0]["hooks"][0]["additional_dependencies"]
    assert dependencies[0] == "mdformat-gfm==1.0.0"
    assert any(item.startswith("markdown-it-py==") for item in dependencies)
    assert all("==" in item for item in dependencies)


def test_hook_refresh_freezes_only_cooled_revisions(
    hook_repository: Path, tmp_path: Path, action_scripts: Path
) -> None:
    remote = tmp_path / "remote"
    remote.mkdir()
    run(remote, "git", "init", "-b", "main")
    (remote / ".pre-commit-hooks.yaml").write_text(
        "- id: fixture\n  name: fixture\n  entry: true\n  language: system\n"
    )
    run(remote, "git", "add", ".")
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "Old hook"],
        cwd=remote,
        env=os.environ | {"GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z"},
        check=True,
        capture_output=True,
    )
    run(remote, "git", "tag", "v1.0.0")
    old_commit = run(remote, "git", "rev-parse", "HEAD").stdout.strip()
    (remote / "version.txt").write_text("new\n")
    run(remote, "git", "add", ".")
    run(remote, "git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", "New hook")
    run(remote, "git", "tag", "v2.0.0")
    (hook_repository / ".pre-commit-config.yaml").write_text(
        f"repos:\n  - repo: {remote.as_uri()}\n    rev: v1.0.0\n    hooks:\n      - id: fixture\n"
    )
    result = action(
        hook_repository,
        tmp_path,
        action_scripts,
        "refresh-hook-pins",
        version="",
    )
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load((hook_repository / ".pre-commit-config.yaml").read_text())["repos"][0]["rev"] == old_commit


@pytest.mark.parametrize(
    ("path", "accepted"),
    [
        pytest.param(None, True, id="clean"),
        pytest.param(".pre-commit-config.yaml", True, id="hook-config"),
        pytest.param("other.txt", False, id="other-file"),
    ],
)
def test_hook_refresh_checks_paths(
    hook_repository: Path, tmp_path: Path, action_scripts: Path, path: str | None, accepted: bool
) -> None:
    if path is not None:
        if path == ".pre-commit-config.yaml":
            (hook_repository / path).write_text((hook_repository / path).read_text() + "# updated\n")
        else:
            (hook_repository / path).write_text("updated\n")
    result = action(hook_repository, tmp_path, action_scripts, "refresh-hook-pins", version="")
    assert (result.returncode == 0) == accepted
    assert ("unexpected path" in result.stderr) == (not accepted)


@pytest.mark.parametrize("changed", [pytest.param(False, id="unchanged"), pytest.param(True, id="changed")])
def test_hook_refresh_emits_patch(hook_repository: Path, tmp_path: Path, action_scripts: Path, changed: bool) -> None:
    if not changed:
        (hook_repository / ".pre-commit-config.yaml").write_text(
            "repos:\n  - repo: local\n    hooks:\n      - id: test\n        name: test\n"
            "        entry: python -c 'pass'\n        language: system\n"
        )
        run(hook_repository, "git", "add", ".pre-commit-config.yaml")
        run(
            hook_repository,
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "commit",
            "-m",
            "Empty hooks",
        )
    result = action(hook_repository, tmp_path, action_scripts, "refresh-hook-pins", version="")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == f"changed={str(changed).lower()}\n"
    assert (tmp_path / "hooks.patch").exists() == changed


def test_hook_refresh_uses_relative_cutoff() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "refresh-hook-pins/action.yml").read_text())
    refresh = next(step for step in action["runs"]["steps"] if step.get("name") == "Refresh exact hook dependencies")
    assert "--exclude-newer '7 days'" in refresh["run"]

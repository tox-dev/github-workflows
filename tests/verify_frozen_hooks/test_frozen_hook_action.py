from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from conftest import action, run

_LOCAL_HOOK: Final = (
    "repos:\n  - repo: local\n    hooks:\n      - id: noop\n        name: noop\n        entry: 'true'\n"
    "        language: system\n"
)


def _repository(tmp_path: Path, config: str, *extra: str) -> Path:
    repository = tmp_path / "source"
    repository.mkdir()
    run(repository, "git", "init", "-q")
    (repository / ".pre-commit-config.yaml").write_text(config)
    for path in extra:
        (repository / path).parent.mkdir(parents=True, exist_ok=True)
        (repository / path).write_text(_LOCAL_HOOK)
    run(repository, "git", "add", ".")
    run(repository, "git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "Hooks")
    return repository


def test_verify_frozen_hooks_accepts_root_configuration(tmp_path: Path, action_scripts: Path) -> None:
    repository = _repository(tmp_path, _LOCAL_HOOK)

    result = action(repository, tmp_path, action_scripts, "verify-frozen-hooks", version="")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("prek.toml", id="root-prek-toml"),
        pytest.param("sub/prek.toml", id="nested-prek-toml"),
        pytest.param(".pre-commit-config.yml", id="root-yml"),
        pytest.param("sub/.pre-commit-config.yaml", id="nested-yaml"),
    ],
)
def test_verify_frozen_hooks_rejects_other_configuration(tmp_path: Path, action_scripts: Path, path: str) -> None:
    repository = _repository(tmp_path, _LOCAL_HOOK, path)

    result = action(repository, tmp_path, action_scripts, "verify-frozen-hooks", version="")

    assert result.returncode != 0
    assert f"only in the root .pre-commit-config.yaml: {path}" in result.stderr


def test_verify_frozen_hooks_rejects_movable_revision(tmp_path: Path, action_scripts: Path) -> None:
    repository = _repository(
        tmp_path, "repos:\n  - repo: https://github.com/example/hooks\n    rev: v1\n    hooks: []\n"
    )

    result = action(repository, tmp_path, action_scripts, "verify-frozen-hooks", version="")

    assert result.returncode != 0
    assert "full lowercase commit SHA" in result.stderr


def test_verify_frozen_hooks_rejects_missing_managed_pins(tmp_path: Path, action_scripts: Path) -> None:
    repository = _repository(
        tmp_path,
        "repos:\n  - repo: local\n    hooks:\n      - id: fetch\n        name: fetch\n        entry: 'true'\n"
        "        language: python\n        additional_dependencies: [requests==2.31.0]\n",
    )

    result = action(repository, tmp_path, action_scripts, "verify-frozen-hooks", version="")

    assert result.returncode != 0
    assert "pins do not match the resolved closure" in result.stderr


def test_verify_frozen_hooks_proves_tagged_revisions_before_building_hooks(
    tmp_path: Path, action_scripts: Path
) -> None:
    repository = _repository(
        tmp_path,
        "repos:\n  - repo: local\n    hooks:\n      - id: fetch\n        name: fetch\n        entry: 'true'\n"
        "        language: python\n        additional_dependencies: [requests==2.31.0]\n",
    )

    result = action(
        repository,
        tmp_path,
        action_scripts,
        "verify-frozen-hooks",
        version="",
        GITHUB_REF="refs/tags/v1.0.0",
        GITHUB_REF_NAME="v1.0.0",
    )

    assert result.returncode != 0
    assert "pins do not match the resolved closure" not in result.stderr

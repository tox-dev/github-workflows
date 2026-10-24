from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("revision", "accepted"),
    [
        pytest.param("a" * 40, True, id="frozen"),
        pytest.param("v1.0.0", False, id="tag"),
        pytest.param("a" * 12, False, id="short-sha"),
        pytest.param("A" * 40, False, id="uppercase-sha"),
    ],
)
def test_frozen_hook_revision(tmp_path: Path, revision: str, accepted: bool) -> None:
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(f"repos:\n  - repo: https://example.org/hooks\n    rev: {revision}\n    hooks: []\n")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/check_frozen_hooks.py"), str(config)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "full lowercase commit SHA" in result.stderr


def test_frozen_hook_revision_allows_local_hook(tmp_path: Path) -> None:
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text("repos:\n  - repo: local\n    hooks: []\n")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/check_frozen_hooks.py"), str(config)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("config_text", "message"),
    [
        pytest.param("repos: null\n", "repository list", id="missing-list"),
        pytest.param("repos:\n  - local\n", "mapping with a URL", id="invalid-repository"),
    ],
)
def test_frozen_hook_revision_rejects_malformed_config(tmp_path: Path, config_text: str, message: str) -> None:
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(config_text)
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/check_frozen_hooks.py"), str(config)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_frozen_hook_import_has_no_cli_side_effect(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/check_frozen_hooks.py"), run_name="frozen_hooks")

    assert capsys.readouterr() == ("", "")

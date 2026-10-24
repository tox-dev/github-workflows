from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

import pytest


def test_lock_groups_reads_recorded_selection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\nrelease = []\nrelease-news = []\nrelease-check = []\n"
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        '[tool.nab]\ncommand-line = ["nab", "lock", "--groups", "release-news", "release-check", '
        '"--output", "pylock.toml"]\n'
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "release-news release-check\n"


@pytest.mark.parametrize(
    ("command", "message"),
    [
        pytest.param('["nab", "lock", "--output", "pylock.toml"]', "cannot read Nab lock groups", id="missing-flag"),
        pytest.param('"nab lock --groups release-news"', "must be a list of strings", id="string-command"),
        pytest.param('["nab", 42]', "must be a list of strings", id="non-string-argument"),
        pytest.param(
            '["nab", "lock", "--groups", "--output", "pylock.toml"]',
            "Nab lock records no selected groups",
            id="empty-groups",
        ),
    ],
)
def test_lock_groups_rejects_missing_selection(tmp_path: Path, command: str, message: str) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(f"[tool.nab]\ncommand-line = {command}\n")

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_lock_groups_import_has_no_cli_side_effect(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), run_name="lock_groups")

    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        pytest.param('"release-news"', "omits release groups", id="omitted-release-group"),
        pytest.param('"release-news", "release-check", "unknown"', "invalid or undeclared", id="undeclared-group"),
        pytest.param('"release-news\\nmode=refresh", "release-check"', "invalid or undeclared", id="output-injection"),
    ],
)
def test_lock_groups_rejects_untrusted_selection(tmp_path: Path, groups: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[dependency-groups]\nrelease-news = []\nrelease-check = []\n")
    lock = tmp_path / "pylock.toml"
    lock.write_text(f'[tool.nab]\ncommand-line = ["nab", "lock", "--groups", {groups}]\n')

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr

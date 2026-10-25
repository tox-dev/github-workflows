from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

_TOOL: Final = Path(__file__).resolve().parents[2] / "tools/check_lock_groups.py"


@pytest.fixture
def lock(tmp_path: Path) -> Path:
    path = tmp_path / "pylock.toml"
    path.write_text(
        'lock-version = "1.0"\nrequires-python = ">=3.15"\ndependency-groups = ["release-check"]\n'
        'created-by = "test"\npackages = []\n'
    )
    return path


def _check(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(_TOOL), *arguments], text=True, capture_output=True, check=False)


@pytest.mark.parametrize(
    ("arguments", "accepted"),
    [
        pytest.param(("release-check",), True, id="present-group"),
        pytest.param(("--build-constraints",), True, id="lock-without-build-group"),
        pytest.param(("release-news",), False, id="missing-group"),
    ],
)
def test_lock_groups_selects_present_groups(lock: Path, arguments: tuple[str, ...], accepted: bool) -> None:
    result = _check(str(lock), *arguments)

    assert (result.returncode == 0) is accepted, result.stderr
    assert ("missing lock dependency groups: release-news" in result.stderr) is not accepted


def test_lock_groups_requires_a_group(lock: Path) -> None:
    result = _check(str(lock))

    assert result.returncode != 0
    assert "at least one dependency group is required" in result.stderr


@pytest.mark.parametrize("location", ["lock", "request"])
def test_lock_groups_rejects_unnormalized_group(lock: Path, location: str) -> None:
    if location == "lock":
        lock.write_text(lock.read_text().replace('["release-check"]', '["release-check", "project_runtime"]'))

    result = _check(str(lock), "release-check" if location == "lock" else "release_check")

    assert result.returncode != 0
    assert "dependency group names must be normalized" in result.stderr


def test_lock_groups_reports_unreadable_lock(tmp_path: Path) -> None:
    result = _check(str(tmp_path / "missing.toml"), "release-check")

    assert result.returncode != 0
    assert "No such file or directory" in result.stderr


def test_lock_groups_import_has_no_cli_side_effect() -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path({str(_TOOL)!r}, run_name='imported')"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def select_cutoffs(
    action_scripts: Path, tmp_path: Path, *, cutoff: str, entries: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(action_scripts / "refresh-release-lock-2.sh")],
        cwd=tmp_path,
        env=os.environ
        | {
            "CUTOFF": cutoff,
            "EXCLUDE_NEWER_PACKAGES": entries,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_reviewed_security_floor_expires_after_rolling_cutoff(action_scripts: Path, tmp_path: Path) -> None:
    entries = "certifi=2026-10-20T02:25:00Z\nuv=2026-10-20T15:13:00Z"
    result = select_cutoffs(action_scripts, tmp_path, cutoff="2026-10-14T15:05:32Z", entries=entries)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "active-package-cutoffs").read_text() == f"{entries}\n"

    result = select_cutoffs(action_scripts, tmp_path, cutoff="2026-10-27T15:13:00Z", entries=entries)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "active-package-cutoffs").read_text() == ""


def test_unrelated_package_keeps_rolling_cutoff(action_scripts: Path, tmp_path: Path) -> None:
    result = select_cutoffs(
        action_scripts,
        tmp_path,
        cutoff="2026-10-14T15:05:32Z",
        entries="certifi=2026-10-20T02:25:00Z",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "active-package-cutoffs").read_text() == "certifi=2026-10-20T02:25:00Z\n"


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("bad name=2026-10-20T02:25:00Z", id="invalid-package"),
        pytest.param("certifi=October 20", id="invalid-format"),
        pytest.param("certifi=2026-10-40T02:25:00Z", id="invalid-date"),
        pytest.param("certifi=2099-01-01T00:00:00Z", id="future-date"),
    ],
)
def test_invalid_reviewed_floor_fails_closed(action_scripts: Path, tmp_path: Path, entry: str) -> None:
    result = select_cutoffs(action_scripts, tmp_path, cutoff="2026-10-14T15:05:32Z", entries=entry)
    assert result.returncode != 0
    assert not (tmp_path / "output").exists()


def test_empty_lines_are_ignored(action_scripts: Path, tmp_path: Path) -> None:
    result = select_cutoffs(
        action_scripts,
        tmp_path,
        cutoff="2026-10-14T15:05:32Z",
        entries="\ncertifi=2026-10-20T02:25:00Z\n",
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "active-package-cutoffs").read_text() == "certifi=2026-10-20T02:25:00Z\n"

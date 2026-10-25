from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import expose_locked_commands


def test_expose_locked_commands_copies_windows_executable(tmp_path: Path, mocker: MockerFixture) -> None:
    environment = tmp_path / "environment"
    scripts = environment / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "release.exe").write_bytes(b"tool")
    github_path = tmp_path / "github-path"
    platform = mocker.create_autospec(
        os, environ={"RUNNER_TEMP": str(tmp_path), "GITHUB_PATH": str(github_path)}, X_OK=os.X_OK
    )
    platform.access.return_value = True
    platform.name = "nt"  # Mock reserves the name keyword, so the platform name is set afterwards.
    mocker.patch.object(expose_locked_commands, "os", platform)
    mocker.patch.object(sys, "argv", ["expose_locked_commands", str(environment)])

    expose_locked_commands.main()

    installed = Path(github_path.read_text().strip()) / "release.exe"
    assert installed.read_bytes() == b"tool"
    assert not installed.is_symlink()


def test_expose_locked_commands_keeps_system_git_and_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scripts = tmp_path / "environment/bin"
    scripts.mkdir(parents=True)
    for name in ("git", "gh", "prek"):
        command = scripts / name
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o755)
    github_path = tmp_path / "github-path"
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_PATH", str(github_path))
    monkeypatch.setattr(sys, "argv", ["expose_locked_commands", str(scripts.parent)])

    expose_locked_commands.main()

    overlay = Path(github_path.read_text().strip())
    assert sorted(path.name for path in overlay.iterdir()) == ["prek"]

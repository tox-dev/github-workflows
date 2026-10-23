from __future__ import annotations

import os
import sys
from pathlib import Path

from pytest_mock import MockerFixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import expose_locked_commands


def test_expose_locked_commands_copies_windows_executable(tmp_path: Path, mocker: MockerFixture) -> None:
    environment = tmp_path / "environment"
    scripts = environment / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "release.exe").write_bytes(b"tool")
    github_path = tmp_path / "github-path"
    platform = mocker.patch.object(expose_locked_commands, "os")
    platform.name = "nt"
    platform.environ = {"RUNNER_TEMP": str(tmp_path), "GITHUB_PATH": str(github_path)}
    platform.X_OK = os.X_OK
    platform.access.return_value = True
    mocker.patch.object(sys, "argv", ["expose_locked_commands", str(environment)])

    expose_locked_commands.main()

    installed = Path(github_path.read_text().strip()) / "release.exe"
    assert installed.read_bytes() == b"tool"
    assert not installed.is_symlink()

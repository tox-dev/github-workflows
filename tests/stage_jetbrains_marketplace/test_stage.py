from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Final

import pytest
from conftest import action

STUB: Final[str] = """\
#!/usr/bin/env bash
printf '%s\\n' "$@" >"$RUNNER_TEMP/release-creator.args"
while (($#)); do
  if [[ "$1" == --github-output ]]; then echo publish=true >>"$2"; fi
  shift
done
"""


@pytest.fixture
def release_creator(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "release-creator"
    script.write_text(STUB)
    script.chmod(0o755)
    return bin_dir


@pytest.fixture
def signed_archive(tmp_path: Path) -> tuple[Path, str]:
    archive = tmp_path / "Plugin-1.2.3-signed.zip"
    archive.write_bytes(b"signed bytes")
    return archive, hashlib.sha256(b"signed bytes").hexdigest()


@pytest.mark.parametrize(
    ("version", "mode", "channel", "publish", "github_output"),
    [
        pytest.param("v1.2.3", "stage", "", "true", True, id="stable-stage"),
        pytest.param("v1.2.3-beta.1", "stage", "beta", "true", True, id="beta-stage"),
        pytest.param("v1.2.3-beta.1", "verify", "beta", "", False, id="beta-verify"),
    ],
)
def test_compares_archive_and_derives_channel(
    action_scripts: Path,
    repository: Path,
    tmp_path: Path,
    release_creator: Path,
    signed_archive: tuple[Path, str],
    version: str,
    mode: str,
    channel: str,
    publish: str,
    github_output: bool,
) -> None:
    archive, digest = signed_archive
    outputs: dict[str, str] = {}
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "stage-jetbrains-marketplace",
        outputs,
        version=version,
        ARCHIVE=str(archive),
        SHA256=digest,
        PLUGIN_ID="com.example.plugin",
        MODE=mode,
        PATH=f"{release_creator}:{os.environ['PATH']}",
    )
    assert result.returncode == 0, result.stderr
    assert outputs == {"channel": channel, "publish": publish}
    arguments = (tmp_path / "release-creator.args").read_text().splitlines()
    assert arguments[:8] == [
        "marketplace",
        "--plugin-id",
        "com.example.plugin",
        "--version",
        version.removeprefix("v"),
        "--archive",
        str(archive),
        "--mode",
    ]
    assert arguments[8] == mode
    assert ("--github-output" in arguments) is github_output


def test_rejects_archive_that_differs_from_signing_digest(
    action_scripts: Path,
    repository: Path,
    tmp_path: Path,
    release_creator: Path,
    signed_archive: tuple[Path, str],
) -> None:
    archive, _ = signed_archive
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "stage-jetbrains-marketplace",
        version="v1.2.3",
        ARCHIVE=str(archive),
        SHA256="0" * 64,
        PLUGIN_ID="com.example.plugin",
        MODE="stage",
        PATH=f"{release_creator}:{os.environ['PATH']}",
    )
    assert result.returncode != 0
    assert not (tmp_path / "release-creator.args").exists()


def test_rejects_unknown_mode(
    action_scripts: Path,
    repository: Path,
    tmp_path: Path,
    release_creator: Path,
    signed_archive: tuple[Path, str],
) -> None:
    archive, digest = signed_archive
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "stage-jetbrains-marketplace",
        version="v1.2.3",
        ARCHIVE=str(archive),
        SHA256=digest,
        PLUGIN_ID="com.example.plugin",
        MODE="publish",
        PATH=f"{release_creator}:{os.environ['PATH']}",
    )
    assert result.returncode != 0
    assert not (tmp_path / "release-creator.args").exists()

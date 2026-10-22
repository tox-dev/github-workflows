from __future__ import annotations

import os
import subprocess
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pytest_httpserver import HTTPServer


def execute(script: Path, tmp_path: Path, **settings: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path,
        env=os.environ | settings,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture
def signed_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "Fish Shell 2-0.1.11-signed.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as content:
        content.writestr("Fish Shell/lib/plugin.jar", b"signed plugin")
    return archive


def test_signed_archive_passes_byte_and_structure_checks(
    signed_archive: Path, tmp_path: Path, action_scripts: Path
) -> None:
    result = execute(
        action_scripts / "publish-jetbrains-marketplace-0.sh",
        tmp_path,
        ARCHIVE=str(signed_archive),
        EXPECTED_SHA=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("changed", ["digest", "plugin-id", "channel", "extension", "corrupt", "duplicate", "symlink"])
def test_invalid_archive_or_input_fails_before_upload(
    signed_archive: Path, tmp_path: Path, action_scripts: Path, changed: str
) -> None:
    settings = {
        "ARCHIVE": str(signed_archive),
        "EXPECTED_SHA": sha256(signed_archive.read_bytes()).hexdigest(),
        "PLUGIN_ID": "29973",
        "CHANNEL": "beta",
    }
    if changed == "digest":
        settings["EXPECTED_SHA"] = "0" * 64
    elif changed == "plugin-id":
        settings["PLUGIN_ID"] = "fish"
    elif changed == "channel":
        settings["CHANNEL"] = "beta release"
    elif changed == "extension":
        wrong_extension = tmp_path / "plugin.tar"
        wrong_extension.write_bytes(signed_archive.read_bytes())
        settings["ARCHIVE"] = str(wrong_extension)
    elif changed == "corrupt":
        signed_archive.write_bytes(b"not a zip")
        settings["EXPECTED_SHA"] = sha256(signed_archive.read_bytes()).hexdigest()
    elif changed == "duplicate":
        with ZipFile(signed_archive, "a") as content:
            content.writestr("Fish Shell/lib/plugin.jar", b"duplicate")
        settings["EXPECTED_SHA"] = sha256(signed_archive.read_bytes()).hexdigest()
    else:
        link = tmp_path / "linked.zip"
        link.symlink_to(signed_archive)
        settings["ARCHIVE"] = str(link)
    result = execute(action_scripts / "publish-jetbrains-marketplace-0.sh", tmp_path, **settings)
    assert result.returncode != 0


@pytest.mark.parametrize("status", [200, 403])
@pytest.mark.parametrize(
    "archive_name",
    ["Fish Shell 2-0.1.11-signed.zip", "Fish Shell, 2; 0.1.11-signed.zip"],
    ids=["plain-path", "multipart-delimiters"],
)
def test_multipart_upload_uses_exact_archive_and_channel(
    signed_archive: Path, tmp_path: Path, action_scripts: Path, httpserver: HTTPServer, status: int, archive_name: str
) -> None:
    signed_archive = signed_archive.rename(tmp_path / archive_name)
    httpserver.expect_request("/api/updates/upload", method="POST").respond_with_data("{}", status=status)
    script = tmp_path / "upload.sh"
    script.write_text(
        (action_scripts / "publish-jetbrains-marketplace-1.sh")
        .read_text()
        .replace("https://plugins.jetbrains.com/api/updates/upload", httpserver.url_for("/api/updates/upload"))
    )
    result = execute(
        script,
        tmp_path,
        ARCHIVE=str(signed_archive),
        EXPECTED_SHA=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
        RUNNER_TEMP=str(tmp_path),
    )
    assert (result.returncode == 0) is (status == 200)
    request = httpserver.log[0][0]
    assert request.headers["Authorization"] == "Bearer fixture-token"
    assert request.form["pluginId"] == "29973"
    assert request.form["channel"] == "beta"
    assert request.files["file"].filename == "plugin.zip"
    assert request.files["file"].read() == signed_archive.read_bytes()


def test_missing_token_fails_without_request(
    signed_archive: Path, tmp_path: Path, action_scripts: Path, httpserver: HTTPServer
) -> None:
    script = tmp_path / "upload.sh"
    script.write_text(
        (action_scripts / "publish-jetbrains-marketplace-1.sh")
        .read_text()
        .replace("https://plugins.jetbrains.com/api/updates/upload", httpserver.url_for("/api/updates/upload"))
    )
    result = execute(
        script,
        tmp_path,
        ARCHIVE=str(signed_archive),
        EXPECTED_SHA=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="",
        PUBLISH_TOKEN="",
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode != 0
    assert not httpserver.log

from __future__ import annotations

import shutil
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from conftest import action
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param("digest", id="digest"),
        pytest.param("plugin-id", id="plugin-id"),
        pytest.param("channel", id="channel"),
        pytest.param("extension", id="extension"),
        pytest.param("corrupt", id="corrupt"),
        pytest.param("duplicate", id="duplicate"),
        pytest.param("symlink", id="symlink"),
    ],
)
def test_invalid_archive_or_input_fails_before_upload(
    signed_archive: Path, tmp_path: Path, marketplace_scripts: Path, httpserver: HTTPServer, changed: str
) -> None:
    settings = {
        "ARCHIVE": str(signed_archive),
        "SHA256": sha256(signed_archive.read_bytes()).hexdigest(),
        "PLUGIN_ID": "29973",
        "CHANNEL": "beta",
    }
    if changed == "digest":
        settings["SHA256"] = "0" * 64
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
        settings["SHA256"] = sha256(signed_archive.read_bytes()).hexdigest()
    elif changed == "duplicate":
        with ZipFile(signed_archive, "a") as content:
            content.writestr("Fish Shell/lib/plugin.jar", b"duplicate")
        settings["SHA256"] = sha256(signed_archive.read_bytes()).hexdigest()
    else:
        link = tmp_path / "linked.zip"
        link.symlink_to(signed_archive)
        settings["ARCHIVE"] = str(link)
    result = action(
        tmp_path,
        tmp_path,
        marketplace_scripts,
        "publish-jetbrains-marketplace",
        version="",
        PUBLISH_TOKEN="fixture-token",
        **settings,
    )
    assert result.returncode != 0
    assert not httpserver.log


@pytest.mark.parametrize("status", [pytest.param(200, id="accepted"), pytest.param(403, id="denied")])
@pytest.mark.parametrize(
    "archive_name",
    ["Fish Shell 2-0.1.11-signed.zip", "Fish Shell, 2; 0.1.11-signed.zip"],
    ids=["plain-path", "multipart-delimiters"],
)
@pytest.mark.parametrize("temporary_name", ["runner-temp", "runner,; temp"], ids=["plain-temp", "multipart-temp"])
def test_multipart_upload_uses_exact_archive_and_channel(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    httpserver: HTTPServer,
    status: int,
    archive_name: str,
    temporary_name: str,
) -> None:
    signed_archive = signed_archive.rename(tmp_path / archive_name)
    runner_temp = tmp_path / temporary_name
    runner_temp.mkdir()
    httpserver.expect_request("/api/updates/upload", method="POST").respond_with_data(
        "upload denied" if status == 403 else "{}", status=status
    )
    result = action(
        tmp_path,
        runner_temp,
        marketplace_scripts,
        "publish-jetbrains-marketplace",
        version="",
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
        RUNNER_TEMP=str(runner_temp),
    )
    assert (result.returncode == 0) is (status == 200)
    if status == 403:
        assert "upload denied" in result.stderr
    request = httpserver.log[0][0]
    assert request.headers["Authorization"] == "Bearer fixture-token"
    assert request.form["pluginId"] == "29973"
    assert request.form["channel"] == "beta"
    assert request.files["file"].filename == "plugin.zip"
    assert request.files["file"].read() == signed_archive.read_bytes()


def test_missing_token_fails_without_request(
    signed_archive: Path, tmp_path: Path, marketplace_scripts: Path, httpserver: HTTPServer
) -> None:
    result = action(
        tmp_path,
        tmp_path,
        marketplace_scripts,
        "publish-jetbrains-marketplace",
        version="",
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="",
        PUBLISH_TOKEN="",
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode != 0
    assert not httpserver.log


@pytest.fixture
def signed_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "Fish Shell 2-0.1.11-signed.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as content:
        content.writestr("Fish Shell/lib/plugin.jar", b"signed plugin")
    return archive


@pytest.fixture
def marketplace_scripts(action_scripts: Path, tmp_path: Path, httpserver: HTTPServer) -> Path:
    scripts = tmp_path / "scripts"
    shutil.copytree(action_scripts, scripts)
    upload = scripts / "publish-jetbrains-marketplace-1.sh"
    upload.write_text(
        upload.read_text().replace(
            "https://plugins.jetbrains.com/api/updates/upload", httpserver.url_for("/api/updates/upload")
        )
    )
    return scripts

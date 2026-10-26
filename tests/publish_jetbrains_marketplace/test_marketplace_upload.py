from __future__ import annotations

import json
import shutil
import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import yaml
from conftest import action
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param("digest", id="digest"),
        pytest.param("duplicate", id="duplicate"),
    ],
)
def test_invalid_archive_or_input_fails_before_upload(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    changed: str,
) -> None:
    settings = {
        "ARCHIVE": str(signed_archive),
        "SHA256": sha256(signed_archive.read_bytes()).hexdigest(),
        "PLUGIN_ID": "29973",
        "CHANNEL": "beta",
    }
    if changed == "digest":
        settings["SHA256"] = "0" * 64
    else:
        with ZipFile(signed_archive, "a") as content:
            content.writestr("Fish Shell/lib/plugin.jar", b"duplicate")
        settings["SHA256"] = sha256(signed_archive.read_bytes()).hexdigest()
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        PUBLISH_TOKEN="fixture-token",
        ARCHIVE=settings["ARCHIVE"],
        SHA256=settings["SHA256"],
        PLUGIN_ID=settings["PLUGIN_ID"],
        CHANNEL=settings["CHANNEL"],
    )
    assert result.returncode != 0
    assert not httpserver.log


@pytest.mark.parametrize(
    "status", [pytest.param(200, id="accepted"), pytest.param(302, id="redirected"), pytest.param(403, id="denied")]
)
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
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    status: int,
    archive_name: str,
    temporary_name: str,
) -> None:
    signed_archive = signed_archive.rename(tmp_path / archive_name)
    runner_temp = tmp_path / temporary_name
    runner_temp.mkdir()
    response = {200: "{}", 302: "redirect", 403: "upload denied"}[status]
    httpserver.expect_request("/api/updates/upload", method="POST").respond_with_data(response, status=status)
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        runner_temp=runner_temp,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
        RUNNER_TEMP=str(runner_temp),
    )
    assert (result.returncode == 0) is (status == 200)
    if status != 200:
        assert response in result.stderr
    else:
        assert json.loads((runner_temp / "marketplace-acceptance.json").read_text()) == {
            "schema": 2,
            "repository": "tox-dev/fixture",
            "tag": "v0.1.11",
            "commit": "0" * 40,
            "sourceRunId": 42,
            "pluginId": 29973,
            "version": "0.1.11",
            "channel": "beta",
            "signedArchive": archive_name,
            "sha256": sha256(signed_archive.read_bytes()).hexdigest(),
            "signedArtifactId": 51,
            "notesArtifactId": 52,
            "notesSha256": sha256(b"Release notes\n").hexdigest(),
        }
    request = httpserver.log[0][0]
    assert request.headers["Authorization"] == "Bearer fixture-token"
    assert request.form["pluginId"] == "29973"
    assert request.form["channel"] == "beta"
    assert request.files["file"].filename == "plugin.zip"
    assert request.files["file"].read() == signed_archive.read_bytes()


@pytest.mark.parametrize(
    "previous_step",
    [
        pytest.param("🚀 Publish signed ZIP", id="current"),
        pytest.param("Publish signed ZIP", id="before-emoji"),
        pytest.param("Upload signed ZIP", id="upload"),
        pytest.param("📤 Publish to JetBrains Marketplace", id="legacy"),
    ],
)
def test_prior_upload_without_receipt_blocks_retry(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    previous_step: str,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        previous_step=previous_step,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "Reconcile run 41 attempt 1 manually" in result.stderr
    assert not httpserver.log


def test_prior_upload_from_renamed_workflow_blocks_retry(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        previous_workflow="old-release.yaml",
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "Reconcile run 41 attempt 1 manually" in result.stderr
    assert not httpserver.log


@pytest.mark.parametrize("previous_workflow", ["release.yaml", "old-release.yaml"])
def test_prior_acceptance_with_matching_artifacts_skips_upload(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    previous_workflow: str,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        previous_workflow=previous_workflow,
        accepted_archive=signed_archive,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode == 0, result.stderr
    assert not httpserver.log


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("tag", "v0.1.12", id="tag"),
        pytest.param("commit", "1" * 40, id="commit"),
        pytest.param("pluginId", 20536, id="plugin"),
        pytest.param("channel", "alpha", id="channel"),
        pytest.param("sha256", "0" * 64, id="signed-digest"),
        pytest.param("signedArtifactId", 70, id="signed-artifact"),
        pytest.param("notesArtifactId", 71, id="notes-artifact"),
        pytest.param("notesSha256", "0" * 64, id="notes-digest"),
    ],
)
def test_changed_prior_receipt_blocks_retry(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    field: str,
    value: str | int,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        accepted_archive=signed_archive,
        receipt_changes={field: value},
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert not httpserver.log


@pytest.mark.parametrize("changed", [pytest.param("signed", id="signed-zip"), pytest.param("notes", id="notes")])
def test_changed_prior_artifact_blocks_retry(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    changed: str,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        accepted_archive=signed_archive,
        prior_signed=b"changed" if changed == "signed" else None,
        prior_notes=b"changed" if changed == "notes" else None,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert not httpserver.log


def test_reconciled_attempt_allows_another_retry(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        reconciled_attempt=True,
        accepted_archive=signed_archive,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode == 0, result.stderr
    assert not httpserver.log
    assert any(request.path.endswith("/artifacts/62/zip") for request, _ in github_api[0].log)


def test_receipt_from_unlisted_run_blocks_retry(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_run=True,
        accepted_archive=signed_archive,
        receipt_changes={"sourceRunId": 30},
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert not httpserver.log


def test_fork_run_on_tag_named_branch_allows_upload(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/api/updates/upload", method="POST").respond_with_data("{}")
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        fork_run=True,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode == 0, result.stderr
    assert len(httpserver.log) == 1
    assert not any("/runs/39/" in request.path for request, _ in github_api[0].log)


def publish_action(
    repository: Path,
    scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    *,
    runner_temp: Path | None = None,
    previous_run: bool = False,
    previous_step: str = "🚀 Publish signed ZIP",
    previous_workflow: str = "release.yaml",
    accepted_archive: Path | None = None,
    missing_receipt: bool = False,
    receipt_changes: dict[str, str | int] | None = None,
    prior_signed: bytes | None = None,
    prior_notes: bytes | None = None,
    fork_run: bool = False,
    reconciled_attempt: bool = False,
    **settings: str,
) -> subprocess.CompletedProcess[str]:
    server, environment = github_api
    runs = [
        {
            "id": 40,
            "head_branch": "main",
            "head_sha": "2" * 40,
            "head_repository": {"full_name": "tox-dev/fixture"},
            "path": ".github/workflows/check.yaml",
        }
    ]
    if previous_run:
        runs.append(
            {
                "id": 41,
                "head_branch": "v0.1.11",
                "head_sha": "0" * 40,
                "head_repository": {"full_name": "tox-dev/fixture"},
                "path": f".github/workflows/{previous_workflow}",
            }
        )
    if fork_run:
        runs.append(
            {
                "id": 39,
                "head_branch": "v0.1.11",
                "head_sha": "3" * 40,
                "head_repository": {"full_name": "mallory/fixture"},
                "path": ".github/workflows/release.yaml",
            }
        )
    server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs").respond_with_json({"workflow_runs": runs})
    if previous_run:
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/41/jobs").respond_with_json(
            {
                "jobs": [
                    {
                        "run_attempt": attempt,
                        "steps": [{"name": previous_step, "started_at": "2026-10-23T00:00:00Z"}],
                    }
                    for attempt in ((1, 2) if reconciled_attempt else (1,))
                ]
            }
        )
        artifacts = (
            [
                {
                    "id": artifact_id,
                    "name": artifact_name,
                    "expired": False,
                    "archive_download_url": (
                        f"https://localhost:{server.port}/api/v3/repos/tox-dev/fixture/actions/"
                        f"artifacts/{artifact_id}/zip"
                    ),
                }
                for artifact_id, artifact_name in (
                    (61, "marketplace-acceptance-41-1"),
                    *([(62, "marketplace-acceptance-41-2")] if reconciled_attempt else []),
                    (51, "plugin-distribution"),
                    (52, "release-notes"),
                )
            ]
            if accepted_archive
            else []
        )
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/41/artifacts").respond_with_json(
            {"artifacts": artifacts}
        )
        if accepted_archive:
            receipt = {
                "schema": 2,
                "repository": "tox-dev/fixture",
                "tag": "v0.1.11",
                "commit": "0" * 40,
                "sourceRunId": 41,
                "pluginId": 29973,
                "version": "0.1.11",
                "channel": "beta",
                "signedArchive": accepted_archive.name,
                "sha256": sha256(accepted_archive.read_bytes()).hexdigest(),
                "signedArtifactId": 51,
                "notesArtifactId": 52,
                "notesSha256": sha256(b"Release notes\n").hexdigest(),
            }
            receipt.update(receipt_changes or {})
            for artifact_id, filename, payload in (
                (61, "other.json" if missing_receipt else "marketplace-acceptance.json", json.dumps(receipt).encode()),
                (62, "marketplace-acceptance.json", json.dumps(receipt).encode()),
                (
                    51,
                    accepted_archive.name,
                    prior_signed if prior_signed is not None else accepted_archive.read_bytes(),
                ),
                (52, "release-notes.md", prior_notes if prior_notes is not None else b"Release notes\n"),
            ):
                archive = BytesIO()
                with ZipFile(archive, "w", ZIP_DEFLATED) as content:
                    content.writestr(filename, payload)
                server.expect_request(
                    f"/api/v3/repos/tox-dev/fixture/actions/artifacts/{artifact_id}/zip"
                ).respond_with_data(archive.getvalue(), content_type="application/zip")
    notes_file = repository / "release-notes.md"
    notes_file.write_text("Release notes\n")
    return action(
        repository,
        runner_temp or repository,
        scripts,
        "publish-jetbrains-marketplace",
        version="",
        TAG="v0.1.11",
        COMMIT="0" * 40,
        SIGNED_ARTIFACT_ID="51",
        NOTES_ARTIFACT_ID="52",
        NOTES_FILE=str(notes_file),
        GITHUB_REF="refs/tags/v0.1.11",
        GITHUB_SERVER_URL="https://github.com",
        GITHUB_WORKFLOW_REF="tox-dev/fixture/.github/workflows/release.yaml@refs/tags/v0.1.11",
        GITHUB_RUN_ID="42",
        GITHUB_RUN_ATTEMPT="1",
        **environment,
        **settings,
    )


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
    steps = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "publish-jetbrains-marketplace/action.yml").read_text()
    )["runs"]["steps"]
    upload_index = next(index for index, step in enumerate(steps) if step.get("name") == "🚀 Upload signed ZIP")
    upload = scripts / f"publish-jetbrains-marketplace-{upload_index}.sh"
    upload.write_text(
        upload.read_text().replace(
            "https://plugins.jetbrains.com/api/updates/upload", httpserver.url_for("/api/updates/upload")
        )
    )
    return scripts

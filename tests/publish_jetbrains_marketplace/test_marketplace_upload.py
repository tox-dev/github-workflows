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
        pytest.param("plugin-id", id="plugin-id"),
        pytest.param("channel", id="channel"),
        pytest.param("extension", id="extension"),
        pytest.param("corrupt", id="corrupt"),
        pytest.param("duplicate", id="duplicate"),
        pytest.param("symlink", id="symlink"),
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


def test_missing_token_fails_without_request(
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
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="",
        PUBLISH_TOKEN="",
        RUNNER_TEMP=str(tmp_path),
    )
    assert result.returncode != 0
    assert not httpserver.log


def test_prior_upload_without_receipt_blocks_retry(
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
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "Reconcile run 41 attempt 1 manually" in result.stderr
    assert not httpserver.log


@pytest.mark.parametrize(
    "previous_step",
    [
        pytest.param("Publish signed ZIP", id="current"),
        pytest.param("📤 Publish to JetBrains Marketplace", id="legacy"),
    ],
)
def test_prior_upload_on_another_commit_blocks_retry(
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
        previous_commit="1" * 40,
        previous_step=previous_step,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "earlier Marketplace upload on commit" in result.stderr
    assert any(
        request.path == "/api/v3/repos/tox-dev/fixture/actions/runs"
        and request.query_string == b"branch=v0.1.11&per_page=100"
        for request, _ in github_api[0].log
    )
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


def test_deleted_prior_run_deployment_blocks_upload(
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
        previous_deployment=True,
        previous_deployment_job_missing=True,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "Cannot inspect release deployment" in result.stderr
    assert not httpserver.log


@pytest.mark.parametrize(
    ("log_url", "job_run"),
    [
        pytest.param("https://example.org/tox-dev/fixture/actions/runs/41/job/170", None, id="foreign-host"),
        pytest.param("https://github.com/tox-dev/fixture/actions/runs/41/attempts/1", None, id="not-a-job"),
        pytest.param(None, 40, id="job-from-another-run"),
    ],
)
def test_unidentified_prior_deployment_blocks_upload(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    log_url: str | None,
    job_run: int | None,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_deployment=True,
        previous_deployment_log_url=log_url,
        previous_deployment_job_run=job_run,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "Cannot identify release deployment 70" in result.stderr
    assert not httpserver.log


def test_prior_contributor_deployment_blocks_upload(
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
        previous_deployment=True,
        previous_deployment_upload=False,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "prior release deployment 70 from run 41 attempt 1" in result.stderr
    assert not httpserver.log


@pytest.mark.parametrize(
    ("state", "started"),
    [
        pytest.param("success", "2026-10-23T00:00:00Z", id="completed"),
        pytest.param("failure", None, id="partial"),
    ],
)
def test_renamed_prior_upload_deployment_blocks_upload(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    state: str,
    started: str | None,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        previous_deployment=True,
        previous_deployment_step="Publish to Marketplace",
        previous_deployment_started=started,
        previous_deployment_state=state,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "prior release deployment 70 from run 41 attempt 1" in result.stderr
    assert not httpserver.log


def test_new_tag_on_old_commit_can_upload(
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
        run_history=False,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode == 0, result.stderr
    assert len(httpserver.log) == 1


def test_previous_attempt_deployment_blocks_upload(
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
        previous_deployment=True,
        previous_deployment_run=42,
        previous_deployment_attempt=1,
        current_attempt=2,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "prior release deployment" in result.stderr
    assert not httpserver.log


def test_moved_tag_deployment_blocks_upload(
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
        previous_deployment=True,
        previous_deployment_sha="1" * 40,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "release deployment on another commit" in result.stderr
    assert not httpserver.log


def test_missing_current_publisher_deployment_blocks_upload(
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
        current_deployment_upload=False,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert "needs a release environment deployment" in result.stderr
    assert not httpserver.log


def test_current_run_other_deployments_allow_upload(
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
        extra_current_deployment=True,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode == 0, result.stderr
    assert len(httpserver.log) == 1
    assert any(
        request.path == "/api/v3/repos/tox-dev/fixture/deployments"
        and request.query_string == b"ref=v0.1.11&environment=release&per_page=100"
        for request, _ in github_api[0].log
    )


@pytest.mark.parametrize("annotated", [pytest.param(False, id="lightweight"), pytest.param(True, id="annotated")])
def test_remote_moved_tag_blocks_upload(
    signed_archive: Path,
    tmp_path: Path,
    marketplace_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    httpserver: HTTPServer,
    annotated: bool,
) -> None:
    result = publish_action(
        tmp_path,
        marketplace_scripts,
        github_api,
        remote_commit="1" * 40,
        annotated=annotated,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
    assert not httpserver.log


def test_annotated_tag_targets_release_commit(
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
        annotated=True,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode == 0, result.stderr
    assert len(httpserver.log) == 1


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


def test_prior_acceptance_missing_receipt_file_blocks_retry(
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
        missing_receipt=True,
        ARCHIVE=str(signed_archive),
        SHA256=sha256(signed_archive.read_bytes()).hexdigest(),
        PLUGIN_ID="29973",
        CHANNEL="beta",
        PUBLISH_TOKEN="fixture-token",
    )
    assert result.returncode != 0
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
    previous_commit: str = "0" * 40,
    previous_step: str = "Publish signed ZIP",
    previous_workflow: str = "release.yaml",
    previous_deployment: bool = False,
    previous_deployment_run: int = 41,
    previous_deployment_attempt: int = 1,
    previous_deployment_upload: bool = True,
    previous_deployment_step: str = "Publish signed ZIP",
    previous_deployment_started: str | None = "2026-10-23T00:00:00Z",
    previous_deployment_state: str = "success",
    previous_deployment_sha: str = "0" * 40,
    previous_deployment_job_missing: bool = False,
    previous_deployment_log_url: str | None = None,
    previous_deployment_job_run: int | None = None,
    extra_current_deployment: bool = False,
    current_deployment_upload: bool = True,
    current_attempt: int = 1,
    run_history: bool = True,
    accepted_archive: Path | None = None,
    missing_receipt: bool = False,
    receipt_changes: dict[str, str | int] | None = None,
    prior_signed: bytes | None = None,
    prior_notes: bytes | None = None,
    remote_commit: str = "0" * 40,
    annotated: bool = False,
    fork_run: bool = False,
    reconciled_attempt: bool = False,
    **settings: str,
) -> subprocess.CompletedProcess[str]:
    server, environment = github_api
    server.expect_request("/api/v3/repos/tox-dev/fixture/git/ref/tags/v0.1.11").respond_with_json(
        {"object": {"type": "tag" if annotated else "commit", "sha": "f" * 40 if annotated else remote_commit}}
    )
    if annotated:
        server.expect_request(f"/api/v3/repos/tox-dev/fixture/git/tags/{'f' * 40}").respond_with_json(
            {"object": {"type": "commit", "sha": remote_commit}}
        )
    runs = (
        [
            {
                "id": 40,
                "head_branch": "main",
                "head_sha": "2" * 40,
                "head_repository": {"full_name": "tox-dev/fixture"},
                "path": ".github/workflows/check.yaml",
            }
        ]
        if run_history
        else []
    )
    if previous_run:
        runs.append(
            {
                "id": 41,
                "head_branch": "v0.1.11",
                "head_sha": previous_commit,
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
    deployments = [{"id": 71, "sha": "0" * 40}]
    if extra_current_deployment:
        deployments.append({"id": 72, "sha": "0" * 40})
    if previous_deployment:
        deployments.append({"id": 70, "sha": previous_deployment_sha})
    server.expect_request("/api/v3/repos/tox-dev/fixture/deployments").respond_with_json(deployments)
    for deployment in deployments:
        deployment_id = int(deployment["id"])
        prior = deployment_id == 70
        run_id = previous_deployment_run if prior else 42
        attempt = previous_deployment_attempt if prior else current_attempt
        job_id = deployment_id + 100
        server.expect_request(f"/api/v3/repos/tox-dev/fixture/deployments/{deployment_id}/statuses").respond_with_json(
            [
                {
                    "log_url": previous_deployment_log_url
                    if prior and previous_deployment_log_url is not None
                    else f"https://github.com/tox-dev/fixture/actions/runs/{run_id}/job/{job_id}",
                    "state": previous_deployment_state if prior else "in_progress",
                }
            ]
        )
        job_request = server.expect_request(f"/api/v3/repos/tox-dev/fixture/actions/jobs/{job_id}")
        if prior and previous_deployment_job_missing:
            job_request.respond_with_data("deleted", status=404)
        else:
            job_request.respond_with_json(
                {
                    "run_id": previous_deployment_job_run
                    if prior and previous_deployment_job_run is not None
                    else run_id,
                    "run_attempt": attempt,
                    "steps": [
                        {
                            "name": (
                                previous_deployment_step
                                if prior and previous_deployment_upload
                                else "Publish signed ZIP"
                                if current_deployment_upload and not prior
                                else "Generate contributors"
                            ),
                            "started_at": previous_deployment_started if prior else "2026-10-23T00:00:00Z",
                        }
                    ],
                }
            )
    if previous_run:
        server.expect_request("/api/v3/repos/tox-dev/fixture/actions/runs/41/jobs").respond_with_json(
            {
                "jobs": [
                    {"run_attempt": attempt, "steps": [{"name": previous_step, "started_at": "2026-10-23T00:00:00Z"}]}
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
        GITHUB_RUN_ATTEMPT=str(current_attempt),
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
    upload_index = next(index for index, step in enumerate(steps) if step.get("name") == "Upload signed ZIP")
    upload = scripts / f"publish-jetbrains-marketplace-{upload_index}.sh"
    upload.write_text(
        upload.read_text().replace(
            "https://plugins.jetbrains.com/api/updates/upload", httpserver.url_for("/api/updates/upload")
        )
    )
    return scripts

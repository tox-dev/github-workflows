from __future__ import annotations

import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest
from conftest import action, run
from pytest_httpserver import HTTPServer


@pytest.fixture
def release_cli(tmp_path: Path) -> dict[str, str]:
    real_gh = shutil.which("gh")
    assert real_gh is not None
    executable = tmp_path / "bin" / "gh"
    executable.parent.mkdir()
    executable.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == release ]]; then\n"
        '  printf "%s\\0" "$@" >>"$GH_RELEASE_LOG"\n'
        '  printf "\\n" >>"$GH_RELEASE_LOG"\n'
        "  if [[ $2 == upload && ${GH_UPLOAD_FAILURE:-false} == true ]]; then exit 1; fi\n"
        "  if [[ $2 == upload && ${GH_UPLOAD_FAILURE:-false} == once && ! -f $GH_FAILURE_MARKER ]]; then\n"
        '    touch "$GH_FAILURE_MARKER"; exit 1\n'
        "  fi\n"
        "  if [[ $2 == verify-asset && ${GH_VERIFY_FAILURE:-false} == true ]]; then exit 1; fi\n"
        "  exit 0\n"
        "fi\n"
        'exec "$GH_REAL" "$@"\n',
    )
    executable.chmod(0o755)
    (executable.parent / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    (executable.parent / "sleep").chmod(0o755)
    return {
        "PATH": f"{executable.parent}:{os.environ['PATH']}",
        "GH_REAL": real_gh,
        "GH_RELEASE_LOG": str(tmp_path / "release-cli-arguments"),
        "GH_FAILURE_MARKER": str(tmp_path / "release-cli-failed-once"),
    }


def _release_calls(tmp_path: Path) -> list[tuple[str, ...]]:
    path = tmp_path / "release-cli-arguments"
    return (
        [tuple(part.decode() for part in line.split(b"\0")[:-1]) for line in path.read_bytes().splitlines()]
        if path.exists()
        else []
    )


def _notes_and_commit(repository: Path, tmp_path: Path) -> tuple[Path, str]:
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    return notes, run(repository, "git", "rev-parse", "0.1.0").stdout.strip()


def _release(
    notes: Path, *, draft: bool, assets: list[dict[str, str]] | None = None, immutable: bool = False
) -> dict[str, str | int | bool | list[dict[str, str]]]:
    return {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": draft,
        "prerelease": False,
        "immutable": immutable,
        "assets": assets or [],
    }


def _request(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    notes: Path,
    commit: str,
    environment: dict[str, str],
    *,
    assets: Path | None = None,
    mode: str = "complete",
) -> subprocess.CompletedProcess[str]:
    return action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets) if assets is not None else "",
        PRERELEASE="false",
        MODE=mode,
        **environment,
    )


@pytest.mark.parametrize("with_asset", [pytest.param(False, id="notes-only"), pytest.param(True, id="with-asset")])
def test_existing_published_release_is_verified_without_writes(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
    with_asset: bool,
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    if with_asset:
        assets.mkdir()
        (assets / "fixture.zip").write_bytes(b"release archive")
    release = _release(
        notes,
        draft=False,
        immutable=True,
        assets=(
            [{"name": "fixture.zip", "digest": f"sha256:{sha256(b'release archive').hexdigest()}", "state": "uploaded"}]
            if with_asset
            else []
        ),
    )
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release]
    )
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli,
        assets=assets if with_asset else None,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"]
    assert _release_calls(tmp_path) == (
        [("release", "verify-asset", "0.1.0", str(assets / "fixture.zip"), "--repo", "tox-dev/fixture")]
        if with_asset
        else []
    )


def test_immutable_release_with_changed_assets_fails(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fixture.zip").write_bytes(b"release archive")
    release = _release(
        notes,
        draft=False,
        immutable=True,
        assets=[{"name": "fixture.zip", "digest": "sha256:" + "0" * 64, "state": "uploaded"}],
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/releases", query_string="per_page=100", method="GET"
    ).respond_with_json([release])
    result = _request(repository, tmp_path, action_scripts, notes, commit, environment | release_cli, assets=assets)
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"]
    assert not _release_calls(tmp_path)


@pytest.mark.parametrize(
    ("changed_field", "value"),
    [
        pytest.param("name", "Wrong title", id="title"),
        pytest.param("body", "Wrong notes.\n", id="notes"),
        pytest.param("prerelease", True, id="prerelease"),
    ],
)
def test_rerun_updates_changed_draft(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
    changed_field: str,
    value: str | bool,
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    draft = _release(notes, draft=True)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft | {changed_field: value}]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    result = _request(repository, tmp_path, action_scripts, notes, commit, environment | release_cli, mode="stage")
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "PATCH", "GET"]
    assert server.log[1][0].get_json() == {"name": "0.1.0", "body": notes.read_text(), "prerelease": False}


def test_mutable_published_release_is_rechecked(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    release = _release(notes, draft=False)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
    result = _request(repository, tmp_path, action_scripts, notes, commit, environment | release_cli)
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "GET"]
    assert not _release_calls(tmp_path)


def test_staged_release_publishes_without_reupload(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    draft = _release(
        notes,
        draft=True,
        assets=[
            {
                "name": asset_path.name,
                "digest": f"sha256:{sha256(asset_path.read_bytes()).hexdigest()}",
                "state": "uploaded",
            }
        ],
    )
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(draft | {"draft": False})
    result = _request(
        repository, tmp_path, action_scripts, notes, commit, environment | release_cli, assets=assets, mode="publish"
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "GET", "PATCH"]
    assert _release_calls(tmp_path) == [
        ("release", "verify-asset", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture")
    ]


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param("stage", id="draft"),
        pytest.param("complete", id="published"),
        pytest.param("publish", id="published-without-draft"),
    ],
)
def test_missing_release_is_created_then_optionally_published(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
    mode: str,
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    draft = _release(notes, draft=True)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json([])
    server.expect_ordered_request(f"{prefix}/releases", method="POST").respond_with_json(draft, status=201)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    if mode != "stage":
        server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
            draft | {"draft": False}
        )
    result = _request(repository, tmp_path, action_scripts, notes, commit, environment | release_cli, mode=mode)
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == [
        "GET",
        "POST",
        "GET",
        *(["PATCH"] if mode != "stage" else []),
    ]
    assert not _release_calls(tmp_path)
    request = next(request for request, _ in server.log if request.method == "POST")
    assert request.get_json() == {
        "tag_name": "0.1.0",
        "target_commitish": commit,
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": False,
    }


@pytest.mark.parametrize("mode", [pytest.param("stage", id="draft"), pytest.param("complete", id="published")])
@pytest.mark.parametrize(
    "asset_name",
    [
        pytest.param("fixture.zip", id="plain"),
        pytest.param("fixture+linux.zip", id="plus"),
        pytest.param("Fixture signed.zip", id="space"),
    ],
)
def test_draft_release_uploads_missing_asset(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
    mode: str,
    asset_name: str,
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / asset_name
    asset_path.write_bytes(b"release archive")
    asset = {"name": asset_name, "digest": f"sha256:{sha256(b'release archive').hexdigest()}", "state": "uploaded"}
    draft = _release(notes, draft=True)
    complete = _release(notes, draft=True, assets=[asset])
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(complete)
    if mode == "complete":
        server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
            complete | {"draft": False}
        )
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli,
        assets=assets,
        mode=mode,
    )
    assert result.returncode == 0, result.stderr
    assert _release_calls(tmp_path) == [
        ("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture"),
        *(
            [("release", "verify-asset", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture")]
            if mode == "complete"
            else []
        ),
    ]
    assert [request.method for request, _ in server.log] == [
        "GET",
        "GET",
        "GET",
        *(["PATCH"] if mode == "complete" else []),
    ]


def test_draft_release_replaces_incomplete_asset(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    incomplete = _release(
        notes,
        draft=True,
        assets=[{"id": "21", "name": asset_path.name, "digest": "", "state": "starter"}],
    )
    uploaded = _release(
        notes,
        draft=True,
        assets=[
            {
                "name": asset_path.name,
                "digest": f"sha256:{sha256(asset_path.read_bytes()).hexdigest()}",
                "state": "uploaded",
            }
        ],
    )
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [incomplete]
    )
    server.expect_ordered_request(f"{prefix}/releases/assets/21", method="DELETE").respond_with_json({})
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(incomplete | {"assets": []})
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(uploaded)
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli,
        assets=assets,
        mode="stage",
    )
    assert result.returncode == 0, result.stderr
    assert ("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture") in _release_calls(tmp_path)
    assert [request.method for request, _ in server.log] == ["GET", "DELETE", "GET", "GET"]


def test_changed_draft_is_updated_before_upload(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    draft = _release(notes, draft=True)
    complete = _release(
        notes,
        draft=True,
        assets=[
            {"name": "fixture.zip", "digest": f"sha256:{sha256(b'release archive').hexdigest()}", "state": "uploaded"}
        ],
    )
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft | {"body": "Human-edited notes.\n"}]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(complete)
    result = _request(
        repository, tmp_path, action_scripts, notes, commit, environment | release_cli, assets=assets, mode="stage"
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "PATCH", "GET", "GET"]
    assert _release_calls(tmp_path) == [("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture")]


def test_failed_upload_deletes_partial_asset_before_retry(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    draft = _release(notes, draft=True)
    partial = _release(
        notes, draft=True, assets=[{"id": "21", "name": asset_path.name, "digest": "", "state": "starter"}]
    )
    complete = _release(
        notes,
        draft=True,
        assets=[
            {
                "name": asset_path.name,
                "digest": f"sha256:{sha256(asset_path.read_bytes()).hexdigest()}",
                "state": "uploaded",
            }
        ],
    )
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    for release in (draft, partial, partial):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
    server.expect_ordered_request(f"{prefix}/releases/assets/21", method="DELETE").respond_with_json({})
    for _ in range(2):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(complete)

    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli | {"GH_UPLOAD_FAILURE": "once"},
        assets=assets,
        mode="stage",
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * 4 + ["DELETE", "GET"]
    assert _release_calls(tmp_path) == [
        ("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture"),
        ("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture"),
    ]


def test_failed_asset_lookup_stops_retry(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    draft = _release(notes, draft=True)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    for _ in range(2):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_data(status=500)
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli | {"GH_UPLOAD_FAILURE": "once"},
        assets=assets,
        mode="stage",
    )
    assert result.returncode != 0
    assert _release_calls(tmp_path) == [("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture")]


def test_failed_asset_upload_leaves_draft_unpublished(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fixture.zip").write_bytes(b"release archive")
    draft = _release(notes, draft=True)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    for _ in range(14):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli | {"GH_UPLOAD_FAILURE": "true"},
        assets=assets,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"] * 13
    assert (
        _release_calls(tmp_path)
        == [("release", "upload", "0.1.0", str(assets / "fixture.zip"), "--repo", "tox-dev/fixture")] * 6
    )


def test_upload_failure_recovers_when_asset_is_present(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    asset = {
        "name": asset_path.name,
        "digest": f"sha256:{sha256(asset_path.read_bytes()).hexdigest()}",
        "state": "uploaded",
    }
    draft = _release(notes, draft=True)
    complete = _release(notes, draft=True, assets=[asset])
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(complete)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(complete)
    server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
        complete | {"draft": False}
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(complete | {"draft": False})
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli | {"GH_UPLOAD_FAILURE": "once"},
        assets=assets,
    )
    assert result.returncode == 0, result.stderr
    assert _release_calls(tmp_path) == [
        ("release", "upload", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture"),
        ("release", "verify-asset", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture"),
    ]


def test_failed_asset_attestation_is_reported(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    asset_path = assets / "fixture.zip"
    asset_path.write_bytes(b"release archive")
    release = _release(
        notes,
        draft=False,
        immutable=True,
        assets=[
            {
                "name": asset_path.name,
                "digest": f"sha256:{sha256(asset_path.read_bytes()).hexdigest()}",
                "state": "uploaded",
            }
        ],
    )
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release]
    )
    result = _request(
        repository,
        tmp_path,
        action_scripts,
        notes,
        commit,
        environment | release_cli | {"GH_VERIFY_FAILURE": "true"},
        assets=assets,
    )
    assert result.returncode != 0
    assert "release asset attestation could not be verified" in result.stderr
    assert [request.method for request, _ in server.log] == ["GET"]
    assert (
        _release_calls(tmp_path)
        == [("release", "verify-asset", "0.1.0", str(asset_path), "--repo", "tox-dev/fixture")] * 6
    )


def test_duplicate_releases_use_the_first(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    release_cli: dict[str, str],
) -> None:
    server, environment = github_api
    notes, commit = _notes_and_commit(repository, tmp_path)
    first = _release(notes, draft=True)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [first, first | {"id": 43}]
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(first)
    server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(first | {"draft": False})
    result = _request(repository, tmp_path, action_scripts, notes, commit, environment | release_cli)
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "GET", "PATCH"]

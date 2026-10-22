from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from conftest import action, run
from pytest_httpserver import HTTPServer


@pytest.mark.parametrize(
    ("with_asset", "empty_directory"),
    [(False, False), (False, True), (True, False)],
    ids=["notes-only", "empty-directory", "with-asset"],
)
def test_published_release_is_verified_without_writes(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    with_asset: bool,
    empty_directory: bool,
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    assets = tmp_path / "assets"
    if with_asset or empty_directory:
        assets.mkdir()
    if with_asset:
        (assets / "fixture.zip").write_bytes(b"release archive")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    release = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": False,
        "prerelease": False,
        "assets": (
            [{"name": "fixture.zip", "digest": f"sha256:{sha256(b'release archive').hexdigest()}", "state": "uploaded"}]
            if with_asset
            else []
        ),
        "target_commitish": "main",
    }
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release],
    )
    for _ in range(2 + int(with_asset or empty_directory)):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets) if with_asset or empty_directory else "",
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log] == [
        f"{prefix}/git/ref/tags/0.1.0",
        f"{prefix}/releases",
        *[f"{prefix}/releases/42"] * (2 + int(with_asset or empty_directory)),
    ]


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        pytest.param("name", "Other title", id="title"),
        pytest.param("body", "Different notes.\n", id="body"),
        pytest.param("prerelease", True, id="prerelease"),
        pytest.param("assets", [{"name": "extra.zip", "digest": "sha256:deadbeef", "state": "uploaded"}], id="asset"),
    ],
)
@pytest.mark.parametrize("is_draft", [False, True], ids=["published", "draft"])
def test_existing_release_rejects_changed_content(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    changed_field: str,
    changed_value: str | bool | list[dict[str, str]],
    is_draft: bool,
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    release = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": is_draft,
        "prerelease": False,
        "assets": [],
    }
    release[changed_field] = changed_value
    server.expect_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release],
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET", "GET"]


def test_tag_must_point_to_expected_commit(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    server.expect_request("/api/v3/repos/tox-dev/fixture/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": "0" * 40}},
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT="1" * 40,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"]


def test_annotated_tag_points_to_expected_commit(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "tag", "sha": "2" * 40}},
    )
    server.expect_ordered_request(f"{prefix}/git/tags/{'2' * 40}", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}},
    )
    release = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": False,
        "prerelease": False,
        "assets": [],
    }
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release],
    )
    for _ in range(2):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.path for request, _ in server.log] == [
        f"{prefix}/git/ref/tags/0.1.0",
        f"{prefix}/git/tags/{'2' * 40}",
        f"{prefix}/releases",
        *[f"{prefix}/releases/42"] * 2,
    ]


def test_missing_tag_rejects_same_name_branch(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    run(repository, "git", "branch", "0.1.0", commit)
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"message": "Not Found"},
        status=404,
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode != 0
    assert [request.path for request, _ in server.log] == [f"{prefix}/git/ref/tags/0.1.0"]


def test_asset_name_must_be_safe(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "unsafe\nname.zip").write_bytes(b"release archive")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    server.expect_request("/api/v3/repos/tox-dev/fixture/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}},
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets),
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode != 0
    assert "unsafe release asset name" in result.stdout
    assert [request.method for request, _ in server.log] == ["GET"]


def test_publish_requires_an_existing_draft(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json([])
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        MODE="publish",
        **environment,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET", "GET"]


def test_publish_rejects_incomplete_draft_without_upload(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fixture.zip").write_bytes(b"release archive")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    draft = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": False,
        "assets": [],
    }
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft],
    )
    for _ in range(6):
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets),
        PRERELEASE="false",
        MODE="publish",
        **environment,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"] * 8


def test_invalid_mode_rejects_before_api_access(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT="0" * 40,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        MODE="unknown",
        **environment,
    )
    assert result.returncode != 0
    assert "invalid release mode" in result.stdout
    assert server.log == []


@pytest.mark.parametrize("mode", ["stage", "publish", "complete"])
def test_matching_draft_is_published_without_recreation(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    mode: str,
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    draft = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": False,
        "assets": [],
    }
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft],
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    if mode != "stage":
        server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
            draft | {"draft": False}
        )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(
        draft | {"draft": mode == "stage"},
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE="false",
        MODE=mode,
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == [
        "GET",
        "GET",
        "GET",
        *([] if mode == "stage" else ["PATCH"]),
        "GET",
    ]


@pytest.mark.parametrize(
    ("is_prerelease", "mode"),
    [
        pytest.param(False, "stage", id="stable-stage"),
        pytest.param(True, "stage", id="prerelease-stage"),
        pytest.param(False, "complete", id="stable-complete"),
        pytest.param(True, "complete", id="prerelease-complete"),
    ],
)
def test_missing_release_is_created_and_published(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    is_prerelease: bool,
    mode: str,
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    release = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": is_prerelease,
        "assets": [],
    }
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json([])
    server.expect_ordered_request(f"{prefix}/releases", method="POST").respond_with_json(release, status=201)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
    if mode == "complete":
        server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
            release | {"draft": False},
        )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(
        release | {"draft": mode == "stage"},
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        GITHUB_REPOSITORY="other/checkout",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY="",
        PRERELEASE=str(is_prerelease).lower(),
        MODE=mode,
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == [
        "GET",
        "GET",
        "POST",
        "GET",
        *([] if mode == "stage" else ["PATCH"]),
        "GET",
    ]
    request = next(
        request for request, _ in server.log if request.path == f"{prefix}/releases" and request.method == "POST"
    )
    assert request.get_json() == {
        "tag_name": "0.1.0",
        "target_commitish": commit,
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": is_prerelease,
    }


@pytest.mark.parametrize("mode", ["stage", "complete"])
@pytest.mark.parametrize("asset_name", ["fixture.zip", "fixture+linux.zip", "Fixture signed.zip"])
def test_draft_release_resumes_missing_asset(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    mode: str,
    asset_name: str,
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / asset_name).write_bytes(b"release archive")
    digest = f"sha256:{sha256(b'release archive').hexdigest()}"
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    asset = {"name": asset_name, "digest": digest, "state": "uploaded"}
    release = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": False,
        "assets": [],
        "upload_url": f"https://localhost:{server.port}{prefix}/releases/42/assets{{?name,label}}",
    }
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [release],
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
    server.expect_ordered_request(
        f"{prefix}/releases/42/assets",
        query_string=f"name={asset_name.replace('+', '%2B').replace(' ', '%20')}",
        method="POST",
        data=b"release archive",
    ).respond_with_json(asset, status=201)
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(
        release | {"assets": [asset]},
    )
    if mode == "complete":
        server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
            release | {"draft": False},
        )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(
        release | {"draft": mode == "stage", "assets": [asset]},
    )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets),
        PRERELEASE="false",
        MODE=mode,
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == [
        "GET",
        "GET",
        "GET",
        "POST",
        "GET",
        *([] if mode == "stage" else ["PATCH"]),
        "GET",
    ]


def test_failed_asset_upload_leaves_draft_unpublished(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fixture.zip").write_bytes(b"release archive")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    draft = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": False,
        "assets": [],
        "upload_url": f"https://localhost:{server.port}{prefix}/releases/42/assets{{?name,label}}",
    }
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft],
    )
    server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(draft)
    server.expect_ordered_request(
        f"{prefix}/releases/42/assets",
        query_string="name=fixture.zip",
        method="POST",
        data=b"release archive",
    ).respond_with_json({"message": "upstream failure"}, status=502)
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets),
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET", "GET", "GET", "POST"]


@pytest.mark.parametrize(
    "failed_read",
    [
        pytest.param("upload", id="before-upload"),
        pytest.param("complete", id="after-upload"),
        pytest.param("published", id="after-publish"),
    ],
)
def test_release_read_recovers_without_duplicate_writes(
    repository: Path,
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    failed_read: str,
) -> None:
    server, environment = github_api
    notes = tmp_path / "notes.md"
    notes.write_text("Release notes.\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "fixture.zip").write_bytes(b"release archive")
    commit = run(repository, "git", "rev-parse", "0.1.0").stdout.strip()
    prefix = "/api/v3/repos/tox-dev/fixture"
    asset = {"name": "fixture.zip", "digest": f"sha256:{sha256(b'release archive').hexdigest()}", "state": "uploaded"}
    draft = {
        "id": 42,
        "tag_name": "0.1.0",
        "name": "0.1.0",
        "body": notes.read_text(),
        "draft": True,
        "prerelease": False,
        "assets": [],
        "upload_url": f"https://localhost:{server.port}{prefix}/releases/42/assets{{?name,label}}",
    }
    server.expect_ordered_request(f"{prefix}/git/ref/tags/0.1.0", method="GET").respond_with_json(
        {"object": {"type": "commit", "sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/releases", query_string="per_page=100", method="GET").respond_with_json(
        [draft]
    )
    for stage, release in (
        ("upload", draft),
        ("complete", draft | {"assets": [asset]}),
        ("published", draft | {"draft": False, "assets": [asset]}),
    ):
        if stage == failed_read:
            server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(
                {"message": "upstream failure"}, status=502
            )
        server.expect_ordered_request(f"{prefix}/releases/42", method="GET").respond_with_json(release)
        if stage == "upload":
            server.expect_ordered_request(
                f"{prefix}/releases/42/assets", query_string="name=fixture.zip", method="POST", data=b"release archive"
            ).respond_with_json(asset, status=201)
        elif stage == "complete":
            server.expect_ordered_request(f"{prefix}/releases/42", method="PATCH").respond_with_json(
                draft | {"draft": False, "assets": [asset]}
            )
    result = action(
        repository,
        tmp_path,
        action_scripts,
        "publish-github-release",
        version="0.1.0",
        REPOSITORY="tox-dev/fixture",
        TAG="0.1.0",
        COMMIT=commit,
        TITLE="0.1.0",
        NOTES_FILE=str(notes),
        ASSETS_DIRECTORY=str(assets),
        PRERELEASE="false",
        **environment,
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == [
        "GET",
        "GET",
        "GET",
        *(["GET"] if failed_read == "upload" else []),
        "POST",
        "GET",
        *(["GET"] if failed_read == "complete" else []),
        "PATCH",
        "GET",
        *(["GET"] if failed_read == "published" else []),
    ]

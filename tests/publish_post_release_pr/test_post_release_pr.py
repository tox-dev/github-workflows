from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_httpserver import HTTPServer


def test_action_maps_writer_app_slug() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "publish-post-release-pr/action.yml").read_text())
    assert action["inputs"]["app-slug"]["required"]
    assert action["inputs"]["allowed-paths"]["required"]
    assert action["runs"]["steps"][0]["env"]["APP_SLUG"] == "${{ inputs.app-slug }}"
    assert action["runs"]["steps"][0]["env"]["ALLOWED_PATHS"] == "${{ inputs.allowed-paths }}"


def expect_bot(server: HTTPServer) -> None:
    server.expect_request("/api/v3/users/fixture-app[bot]", method="GET").respond_with_json({"id": 123})


def publish(
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    *,
    main_blob: str,
    expected_blob: str,
    additional_blob: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], HTTPServer]:
    server, environment = github_api
    expect_bot(server)
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    paths = tmp_path / "paths.tsv"
    paths.write_text(f"gradle.properties\t{expected_blob}\n")
    if additional_blob is not None:
        with paths.open("a") as stream:
            stream.write(f"other.txt\t{additional_blob}\n")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "state": "closed",
                "merged_at": "2026-10-20T00:00:00Z",
                "title": "Bump version to 2.4.8-dev",
                "body": body.read_text(),
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "tox-dev/fixture"}, "ref": "post-release-v2.4.7"},
            }
        ]
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/git/ref/heads/main", method="GET").respond_with_json(
        {"object": {"sha": "a" * 40}}
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/contents/gradle.properties", query_string="ref=main", method="GET"
    ).respond_with_json({"type": "file", "sha": main_blob})
    if additional_blob is not None and main_blob == expected_blob:
        server.expect_request(
            "/api/v3/repos/tox-dev/fixture/contents/other.txt", query_string="ref=main", method="GET"
        ).respond_with_json({"type": "file", "sha": additional_blob})
    if main_blob == expected_blob:
        server.expect_request("/api/v3/repos/tox-dev/fixture/pulls/7/files", method="GET").respond_with_json(
            [{"filename": "gradle.properties"}, *([{"filename": "other.txt"}] if additional_blob is not None else [])]
        )
        server.expect_request("/api/v3/repos/tox-dev/fixture/issues/7/labels", method="GET").respond_with_json(
            [{"name": "skip news"}]
        )
    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[2] / "publish-post-release-pr/publish.sh")],
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "APP_SLUG": "fixture-app",
            "BASE": "main",
            "BASE_COMMIT": "a" * 40,
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties\nother.txt\n" if additional_blob is not None else "gradle.properties",
            "BUNDLE": "",
            "CANDIDATE_COMMIT": "",
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    return result, server


def test_merged_branch_deleted_and_main_matches_is_complete(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, github_api, main_blob="b" * 40, expected_blob="b" * 40)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "pull-request=7\n"
    assert [request.method for request, _ in server.log] == ["GET"] * 6


def test_multiline_allowed_paths_accepts_trailing_newline(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, github_api, main_blob="b" * 40, expected_blob="b" * 40, additional_blob="c" * 40)
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * 7


def test_merged_branch_deleted_and_later_main_change_fails(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, github_api, main_blob="c" * 40, expected_blob="b" * 40)
    assert result.returncode != 0
    assert not (tmp_path / "output").exists()
    assert [request.method for request, _ in server.log] == ["GET"] * 4


def run_git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def candidate(tmp_path: Path, *, extra_path: bool = False, wrong_author: bool = False) -> tuple[Path, str, str, str]:
    repository = tmp_path / "source"
    repository.mkdir()
    run_git(repository, "init", "-q", "-b", "main")
    run_git(repository, "config", "user.name", "fixture-app[bot]")
    run_git(repository, "config", "user.email", "123+fixture-app[bot]@users.noreply.github.com")
    (repository / "gradle.properties").write_text("pluginVersion=2.4.7\n")
    run_git(repository, "add", "gradle.properties")
    run_git(repository, "commit", "-qm", "Base")
    base = run_git(repository, "rev-parse", "HEAD")
    run_git(repository, "checkout", "-qb", "release-candidate")
    (repository / "gradle.properties").write_text("pluginVersion=2.4.8-dev\n")
    run_git(repository, "add", "gradle.properties")
    if extra_path:
        (repository / "other.txt").write_text("unexpected\n")
        run_git(repository, "add", "other.txt")
    if wrong_author:
        run_git(repository, "config", "user.name", "Different author")
    run_git(repository, "commit", "-qm", "Bump version")
    commit = run_git(repository, "rev-parse", "HEAD")
    blob = run_git(repository, "rev-parse", "HEAD:gradle.properties")
    bundle = tmp_path / "candidate.bundle"
    run_git(repository, "bundle", "create", str(bundle), "refs/heads/release-candidate")
    return bundle, base, commit, blob


@pytest.mark.parametrize(
    ("branch_tree", "branch_author", "base_moved", "expected_success"),
    [
        ("candidate", "fixture-app[bot]", False, True),
        ("other", "fixture-app[bot]", False, False),
        ("candidate", "Other", False, False),
        ("candidate", "fixture-app[bot]", True, False),
    ],
    ids=["exact-branch", "divergent-branch", "divergent-author", "moved-base"],
)
def test_open_branch_must_match_prepared_candidate(
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    branch_tree: str,
    branch_author: str,
    base_moved: bool,
    expected_success: bool,
) -> None:
    server, environment = github_api
    expect_bot(server)
    bundle, base, commit, blob = candidate(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    paths = tmp_path / "paths.tsv"
    paths.write_text(f"gradle.properties\t{blob}\n")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "state": "open",
                "merged_at": None,
                "title": "Bump version to 2.4.8-dev",
                "body": body.read_text(),
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "tox-dev/fixture"}, "ref": "post-release-v2.4.7", "sha": commit},
            }
        ]
    )
    server.expect_request("/api/v3/repos/tox-dev/fixture/git/ref/heads/main", method="GET").respond_with_json(
        {"object": {"sha": "c" * 40 if base_moved else base}}
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/git/ref/heads/post-release-v2.4.7", method="GET"
    ).respond_with_json({"object": {"sha": commit}})
    server.expect_request(f"/api/v3/repos/tox-dev/fixture/git/commits/{commit}", method="GET").respond_with_json(
        {
            "parents": [{"sha": base}],
            "author": {"name": branch_author, "email": "123+fixture-app[bot]@users.noreply.github.com"},
            "tree": {
                "sha": "b" * 40 if branch_tree == "other" else run_git(tmp_path / "source", "rev-parse", "HEAD^{tree}")
            },
        }
    )
    if expected_success:
        server.expect_request("/api/v3/repos/tox-dev/fixture/issues/7/labels", method="GET").respond_with_json(
            [{"name": "skip news"}]
        )
    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[2] / "publish-post-release-pr/publish.sh")],
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "APP_SLUG": "fixture-app",
            "BASE": "main",
            "BASE_COMMIT": base,
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) is expected_success, result.stderr
    assert (tmp_path / "output").exists() is expected_success
    assert all(request.method == "GET" for request, _ in server.log)


def test_absent_branch_pushes_prepared_commit_and_opens_pr(
    tmp_path: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    server.expect_ordered_request("/api/v3/users/fixture-app[bot]", method="GET").respond_with_json({"id": 123})
    bundle, base, commit, blob = candidate(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    paths = tmp_path / "paths.tsv"
    paths.write_text(f"gradle.properties\t{blob}\n")
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/pulls", method="GET").respond_with_json([])
    server.expect_ordered_request(f"{prefix}/git/ref/heads/main", method="GET").respond_with_json(
        {"object": {"sha": base}}
    )
    server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
        {"message": "Not Found"}, status=404
    )
    server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
        {"object": {"sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/pulls", method="POST").respond_with_json({"number": 7}, status=201)
    server.expect_ordered_request(f"{prefix}/issues/7/labels", method="GET").respond_with_json([])
    server.expect_ordered_request(f"{prefix}/issues/7/labels", method="POST").respond_with_json(
        [{"name": "skip news"}], status=200
    )
    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[2] / "publish-post-release-pr/publish.sh")],
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "APP_SLUG": "fixture-app",
            "BASE": "main",
            "BASE_COMMIT": base,
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GIT_REMOTE_URL": str(remote),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert run_git(remote, "rev-parse", "refs/heads/post-release-v2.4.7") == commit
    assert (tmp_path / "output").read_text() == "pull-request=7\n"


@pytest.mark.parametrize(
    "changed_input",
    ["commit", "blob", "extra", "author", "unauthorized"],
    ids=["stale-bundle", "changed-path-manifest", "extra-path", "wrong-author", "unauthorized-path"],
)
def test_prepared_candidate_identity_is_checked_before_api_write(
    tmp_path: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    changed_input: str,
) -> None:
    server, environment = github_api
    expect_bot(server)
    bundle, base, commit, blob = candidate(
        tmp_path, extra_path=changed_input in {"extra", "unauthorized"}, wrong_author=changed_input == "author"
    )
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    paths = tmp_path / "paths.tsv"
    paths.write_text(f"gradle.properties\t{'c' * 40 if changed_input == 'blob' else blob}\n")
    if changed_input == "unauthorized":
        with paths.open("a") as stream:
            stream.write(f"other.txt\t{run_git(tmp_path / 'source', 'rev-parse', 'HEAD:other.txt')}\n")
    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[2] / "publish-post-release-pr/publish.sh")],
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "APP_SLUG": "fixture-app",
            "BASE": "main",
            "BASE_COMMIT": base,
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle),
            "CANDIDATE_COMMIT": "d" * 40 if changed_input == "commit" else commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"]
    assert not (tmp_path / "output").exists()

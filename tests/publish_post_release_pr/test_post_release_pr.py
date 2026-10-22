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
    assert action["runs"]["steps"][1]["env"]["ALLOWED_PATHS"] == "${{ inputs.allowed-paths }}"
    assert action["runs"]["steps"][-1]["id"] == "publish"


def run_publish(action_scripts: Path, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    steps = yaml.safe_load((Path(__file__).resolve().parents[2] / "publish-post-release-pr/action.yml").read_text())[
        "runs"
    ]["steps"]
    action_variables = {name for step in steps for name in step["env"]}
    base_env = {name: value for name, value in env.items() if name not in action_variables}
    result = None
    for index, step in enumerate(steps):
        result = subprocess.run(
            ["bash", str(action_scripts / f"publish-post-release-pr-{index}.sh")],
            cwd=cwd,
            env=base_env | {name: env[name] for name in step["env"]},
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            return result
    assert result is not None
    return result


def expect_bot(server: HTTPServer) -> None:
    server.expect_request("/api/v3/users/fixture-app[bot]", method="GET").respond_with_json({"id": 123})


def publish(
    tmp_path: Path,
    action_scripts: Path,
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
    result = run_publish(
        action_scripts,
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
            "COMMIT_MESSAGE": "Bump version",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties\nother.txt\n" if additional_blob is not None else "gradle.properties",
            "BUNDLE": "",
            "CANDIDATE_COMMIT": "",
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
    )
    return result, server


def test_merged_branch_deleted_and_main_matches_is_complete(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, action_scripts, github_api, main_blob="b" * 40, expected_blob="b" * 40)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "pull-request=7\n"
    assert [request.method for request, _ in server.log] == ["GET"] * 6


def test_multiline_allowed_paths_accepts_trailing_newline(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(
        tmp_path, action_scripts, github_api, main_blob="b" * 40, expected_blob="b" * 40, additional_blob="c" * 40
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * 7


def test_merged_branch_deleted_and_later_main_change_fails(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, action_scripts, github_api, main_blob="c" * 40, expected_blob="b" * 40)
    assert result.returncode != 0
    assert not (tmp_path / "output").exists()
    assert [request.method for request, _ in server.log] == ["GET"] * 4


def test_open_pull_request_metadata_change_fails(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    server.expect_request("/api/v3/repos/tox-dev/fixture/pulls", method="GET").respond_with_json(
        [
            {
                "number": 7,
                "state": "open",
                "merged_at": None,
                "title": "Different title",
                "body": body.read_text(),
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "tox-dev/fixture"}, "ref": "post-release-v2.4.7"},
            }
        ]
    )
    result = subprocess.run(
        ["bash", str(action_scripts / "publish-post-release-pr-3.sh")],
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "REPOSITORY": "tox-dev/fixture",
            "BASE": "main",
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "COMMIT_MESSAGE": "Bump version",
            "BODY_FILE": str(body),
            "RUNNER_TEMP": str(tmp_path),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "open pull request metadata changed" in result.stderr


def test_closed_unmerged_pr_blocks_retry_before_write(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
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
                "state": "closed",
                "merged_at": None,
                "title": "Bump version to 2.4.8-dev",
                "body": body.read_text(),
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "tox-dev/fixture"}, "ref": "post-release-v2.4.7"},
            }
        ]
    )
    result = run_publish(
        action_scripts,
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
            "COMMIT_MESSAGE": "Bump version",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle.relative_to(tmp_path)),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
    )
    assert result.returncode != 0
    assert "post-release pull request was closed without merging; reopen it to retry" in result.stderr
    assert [request.method for request, _ in server.log] == ["GET", "GET"]
    assert not (tmp_path / "output").exists()


def run_git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def candidate(
    tmp_path: Path,
    *,
    extra_path: bool = False,
    wrong_author: bool = False,
    wrong_committer: bool = False,
    wrong_message: bool = False,
) -> tuple[Path, str, str, str]:
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
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-qm", "Different message" if wrong_message else "Bump version"],
        env=os.environ | ({"GIT_COMMITTER_NAME": "Different committer"} if wrong_committer else {}),
        check=True,
    )
    commit = run_git(repository, "rev-parse", "HEAD")
    blob = run_git(repository, "rev-parse", "HEAD:gradle.properties")
    bundle = tmp_path / "candidate.bundle"
    run_git(repository, "bundle", "create", str(bundle), "refs/heads/release-candidate")
    return bundle, base, commit, blob


@pytest.mark.parametrize(
    "branch_tamper",
    ["none", "tree", "author", "committer", "message", "base", "parent"],
    ids=[
        "exact-branch",
        "divergent-tree",
        "divergent-author",
        "divergent-committer",
        "divergent-message",
        "moved-base",
        "merge-commit",
    ],
)
def test_open_branch_must_match_prepared_candidate(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    branch_tamper: str,
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
        {"object": {"sha": "c" * 40 if branch_tamper == "base" else base}}
    )
    server.expect_request(
        "/api/v3/repos/tox-dev/fixture/git/ref/heads/post-release-v2.4.7", method="GET"
    ).respond_with_json({"object": {"sha": commit}})
    server.expect_request(f"/api/v3/repos/tox-dev/fixture/git/commits/{commit}", method="GET").respond_with_json(
        {
            "parents": [{"sha": base}] + ([{"sha": "d" * 40}] if branch_tamper == "parent" else []),
            "author": {
                "name": "Other" if branch_tamper == "author" else "fixture-app[bot]",
                "email": "123+fixture-app[bot]@users.noreply.github.com",
            },
            "committer": {
                "name": "Other" if branch_tamper == "committer" else "fixture-app[bot]",
                "email": "123+fixture-app[bot]@users.noreply.github.com",
            },
            "message": "Other" if branch_tamper == "message" else "Bump version",
            "tree": {
                "sha": "b" * 40 if branch_tamper == "tree" else run_git(tmp_path / "source", "rev-parse", "HEAD^{tree}")
            },
        }
    )
    if branch_tamper == "none":
        server.expect_request("/api/v3/repos/tox-dev/fixture/issues/7/labels", method="GET").respond_with_json(
            [{"name": "skip news"}]
        )
    result = run_publish(
        action_scripts,
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
            "COMMIT_MESSAGE": "Bump version",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle.relative_to(tmp_path)),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
    )
    assert (result.returncode == 0) is (branch_tamper == "none"), result.stderr
    assert (tmp_path / "output").exists() is (branch_tamper == "none")
    assert all(request.method == "GET" for request, _ in server.log)


@pytest.mark.parametrize("matching_head", [True, False], ids=["prepared-head", "changed-head"])
def test_absent_branch_pushes_prepared_commit_and_opens_pr(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]], matching_head: bool
) -> None:
    server, environment = github_api
    server.expect_ordered_request("/api/v3/users/fixture-app[bot]", method="GET").respond_with_json({"id": 123})
    bundle, base, commit, blob = candidate(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    git_config = tmp_path / "gitconfig"
    subprocess.run(
        [
            "git",
            "config",
            "--file",
            str(git_config),
            f"url.{remote}.insteadOf",
            f"https://{environment['GH_HOST']}/tox-dev/fixture.git",
        ],
        check=True,
    )
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
    server.expect_ordered_request(f"{prefix}/git/ref/heads/main", method="GET").respond_with_json(
        {"object": {"sha": base}}
    )
    server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
        {"object": {"sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
        {"object": {"sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/pulls", method="POST").respond_with_json(
        {"number": 7, "head": {"sha": commit if matching_head else "b" * 40}}, status=201
    )
    if matching_head:
        server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
            {"object": {"sha": commit}}
        )
        server.expect_ordered_request(f"{prefix}/issues/7/labels", method="GET").respond_with_json([])
        server.expect_ordered_request(f"{prefix}/issues/7/labels", method="POST").respond_with_json(
            [{"name": "skip news"}], status=200
        )
    result = run_publish(
        action_scripts,
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
            "COMMIT_MESSAGE": "Bump version",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GIT_CONFIG_GLOBAL": str(git_config),
        },
    )
    assert (result.returncode == 0) is matching_head, result.stderr
    assert run_git(remote, "rev-parse", "refs/heads/post-release-v2.4.7") == commit
    assert (tmp_path / "output").exists() is matching_head


@pytest.mark.parametrize(
    "changed_input",
    ["commit", "blob", "extra", "author", "committer", "message", "unauthorized"],
    ids=[
        "stale-bundle",
        "changed-path-manifest",
        "extra-path",
        "wrong-author",
        "wrong-committer",
        "wrong-message",
        "unauthorized-path",
    ],
)
def test_prepared_candidate_identity_is_checked_before_api_write(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    changed_input: str,
) -> None:
    server, environment = github_api
    expect_bot(server)
    bundle, base, commit, blob = candidate(
        tmp_path,
        extra_path=changed_input in {"extra", "unauthorized"},
        wrong_author=changed_input == "author",
        wrong_committer=changed_input == "committer",
        wrong_message=changed_input == "message",
    )
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    paths = tmp_path / "paths.tsv"
    paths.write_text(f"gradle.properties\t{'c' * 40 if changed_input == 'blob' else blob}\n")
    if changed_input == "unauthorized":
        with paths.open("a") as stream:
            stream.write(f"other.txt\t{run_git(tmp_path / 'source', 'rev-parse', 'HEAD:other.txt')}\n")
    result = run_publish(
        action_scripts,
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
            "COMMIT_MESSAGE": "Bump version",
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "output"),
        },
    )
    assert result.returncode != 0
    assert [request.method for request, _ in server.log] == ["GET"]
    assert not (tmp_path / "output").exists()

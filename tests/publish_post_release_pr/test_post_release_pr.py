from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import action
from pytest_httpserver import HTTPServer


def test_action_maps_writer_allowed_paths() -> None:
    action = yaml.safe_load((Path(__file__).resolve().parents[2] / "publish-post-release-pr/action.yml").read_text())
    assert action["inputs"]["allowed-paths"]["required"]
    assert action["runs"]["steps"][0]["env"]["ALLOWED_PATHS"] == "${{ inputs.allowed-paths }}"
    assert "outputs" not in action
    assert {"repository", "base", "label"}.isdisjoint(action["inputs"])


def run_publish(action_scripts: Path, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    settings = {
        name: value
        for name, value in env.items()
        if name not in {"BASE", "LABEL"} and (name not in os.environ or os.environ[name] != value)
    }
    return action(
        cwd,
        Path(env["RUNNER_TEMP"]),
        action_scripts,
        "publish-post-release-pr",
        version="",
        **settings,
    )


def publish(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    *,
    expected_blob: str,
    additional_blob: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], HTTPServer]:
    server, environment = github_api
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
    server.expect_request("/api/v3/repos/tox-dev/fixture/issues/7/labels", method="GET").respond_with_json(
        [{"name": "skip news"}]
    )
    result = run_publish(
        action_scripts,
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "GITHUB_REPOSITORY": "tox-dev/fixture",
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
        },
    )
    return result, server


def test_merged_branch_deleted_and_main_matches_is_complete(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, action_scripts, github_api, expected_blob="b" * 40)
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * 2


def test_multiline_allowed_paths_accepts_trailing_newline(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    result, server = publish(tmp_path, action_scripts, github_api, expected_blob="b" * 40, additional_blob="c" * 40)
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * 2


def test_closed_unmerged_pr_blocks_retry_before_write(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
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
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "BASE": "main",
            "BASE_COMMIT": base,
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle.relative_to(tmp_path)),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
        },
    )
    assert result.returncode != 0
    assert "post-release pull request was closed without merging; reopen it to retry" in result.stderr
    assert [request.method for request, _ in server.log] == ["GET"]


def run_git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def candidate(tmp_path: Path, *, extra_path: bool = False) -> tuple[Path, str, str, str]:
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
    run_git(repository, "commit", "-qm", "Bump version")
    commit = run_git(repository, "rev-parse", "HEAD")
    blob = run_git(repository, "rev-parse", "HEAD:gradle.properties")
    bundle = tmp_path / "candidate.bundle"
    run_git(repository, "bundle", "create", str(bundle), "refs/heads/release-candidate")
    return bundle, base, commit, blob


def test_open_pull_request_branch_is_reused(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
    bundle, base, commit, blob = candidate(tmp_path)
    body = tmp_path / "body.md"
    body.write_text("Set the next development version.\n")
    paths = tmp_path / "paths.tsv"
    paths.write_text(f"gradle.properties\t{blob}\n")
    prefix = "/api/v3/repos/tox-dev/fixture"
    server.expect_ordered_request(f"{prefix}/pulls", method="GET").respond_with_json(
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
    server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
        {"object": {"sha": commit}}
    )
    server.expect_ordered_request(f"{prefix}/issues/7/labels", method="GET").respond_with_json([{"name": "skip news"}])
    result = run_publish(
        action_scripts,
        cwd=tmp_path,
        env=os.environ
        | environment
        | {
            "GITHUB_REPOSITORY": "tox-dev/fixture",
            "BASE": "main",
            "BASE_COMMIT": base,
            "BRANCH": "post-release-v2.4.7",
            "TITLE": "Bump version to 2.4.8-dev",
            "BODY_FILE": str(body),
            "PATHS_FILE": str(paths),
            "ALLOWED_PATHS": "gradle.properties",
            "BUNDLE": str(bundle.relative_to(tmp_path)),
            "CANDIDATE_COMMIT": commit,
            "LABEL": "skip news",
            "RUNNER_TEMP": str(tmp_path),
        },
    )
    assert result.returncode == 0, result.stderr
    assert [request.method for request, _ in server.log] == ["GET"] * 3


def test_absent_branch_pushes_prepared_commit_and_opens_pr(
    tmp_path: Path, action_scripts: Path, github_api: tuple[HTTPServer, dict[str, str]]
) -> None:
    server, environment = github_api
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
    server.expect_ordered_request(f"{prefix}/git/ref/heads/post-release-v2.4.7", method="GET").respond_with_json(
        {"message": "Not Found"}, status=404
    )
    server.expect_ordered_request(f"{prefix}/pulls", method="POST").respond_with_json(
        {"number": 7, "head": {"sha": commit}}, status=201
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
            "GITHUB_REPOSITORY": "tox-dev/fixture",
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
            "GIT_CONFIG_GLOBAL": str(git_config),
        },
    )
    assert result.returncode == 0, result.stderr
    assert run_git(remote, "rev-parse", "refs/heads/post-release-v2.4.7") == commit


@pytest.mark.parametrize(
    "changed_input",
    [
        pytest.param("commit", id="stale-bundle"),
        pytest.param("blob", id="changed-path-manifest"),
        pytest.param("extra", id="extra-path"),
        pytest.param("unauthorized", id="unauthorized-path"),
    ],
)
def test_prepared_candidate_identity_is_checked_before_api_write(
    tmp_path: Path,
    action_scripts: Path,
    github_api: tuple[HTTPServer, dict[str, str]],
    changed_input: str,
) -> None:
    server, environment = github_api
    bundle, base, commit, blob = candidate(tmp_path, extra_path=changed_input in {"extra", "unauthorized"})
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
            "GITHUB_REPOSITORY": "tox-dev/fixture",
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
        },
    )
    assert result.returncode != 0
    assert not server.log

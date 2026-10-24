"""Require GitHub-observed age for hook revisions added since the last release."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from yaml import YAMLError, safe_load


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("tag")
    parser.add_argument("--config", default=".pre-commit-config.yaml")
    try:
        args = parser.parse_args()
        check_tagged_hooks(args.repository, args.tag, args.config)
    except (OSError, RuntimeError, TypeError, ValueError, YAMLError, json.JSONDecodeError) as error:
        parser.error(str(error))


def check_tagged_hooks(repository: str, tag: str, config: str) -> None:
    if not repository or not tag or Path(config).is_absolute() or ".." in Path(config).parts:
        raise ValueError("tagged hook proof needs a repository, tag, and relative config path")
    if _git("rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("tagged hook proof needs complete git history and tags")
    head = _git("rev-parse", "HEAD")
    previous = _previous_release(repository, head, tag)
    current = _pairs(Path(config).read_text(encoding="utf-8"))
    pending = current - (_pairs_at(previous, config) if previous else set())
    if not pending:
        return
    revision_range = f"{previous}..HEAD" if previous else "HEAD"
    introductions: dict[tuple[str, str], str] = {}
    for commit in _git("rev-list", "--first-parent", "--reverse", revision_range, "--", config).splitlines():
        parent = _git("rev-list", "--parents", "-n", "1", commit).split()[1:2]
        introduced = (_pairs_at(commit, config) - (_pairs_at(parent[0], config) if parent else set())) & pending
        introductions.update(dict.fromkeys(introduced, commit))
    for commit in set(introductions.values()):
        pending -= _proven_pairs(
            repository, config, commit, {pair for pair, change in introductions.items() if change == commit}
        )
    if not pending:
        return
    raise ValueError(
        f"hook revisions lack a seven-day GitHub observation: {', '.join(sorted(f'{repo}@{rev}' for repo, rev in pending))}"
    )


def _previous_release(repository: str, head: str, tag: str) -> str | None:
    published = {
        release["tag_name"]
        for release in _api(f"repos/{repository}/releases?per_page=100")
        if not release.get("draft") and release.get("published_at") and isinstance(release.get("tag_name"), str)
    }
    lineage = set(_git("rev-list", "--first-parent", head).splitlines())
    tags = _git("tag", "--list")
    while previous := _previous_tag(tag, tags):
        commit = _git_optional("rev-parse", "--verify", f"refs/tags/{previous}^{{commit}}")
        if previous in published and commit in lineage and commit != head:
            return previous
        tag = previous
    return None


def _previous_tag(tag: str, tags: str) -> str:
    command = [sys.executable, "-m", "release_creator", "tags", tag, "--previous"]
    if "/" in tag:
        command.extend(("--package", tag.split("/", 1)[0]))
    result = subprocess.run(command, input=tags, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"cannot select prior release tag: {result.stderr.strip()}")
    return result.stdout.strip()


def _pairs_at(revision: str, config: str) -> set[tuple[str, str]]:
    content = _git_optional("show", f"{revision}:{config}")
    return _pairs(content) if content is not None else set()


def _pairs(content: str) -> set[tuple[str, str]]:
    root = safe_load(content)
    if not isinstance(root, dict) or not isinstance(root.get("repos"), list):
        raise TypeError("hook configuration needs a repository list")
    pairs: set[tuple[str, str]] = set()
    for item in root["repos"]:
        if not isinstance(item, dict) or not isinstance(item.get("repo"), str):
            raise TypeError("hook repository needs a URL")
        if item["repo"] not in {"local", "meta"}:
            if not isinstance(item.get("rev"), str):
                raise TypeError("external hook repository needs a revision")
            pairs.add((item["repo"], item["rev"]))
    return pairs


def _proven_pairs(repository: str, config: str, commit: str, introduced: set[tuple[str, str]]) -> set[tuple[str, str]]:
    proven: set[tuple[str, str]] = set()
    for pull in _api(f"repos/{repository}/commits/{commit}/pulls?per_page=100"):
        if (
            pull.get("merge_commit_sha") != commit
            or not pull.get("merged_at")
            or pull.get("base", {}).get("repo", {}).get("full_name") != repository
        ):
            continue
        number = pull["number"]
        if config not in {item["filename"] for item in _api(f"repos/{repository}/pulls/{number}/files?per_page=100")}:
            continue
        merged_at = datetime.fromisoformat(pull["merged_at"])
        if merged_at <= datetime.now(UTC) - timedelta(days=7):
            proven |= introduced
            continue
        head = pull["head"]
        if not isinstance(head.get("repo"), dict) or not isinstance(head["repo"].get("full_name"), str):
            continue
        head_repository = head["repo"]["full_name"]
        encoded = _api_object(f"repos/{head_repository}/contents/{config}?ref={head['sha']}")["content"]
        for pair in _pairs(base64.b64decode(encoded).decode("utf-8")) & introduced:
            if _observed_pair(repository, config, pair, pull):
                proven.add(pair)
    return proven


def _observed_pair(repository: str, config: str, pair: tuple[str, str], pull: dict[str, Any]) -> bool:
    head = pull["head"]
    source = head["repo"]["full_name"]
    opened = datetime.fromisoformat(pull["created_at"])
    cutoff = datetime.now(UTC) - timedelta(days=7)
    for run in _api(
        f"repos/{repository}/actions/runs",
        event="pull_request",
        branch=head["ref"],
        created=f"<{cutoff.isoformat(timespec='seconds').replace('+00:00', 'Z')}",
        per_page="100",
    ):
        if (
            run["event"] != "pull_request"
            or not isinstance(run.get("head_repository"), dict)
            or run["head_repository"].get("full_name") != source
            or run["head_branch"] != head["ref"]
            or datetime.fromisoformat(run["created_at"]) < opened
            or datetime.fromisoformat(run["created_at"]) > cutoff
        ):
            continue
        if not isinstance(run.get("pull_requests"), list) or (
            run["pull_requests"] and not any(item["number"] == pull["number"] for item in run["pull_requests"])
        ):
            continue
        try:
            encoded = _api_object(f"repos/{source}/contents/{config}?ref={run['head_sha']}")["content"]
        except RuntimeError as error:
            if "HTTP 404" in str(error):
                continue
            raise
        if pair in _pairs(base64.b64decode(encoded).decode("utf-8")):
            return True
    return False


def _api(path: str, **fields: str) -> list[dict[str, Any]]:
    command = ["gh", "api", "--paginate", "--slurp", "-X", "GET", path]
    for name, value in fields.items():
        command.extend(("-f", f"{name}={value}"))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"GitHub API request failed for {path}: {result.stderr.strip()}")
    return [
        item
        for page in json.loads(result.stdout)
        for item in (page if isinstance(page, list) else page.get("workflow_runs", page.get("jobs", [])))
    ]


def _api_object(path: str) -> dict[str, Any]:
    result = subprocess.run(["gh", "api", path], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"GitHub API request failed for {path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _git(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _git_optional(*arguments: str) -> str | None:
    result = subprocess.run(["git", *arguments], text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


if __name__ == "__main__":
    main()


__all__ = [
    "check_tagged_hooks",
    "main",
]

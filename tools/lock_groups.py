"""Require a project lock produced by release-creator and check its workspace sources."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Mapping
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    args = parser.parse_args()
    try:
        with args.lock.open("rb") as stream:
            provider = lock_provider(tomllib.load(stream).get("tool"))
    except (OSError, TypeError, ValueError) as error:
        parser.error(f"cannot read the lock producer: {error}")
    if provider != "release-creator":
        parser.error(f"{args.lock} must come from release-creator locks; relock it")


def validate_workspace_sources(project: Path) -> None:
    with project.open("rb") as stream:
        root = tomllib.load(stream)
    workspace = root.get("tool", {}).get("uv", {}).get("workspace", {})
    members = workspace.get("members", [])
    excluded = workspace.get("exclude", [])
    if not all(
        isinstance(patterns, list) and all(isinstance(pattern, str) for pattern in patterns)
        for patterns in (members, excluded)
    ):
        raise ValueError("workspace patterns must be strings")
    directory = project.parent.resolve()

    def matched(patterns: list[str]) -> set[Path]:
        paths = {path.resolve() for pattern in patterns for path in directory.glob(pattern)}
        if any(not path.is_relative_to(directory) for path in paths):
            raise ValueError("workspace members must be inside the project")
        return paths

    projects = [root]
    for member in sorted(matched(members) - matched(excluded)):
        if member.is_dir():
            with (member / "pyproject.toml").open("rb") as stream:
                projects.append(tomllib.load(stream))
    names = {
        _normalized_name(name) for item in projects if isinstance(name := item.get("project", {}).get("name"), str)
    }
    for item in projects:
        for name, source in item.get("tool", {}).get("uv", {}).get("sources", {}).items():
            if source != {"workspace": True} or _normalized_name(name) not in names:
                raise ValueError(f"uv source must name a workspace project: {name}")


def _normalized_name(name: str) -> str:
    return "-".join(filter(None, name.casefold().replace("_", "-").replace(".", "-").split("-")))


def lock_provider(tool: Mapping[str, object] | None) -> str:
    if "release-creator" in (tool or {}):
        return "release-creator"
    if "nab" in (tool or {}):
        return "nab"
    raise ValueError("lock has no recognized producer")


if __name__ == "__main__":
    main()


__all__ = [
    "lock_provider",
    "main",
    "validate_workspace_sources",
]

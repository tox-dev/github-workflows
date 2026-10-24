"""Read the lock producer and its selected release groups."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Mapping
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--provider", action="store_true")
    args = parser.parse_args()
    try:
        with args.lock.open("rb") as stream:
            lock = tomllib.load(stream)
        provider = lock_provider(lock.get("tool"))
        if args.provider:
            print(provider)
            return
        if provider == "release-creator":
            declared, declared_extras = project_selections(args.lock.with_name("pyproject.toml"))
            if lock.get("default-groups") != []:
                raise ValueError("project lock must not install default groups")
            selected = lock["dependency-groups"]
            if not isinstance(selected, list) or not all(isinstance(group, str) for group in selected):
                raise ValueError("project lock has invalid dependency groups")
            if not all(group.isascii() and group.replace("-", "").isalnum() for group in selected):
                raise ValueError("project lock has invalid dependency groups")
            required = declared | {"project-runtime"}
            if missing := required - set(selected):
                raise ValueError(f"project lock omits dependency groups: {', '.join(sorted(missing))}")
            if len(selected) != len(set(selected)) or set(selected) - required - {"build"}:
                raise ValueError("project lock has invalid or undeclared dependency groups")
            extras = lock.get("extras", [])
            if not isinstance(extras, list) or not all(isinstance(extra, str) for extra in extras):
                raise ValueError("project lock has invalid extras")
            if missing_extras := declared_extras - set(extras):
                raise ValueError(f"project lock omits extras: {', '.join(sorted(missing_extras))}")
            if len(extras) != len(set(extras)) or set(extras) != declared_extras:
                raise ValueError("project lock has invalid or undeclared extras")
            print(" ".join(group for group in selected if group.startswith("release-")))
            return
        command = lock["tool"]["nab"]["command-line"]
        if not isinstance(command, list) or not all(isinstance(value, str) for value in command):
            raise ValueError("Nab command-line must be a list of strings")
        start = command.index("--groups") + 1
        groups = command[
            start : next(
                (index for index in range(start, len(command)) if command[index].startswith("--")), len(command)
            )
        ]
        if not groups:
            parser.error("Nab lock records no selected groups")
        with args.lock.with_name("pyproject.toml").open("rb") as stream:
            declared = tomllib.load(stream).get("dependency-groups", {})
        if not all(group.isascii() and group.replace("-", "").isalnum() and group in declared for group in groups):
            raise ValueError("Nab lock selects an invalid or undeclared group")
        required = {name for name in declared if name.startswith("release-")}
        if missing := required - set(groups):
            raise ValueError(f"Nab lock omits release groups: {', '.join(sorted(missing))}")
        print(" ".join(groups))
    except (KeyError, OSError, TypeError, ValueError) as error:
        parser.error(f"cannot read lock groups: {error}")


def project_selections(project: Path) -> tuple[set[str], set[str]]:
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
    return (
        {group for item in projects for group in item.get("dependency-groups", {})},
        {extra for item in projects for extra in item.get("project", {}).get("optional-dependencies", {})},
    )


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
    "project_selections",
]

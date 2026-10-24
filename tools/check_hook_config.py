"""Check the hook changes allowed in a bot pull request."""

from __future__ import annotations

import argparse
import json
import re
import ssl
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from re import Pattern
from typing import Final, cast
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import certifi
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from yaml import MappingNode, ScalarNode, SequenceNode, YAMLError, compose, safe_load
from yaml.error import Mark

_MANAGED_MARKER: Final[Pattern[str]] = re.compile(
    r"""
    ^ \s* ,? \s*
    (?P<marker> [#] \s+ release-creator \s+ managed )
    (?: \s | $ )
    """,
    re.VERBOSE,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("proposed", type=Path)
    parser.add_argument("--managed", choices=("true", "false", ""), default="")
    parser.add_argument("--minimum-days", type=int, default=7)
    args = parser.parse_args()
    try:
        check_config(args.base, args.proposed, args.managed == "true", args.minimum_days)
    except (InvalidRequirement, KeyError, OSError, TypeError, ValueError, YAMLError) as error:
        parser.error(str(error))


def check_config(base: Path, proposed: Path, managed: bool, minimum_days: int) -> None:
    if minimum_days < 7:
        raise ValueError("hook cooldown must be at least seven days")
    base_source = base.read_text(encoding="utf-8")
    proposed_source = proposed.read_text(encoding="utf-8")
    _reject_duplicate_keys(base_source)
    _reject_duplicate_keys(proposed_source)
    old = safe_load(base_source)
    new = safe_load(proposed_source)
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise TypeError("hook configuration must be a mapping")
    old_content = deepcopy(old)
    new_content = deepcopy(new)
    old_repos = old_content.get("repos")
    new_repos = new_content.get("repos")
    if not isinstance(old_repos, list) or not isinstance(new_repos, list):
        raise TypeError("hook repositories must be lists")
    for repository in (*old_repos, *new_repos):
        if not isinstance(repository, dict):
            raise TypeError("hook repository must be a mapping")
        repository.pop("rev", None)
    if managed:
        old_pins = list(_dependency_groups(base_source))
        new_pins = list(_dependency_groups(proposed_source))
        if len(old_pins) != len(new_pins):
            raise ValueError("hook update changes fields beyond revisions and managed dependencies")
        for old_group, new_group in zip(old_pins, new_pins, strict=True):
            _check_dependency_group(old_group, new_group, minimum_days)
        for repository in (*old_repos, *new_repos):
            for hook in repository.get("hooks", []):
                hook.pop("additional_dependencies", None)
    if old_content != new_content:
        raise ValueError(
            "hook update changes fields beyond revisions and managed dependencies"
            if managed
            else "hook update changes fields beyond revisions"
        )


def _dependency_groups(source: str) -> Iterator[list[tuple[str, bool]]]:
    root = cast("MappingNode", compose(source))
    repositories = cast("SequenceNode", _value(root, "repos"))
    for repository in repositories.value:
        hooks = _value(cast("MappingNode", repository), "hooks")
        if not isinstance(hooks, SequenceNode):
            raise TypeError("hook repository must contain hooks")
        for hook in hooks.value:
            if not isinstance(hook, MappingNode):
                raise TypeError("hook must be a mapping")
            dependencies = _value(hook, "additional_dependencies")
            if dependencies is None:
                yield []
                continue
            if not isinstance(dependencies, SequenceNode) or not all(
                isinstance(item, ScalarNode) for item in dependencies.value
            ):
                raise TypeError("additional_dependencies must be a list of package strings")
            yield [(item.value, _managed_marker(source, item)) for item in dependencies.value]


def _managed_marker(source: str, item: ScalarNode) -> bool:
    suffix = source[cast("Mark", item.end_mark).index :].split("\n", 1)[0]
    return _MANAGED_MARKER.match(suffix) is not None


def _reject_duplicate_keys(source: str) -> None:
    root = compose(source)
    pending = [root]
    visited: set[int] = set()
    while pending:
        node = pending.pop()
        if node is None or id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, MappingNode):
            names = [key.value for key, _ in node.value if isinstance(key, ScalarNode)]
            if len(names) != len(set(names)):
                raise ValueError("hook configuration contains duplicate mapping keys")
            pending.extend(child for pair in node.value for child in pair)
        elif isinstance(node, SequenceNode):
            pending.extend(node.value)


def _value(node: MappingNode, name: str) -> object:
    return next((value for key, value in node.value if isinstance(key, ScalarNode) and key.value == name), None)


def _check_dependency_group(old: list[tuple[str, bool]], new: list[tuple[str, bool]], minimum_days: int) -> None:
    old_direct = [item for item, managed in old if not managed]
    new_direct = [item for item, managed in new if not managed]
    if len(old_direct) != len(new_direct):
        raise ValueError("hook update changes direct dependencies")
    for previous, proposed in zip(old_direct, new_direct, strict=True):
        if previous == proposed:
            continue
        old_requirement = Requirement(previous)
        new_requirement = Requirement(proposed)
        if (
            canonicalize_name(old_requirement.name) != canonicalize_name(new_requirement.name)
            or old_requirement.extras != new_requirement.extras
            or old_requirement.marker != new_requirement.marker
            or old_requirement.url is not None
            or new_requirement.url is not None
            or not _exact(old_requirement)
        ):
            raise ValueError("hook update changes direct dependencies beyond an exact pin")
        _check_pypi(new_requirement, minimum_days)
    previous_managed = {_requirement_key(Requirement(item)) for item, marked in old if marked}
    proposed_managed = {_requirement_key(Requirement(item)) for item, marked in new if marked}
    if previous_managed - proposed_managed:
        raise ValueError("hook update removes managed dependencies")
    names = [canonicalize_name(Requirement(item).name) for item, _ in new]
    if len(names) != len(set(names)):
        raise ValueError("hook update duplicates a dependency")
    for item, marked in new:
        if marked and item not in {previous for previous, old_marked in old if old_marked}:
            _check_pypi(Requirement(item), minimum_days)


def _requirement_key(requirement: Requirement) -> tuple[str, frozenset[str], str]:
    return canonicalize_name(requirement.name), frozenset(requirement.extras), str(requirement.marker)


def _exact(requirement: Requirement) -> bool:
    return (
        requirement.url is None
        and len(requirement.specifier) == 1
        and (specifier := next(iter(requirement.specifier))).operator == "=="
        and "*" not in specifier.version
    )


def _check_pypi(requirement: Requirement, minimum_days: int) -> None:
    if not _exact(requirement):
        raise ValueError(f"hook dependency is not an exact PyPI pin: {requirement}")
    version = Version(next(iter(requirement.specifier)).version)
    name = canonicalize_name(requirement.name)
    request = Request(
        f"https://pypi.org/pypi/{quote(name)}/{quote(str(version))}/json",
        headers={"Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=10, context=ssl.create_default_context(cafile=certifi.where())) as response:
        listing = json.load(response)
    files = listing.get("urls")
    if (
        canonicalize_name(listing.get("info", {}).get("name", "")) != name
        or Version(listing.get("info", {}).get("version", "0")) != version
        or not isinstance(files, list)
        or not files
    ):
        raise ValueError(f"invalid PyPI hook dependency: {requirement}")
    cutoff = datetime.now(UTC) - timedelta(days=minimum_days)
    for file in files:
        url = urlsplit(file.get("url", ""))
        uploaded = datetime.fromisoformat(file.get("upload_time_iso_8601", ""))
        if (
            file.get("yanked")
            or url.scheme != "https"
            or url.netloc != "files.pythonhosted.org"
            or not file.get("digests", {}).get("sha256")
            or uploaded.tzinfo is None
            or uploaded > cutoff
        ):
            raise ValueError(f"hook dependency has an uncooled or untrusted PyPI artifact: {requirement}")


if __name__ == "__main__":
    main()


__all__ = ["check_config", "main"]

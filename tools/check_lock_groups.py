"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import json
import re
import ssl
import time
import tomllib
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http.client import IncompleteRead
from pathlib import Path
from typing import Final, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import certifi
from packaging._parser import Variable
from packaging.markers import Marker
from packaging.pylock import Package, Pylock, PylockValidationError
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion

_DURATION: Final = re.compile(r"P(?P<days>[0-9]+)D")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="*")
    parser.add_argument("--build-constraints", action="store_true")
    parser.add_argument("--verify-pypi", action="store_true")
    parser.add_argument("--project", type=Path)
    args = parser.parse_args()
    try:
        groups = {"build"} if args.build_constraints else set(args.groups)
        if not groups:
            parser.error("at least one dependency group is required")
        with args.lock.open("rb") as stream:
            lock = Pylock.from_dict(tomllib.load(stream))
        if unnormalized := sorted(
            name for name in {*groups, *(lock.dependency_groups or ())} if canonicalize_name(name) != name
        ):
            raise ValueError(f"dependency group names must be normalized: {', '.join(unnormalized)}")
        nab: dict = {}
        if args.project:
            if (args.project.parent / "nab.toml").exists():
                raise ValueError("project nab.toml can override the reviewed index policy")
            with args.project.open("rb") as stream:
                nab = tomllib.load(stream).get("tool", {}).get("nab", {})
            _validate_indexes(nab)
            if lock_provider(lock.tool) == "release-creator":
                validate_workspace_sources(args.project)
        if (missing := groups - set(lock.dependency_groups or ())) and not (
            args.build_constraints and missing == {"build"}
        ):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
        if args.build_constraints and "build" not in (lock.dependency_groups or ()):
            groups.clear()
        _check_cooling(lock, groups, nab)
        if args.verify_pypi:
            _verify_pypi(lock, groups)
    except (IncompleteRead, InvalidVersion, KeyError, OSError, PylockValidationError, TypeError, ValueError) as error:
        parser.error(str(error))


def lock_provider(tool: Mapping[str, object] | None) -> str:
    if "release-creator" in (tool or {}):
        return "release-creator"
    if "nab" in (tool or {}):
        return "nab"
    raise ValueError("lock has no recognized producer")


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


def _validate_indexes(nab: dict) -> None:
    if any(index != {"name": "pypi", "url": "https://pypi.org/simple/"} for index in nab.get("indexes", [])):
        raise ValueError("custom Nab indexes are not approved for release locks")
    if nab.get("index") or any("index" in settings for settings in nab.get("packages", {}).values()):
        raise ValueError("custom Nab indexes are not approved for release locks")
    if any("index" in settings for settings in nab.get("package-rules", [])):
        raise ValueError("custom Nab indexes are not approved for release locks")


def _check_cooling(lock: Pylock, groups: set[str], nab: dict) -> None:
    producer = (lock.tool or {}).get(lock_provider(lock.tool))
    if not isinstance(producer, dict):
        raise TypeError("lock producer settings must be a table")
    created = producer.get("created-at")
    if not isinstance(created, datetime) or created.tzinfo is None or created > datetime.now(tz=UTC):
        raise ValueError("lock has no valid creation time or was created in the future")
    threshold = created - timedelta(days=7)
    cutoffs = _package_cutoffs(nab, created)
    whole_seconds = lock.created_by == "release-creator (uv)" and lock_provider(lock.tool) == "release-creator"
    for package in _selected_packages(lock, groups):
        if package.archive is not None or package.vcs is not None or package.directory is not None:
            raise ValueError(f"release lock has a direct-source package: {package.name}")
        if package.index is None:
            raise ValueError(f"release lock has an uncooled non-index package: {package.name}")
        if package.index != "https://pypi.org/simple/":
            raise ValueError(f"release lock has an unapproved index: {package.name}: {package.index}")
        artifacts = ([package.sdist] if package.sdist is not None else []) + list(package.wheels or ())
        cutoff = max(threshold, cutoffs.get(canonicalize_name(package.name), threshold))
        for artifact in artifacts:
            url = urlsplit(artifact.url or "")
            if artifact.path is not None or url.scheme != "https" or url.netloc != "files.pythonhosted.org":
                raise ValueError(f"release lock has a non-PyPI artifact: {artifact.name}")
            if (
                artifact.upload_time is None
                or artifact.upload_time.tzinfo is None
                or artifact.upload_time + timedelta(seconds=whole_seconds) > min(cutoff, created)
            ):
                raise ValueError(f"release lock has an uncooled artifact: {artifact.name}")


def _package_cutoffs(nab: dict, created: datetime) -> dict[str, datetime]:
    overrides = [
        (name, settings["uploaded-prior-to"])
        for name, settings in nab.get("packages", {}).items()
        if "uploaded-prior-to" in settings
    ]
    overrides.extend(
        (name, rule["uploaded-prior-to"])
        for rule in nab.get("package-rules", [])
        if "uploaded-prior-to" in rule
        for name in rule["match"]
    )
    cutoffs: dict[str, datetime] = {}
    for name, value in overrides:
        cutoff = _cutoff(name, value, created)
        key = canonicalize_name(name)
        cutoffs[key] = max(cutoff, cutoffs.get(key, cutoff))
    return cutoffs


def _cutoff(name: str, value: object, created: datetime) -> datetime:
    if value is False:
        return created
    if isinstance(value, str) and (match := _DURATION.fullmatch(value)) is not None:
        return created - timedelta(days=int(match["days"]))
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"invalid Nab cutoff for {name}: {value}") from error
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"invalid Nab cutoff for {name}: {value}")
    return value


def _verify_pypi(lock: Pylock, groups: set[str]) -> None:
    expected: dict[str, list[tuple[str, str | None, str, datetime | None]]] = defaultdict(list)
    for package in _selected_packages(lock, groups):
        for artifact in ([package.sdist] if package.sdist is not None else []) + list(package.wheels or ()):
            expected[canonicalize_name(package.name)].append(
                (
                    urlsplit(artifact.url or "").path.rsplit("/", 1)[-1],
                    artifact.url,
                    artifact.hashes["sha256"],
                    artifact.upload_time,
                )
            )
    whole_seconds = lock.created_by == "release-creator (uv)" and lock_provider(lock.tool) == "release-creator"
    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in pool.map(
            _verify_package_metadata, ((name, artifacts, whole_seconds) for name, artifacts in expected.items())
        ):
            pass


def _verify_package_metadata(item: tuple[str, list[tuple[str, str | None, str, datetime | None]], bool]) -> None:
    name, artifacts, whole_seconds = item
    for attempt in range(5):
        _, actual = _pypi_files(name)
        mismatch = next(
            (
                filename
                for filename, url, digest, upload_time in artifacts
                if not (
                    (record := actual.get(filename)) is not None
                    and record[:2] == (url, digest)
                    and (
                        record[2] == upload_time
                        or whole_seconds
                        and record[2] is not None
                        and record[2].replace(microsecond=0) == upload_time
                    )
                )
            ),
            None,
        )
        if mismatch is None:
            return
        if attempt < 4:
            time.sleep(2**attempt)
    raise ValueError(f"release lock differs from PyPI metadata: {name}: {mismatch}")


def _selected_packages(lock: Pylock, groups: set[str]) -> Iterator[Package]:
    selections = (groups, {"build"}) if "build" in (lock.dependency_groups or ()) else (groups,)
    for package in lock.packages:
        if package.marker is None or any(_possibly_selected(package.marker, selection) for selection in selections):
            yield package


def _possibly_selected(marker: Marker, groups: set[str]) -> bool:
    def expression(nodes: Iterable[object]) -> bool:
        alternatives: list[bool] = []
        current = True
        for node in nodes:
            if node == "or":
                alternatives.append(current)
                current = True
            elif node != "and":
                if isinstance(node, list):
                    current &= expression(node)
                else:
                    left, operator, right = cast("tuple[object, object, object]", node)
                    if isinstance(right, Variable) and str(right) == "dependency_groups" and str(operator) == "in":
                        current &= str(left) in groups
                    elif (
                        isinstance(right, Variable) and str(right) == "dependency_groups" and str(operator) == "not in"
                    ):
                        current &= str(left) not in groups
                    elif isinstance(right, Variable) and str(right) == "extras":
                        current &= str(operator) == "not in"
        return any((*alternatives, current))

    return expression(marker._markers)


def _pypi_files(name: str) -> tuple[str, dict[str, tuple[str | None, str | None, datetime | None]]]:
    request = Request(
        f"https://pypi.org/simple/{name}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json", "Cache-Control": "no-cache"},
    )
    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=10, context=ssl.create_default_context(cafile=certifi.where())) as response:
                listing = json.load(response)
            break
        except HTTPError as error:
            if (error.code not in (404, 429) and error.code < 500) or attempt == 4:
                raise
        except IncompleteRead, TimeoutError, URLError:
            if attempt == 4:
                raise
        time.sleep(2**attempt)
        attempt += 1
    if (
        not isinstance(listing, dict)
        or not isinstance(listing.get("meta"), dict)
        or not isinstance(listing.get("files"), list)
        or not str(listing["meta"].get("api-version", "")).startswith("1.")
        or canonicalize_name(listing.get("name", "")) != name
    ):
        raise ValueError(f"invalid PyPI listing for {name}")
    files: dict[str, tuple[str | None, str | None, datetime | None]] = {}
    for file in listing["files"]:
        if not isinstance(file, dict):
            raise TypeError(f"invalid PyPI listing for {name}")
        if file.get("yanked", False):
            continue
        files[file["filename"]] = (
            file.get("url"),
            file.get("hashes", {}).get("sha256"),
            datetime.fromisoformat(file["upload-time"]) if "upload-time" in file else None,
        )
    return name, files


if __name__ == "__main__":
    main()


__all__ = [
    "lock_provider",
    "main",
    "validate_workspace_sources",
]

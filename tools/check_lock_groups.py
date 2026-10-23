"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import json
import tomllib
from collections import defaultdict
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from nab_cutoffs import reviewed_cutoff, validate_indexes
from packaging.pylock import Package, Pylock, PylockValidationError
from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename
from packaging.version import InvalidVersion, Version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="*")
    parser.add_argument("--shared-lock", type=Path)
    parser.add_argument("--local-tool-source", action="store_true")
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
        if args.project:
            if (args.project.parent / "nab.toml").exists():
                raise ValueError("project nab.toml can override the reviewed index policy")
            with args.project.open("rb") as stream:
                validate_indexes(tomllib.load(stream)["tool"]["nab"])
        if (missing := groups - set(lock.dependency_groups or ())) and not (
            args.build_constraints and missing == {"build"}
        ):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
        if args.build_constraints and not lock.dependency_groups:
            groups.clear()
        _check_cooling(lock, groups, local_tool_source=args.local_tool_source)
        if args.verify_pypi:
            _verify_pypi(lock, groups, local_tool_source=args.local_tool_source)
        if args.shared_lock:
            with args.shared_lock.open("rb") as stream:
                shared = Pylock.from_dict(tomllib.load(stream))
            required = _selected_release_creator(shared, groups)
            if required is not None and not args.local_tool_source:
                installed = _selected_release_creator(lock, groups)
                if installed is None or installed < required:
                    parser.error(f"relock: release-creator {required} required")
    except (InvalidVersion, KeyError, OSError, PylockValidationError, TypeError, ValueError) as error:
        parser.error(str(error))


def _check_cooling(lock: Pylock, groups: set[str], *, local_tool_source: bool = False) -> None:
    created = lock.tool.get("nab", {}).get("created-at") if lock.tool else None
    if not isinstance(created, datetime) or created.tzinfo is None or created > datetime.now(tz=UTC):
        raise ValueError("lock has no valid creation time or was created in the future")
    threshold = created - timedelta(days=7)
    for package in _selected_packages(lock, groups, local_tool_source=local_tool_source):
        if package.index is None:
            raise ValueError(f"release lock has an uncooled non-index package: {package.name}")
        if package.index != "https://pypi.org/simple/":
            raise ValueError(f"release lock has an unapproved index: {package.name}: {package.index}")
        artifacts = ([package.sdist] if package.sdist is not None else []) + list(package.wheels or ())
        cutoff = max(threshold, reviewed_cutoff(package.name, str(package.version)) or threshold)
        for artifact in artifacts:
            url = urlsplit(artifact.url or "")
            if artifact.path is not None or url.scheme != "https" or url.netloc != "files.pythonhosted.org":
                raise ValueError(f"release lock has a non-PyPI artifact: {artifact.name}")
            filename = url.path.rsplit("/", 1)[-1]
            identity = (
                parse_wheel_filename(filename)[:2] if filename.endswith(".whl") else parse_sdist_filename(filename)
            )
            if identity != (canonicalize_name(package.name), Version(str(package.version))):
                raise ValueError(f"release lock artifact differs from package version: {filename}")
            if (
                artifact.upload_time is None
                or artifact.upload_time.tzinfo is None
                or artifact.upload_time > min(cutoff, created)
            ):
                raise ValueError(f"release lock has an uncooled artifact: {artifact.name}")


def _verify_pypi(lock: Pylock, groups: set[str], *, local_tool_source: bool) -> None:
    expected: dict[str, list[tuple[str, str | None, str, datetime | None]]] = defaultdict(list)
    for package in _selected_packages(lock, groups, local_tool_source=local_tool_source):
        for artifact in ([package.sdist] if package.sdist is not None else []) + list(package.wheels or ()):
            expected[canonicalize_name(package.name)].append(
                (
                    urlsplit(artifact.url or "").path.rsplit("/", 1)[-1],
                    artifact.url,
                    artifact.hashes["sha256"],
                    artifact.upload_time,
                )
            )
    with ThreadPoolExecutor(max_workers=8) as pool:
        for name, actual in pool.map(_pypi_files, expected):
            for filename, url, digest, upload_time in expected[name]:
                if actual.get(filename) != (url, digest, upload_time):
                    raise ValueError(f"release lock differs from PyPI metadata: {name}: {filename}")


def _selected_packages(lock: Pylock, groups: set[str], *, local_tool_source: bool) -> Iterator[Package]:
    selections = (groups, {"build"}) if "build" in (lock.dependency_groups or ()) else (groups,)
    for package in lock.packages:
        if package.marker is not None and not any(
            package.marker.evaluate({"dependency_groups": selection}, context="lock_file") for selection in selections
        ):
            continue
        if local_tool_source and package.name == "release-creator" and package.index is None:
            continue
        yield package


def _pypi_files(name: str) -> tuple[str, dict[str, tuple[str | None, str | None, datetime | None]]]:
    request = Request(
        f"https://pypi.org/simple/{name}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json", "Cache-Control": "no-cache"},
    )
    with urlopen(request, timeout=30) as response:
        listing = json.load(response)
    if (
        not str(listing.get("meta", {}).get("api-version", "")).startswith("1.")
        or canonicalize_name(listing.get("name", "")) != name
    ):
        raise ValueError(f"invalid PyPI listing for {name}")
    files: dict[str, tuple[str | None, str | None, datetime | None]] = {}
    for file in listing["files"]:
        files[file["filename"]] = (
            file.get("url"),
            file.get("hashes", {}).get("sha256"),
            datetime.fromisoformat(file["upload-time"]) if "upload-time" in file else None,
        )
    return name, files


def _selected_release_creator(lock: Pylock, groups: set[str]) -> Version | None:
    return next(
        (
            Version(str(package.version))
            for package in lock.packages
            if package.name == "release-creator"
            and (package.marker is None or package.marker.evaluate({"dependency_groups": groups}, context="lock_file"))
        ),
        None,
    )


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

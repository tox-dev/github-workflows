"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from nab_cutoffs import reviewed_cutoff
from packaging.pylock import Pylock, PylockValidationError
from packaging.version import InvalidVersion, Version

_COOLDOWN = timedelta(days=7)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="*")
    parser.add_argument("--shared-lock", type=Path)
    parser.add_argument("--local-tool-source", action="store_true")
    parser.add_argument("--build-constraints", action="store_true")
    args = parser.parse_args()
    try:
        groups = {"build"} if args.build_constraints else set(args.groups)
        if not groups:
            parser.error("at least one dependency group is required")
        with args.lock.open("rb") as stream:
            lock = Pylock.from_dict(tomllib.load(stream))
        if (missing := groups - set(lock.dependency_groups or ())) and not (
            args.build_constraints and missing == {"build"}
        ):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
        _check_cooling(lock, groups | {"build"}, local_tool_source=args.local_tool_source)
        if args.shared_lock:
            with args.shared_lock.open("rb") as stream:
                shared = Pylock.from_dict(tomllib.load(stream))
            _check_cooling(shared, groups | {"build"})
            required = _selected_release_creator(shared, groups)
            if required is not None and not args.local_tool_source:
                installed = _selected_release_creator(lock, groups)
                if installed is None or installed < required:
                    parser.error(f"relock: release-creator {required} required")
    except (InvalidVersion, OSError, PylockValidationError, ValueError) as error:
        parser.error(str(error))


def _check_cooling(lock: Pylock, groups: set[str], *, local_tool_source: bool = False) -> None:
    created = lock.tool.get("nab", {}).get("created-at") if lock.tool else None
    if not isinstance(created, datetime) or created.tzinfo is None or created > datetime.now(tz=UTC):
        raise ValueError("lock has no valid creation time or was created in the future")
    threshold = created - _COOLDOWN
    for package in lock.packages:
        if package.marker is not None and not package.marker.evaluate(
            {"dependency_groups": groups}, context="lock_file"
        ):
            continue
        if local_tool_source and package.name == "release-creator" and package.index is None:
            continue
        if package.index is None:
            raise ValueError(f"release lock has an uncooled non-index package: {package.name}")
        artifacts = ([package.sdist] if package.sdist is not None else []) + list(package.wheels or ())
        if not artifacts:
            raise ValueError(f"release lock has no dated artifacts: {package.name}")
        cutoff = max(threshold, reviewed_cutoff(package.name, str(package.version)) or threshold)
        for artifact in artifacts:
            url = urlsplit(artifact.url or "")
            if artifact.path is not None or url.scheme != "https" or url.netloc != "files.pythonhosted.org":
                raise ValueError(f"release lock has a non-PyPI artifact: {artifact.name}")
            if (
                artifact.upload_time is None
                or artifact.upload_time.tzinfo is None
                or artifact.upload_time > min(cutoff, created)
            ):
                raise ValueError(f"release lock has an uncooled artifact: {artifact.name}")


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

"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from packaging.pylock import Pylock, PylockValidationError
from packaging.version import InvalidVersion, Version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="+")
    parser.add_argument("--shared-lock", type=Path)
    parser.add_argument("--local-tool-source", action="store_true")
    args = parser.parse_args()
    try:
        groups = set(args.groups)
        with args.lock.open("rb") as stream:
            lock = Pylock.from_dict(tomllib.load(stream))
        if missing := groups - set(lock.dependency_groups or ()):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
        if args.shared_lock:
            with args.shared_lock.open("rb") as stream:
                shared = Pylock.from_dict(tomllib.load(stream))
            required = _selected_release_creator(shared, groups)
            installed = _selected_release_creator(lock, groups)
            if required is not None and not args.local_tool_source and (installed is None or installed < required):
                parser.error(f"relock: release-creator {required} required")
    except (InvalidVersion, OSError, PylockValidationError) as error:
        parser.error(str(error))


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

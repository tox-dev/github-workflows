"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from packaging.pylock import Pylock, PylockValidationError
from packaging.version import Version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="+")
    parser.add_argument("--shared-lock", type=Path)
    args = parser.parse_args()
    try:
        with args.lock.open("rb") as stream:
            lock = Pylock.from_dict(tomllib.load(stream))
        if missing := set(args.groups) - set(lock.dependency_groups or ()):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
        if args.shared_lock:
            with args.shared_lock.open("rb") as stream:
                shared = Pylock.from_dict(tomllib.load(stream))
            required = next(package.version for package in shared.packages if package.name == "release-creator")
            installed = next((package.version for package in lock.packages if package.name == "release-creator"), None)
            needs_release_creator = bool(
                set(args.groups)
                & {"release-news", "release-notes", "release-prepare", "release-validate", "release-hooks"}
            )
            if needs_release_creator and (installed is None or Version(str(installed)) < Version(str(required))):
                parser.error(f"relock: release-creator {required} required")
    except (OSError, PylockValidationError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

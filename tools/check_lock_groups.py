"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from packaging.pylock import Pylock, PylockValidationError
from packaging.utils import canonicalize_name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="*")
    parser.add_argument("--build-constraints", action="store_true")
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
        if (missing := groups - set(lock.dependency_groups or ())) and not (
            args.build_constraints and missing == {"build"}
        ):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
    except (KeyError, OSError, PylockValidationError, TypeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

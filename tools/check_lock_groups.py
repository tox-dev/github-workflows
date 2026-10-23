"""Reject dependency groups absent from a PEP 751 lock."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from packaging.pylock import Pylock, PylockValidationError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    parser.add_argument("groups", nargs="+")
    args = parser.parse_args()
    try:
        with args.lock.open("rb") as stream:
            available = Pylock.from_dict(tomllib.load(stream)).dependency_groups
        if missing := set(args.groups) - set(available or ()):
            parser.error(f"missing lock dependency groups: {', '.join(sorted(missing))}")
    except (OSError, PylockValidationError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

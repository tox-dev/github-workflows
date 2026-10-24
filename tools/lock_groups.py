"""Print the dependency groups used to create a Nab lock."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lock", type=Path)
    args = parser.parse_args()
    try:
        with args.lock.open("rb") as stream:
            lock = tomllib.load(stream)
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
            declared = tomllib.load(stream)["dependency-groups"]
        if not all(group.isascii() and group.replace("-", "").isalnum() and group in declared for group in groups):
            raise ValueError("Nab lock selects an invalid or undeclared group")
        required = {name for name in declared if name.startswith("release")}
        if missing := required - set(groups):
            raise ValueError(f"Nab lock omits release groups: {', '.join(sorted(missing))}")
        print(" ".join(groups))
    except (KeyError, OSError, TypeError, ValueError) as error:
        parser.error(f"cannot read Nab lock groups: {error}")


if __name__ == "__main__":
    main()

"""Compare a regenerated Nab lock while ignoring the command used to regenerate it."""

from __future__ import annotations

import argparse
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("committed", type=Path)
    parser.add_argument("regenerated", type=Path)
    args = parser.parse_args()
    try:
        before = args.committed.read_bytes()
        old = tomllib.loads(before.decode())
        new = tomllib.loads(args.regenerated.read_text())
        created = old["tool"]["nab"].get("created-at")
        if not isinstance(created, datetime) or created.tzinfo is None or created > datetime.now(UTC):
            parser.error("committed Nab lock has no valid creation time or was created in the future")
        old["tool"]["nab"].pop("command-line", None)
        new["tool"]["nab"].pop("command-line", None)
        if old != new:
            parser.error("regenerated Nab lock differs from the committed lock")
        args.regenerated.write_bytes(before)
        print(
            f"Lock check: regenerated {args.regenerated} matches the committed lock (command line ignored)",
            file=sys.stderr,
        )
    except (OSError, UnicodeDecodeError, KeyError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

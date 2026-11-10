#!/usr/bin/env python3
"""Print a count and its singular or plural noun."""

import sys


def main() -> None:
    if len(sys.argv) not in {3, 4}:
        raise SystemExit("usage: plural.py COUNT SINGULAR [PLURAL]")
    count = int(sys.argv[1])
    noun = sys.argv[2]
    if count != 1:
        noun = sys.argv[3] if len(sys.argv) == 4 else f"{noun}s"
    sys.stdout.write(f"{count} {noun}")


main()

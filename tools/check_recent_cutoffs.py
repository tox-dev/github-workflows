"""Reject recent Nab cutoffs without an explicit reviewed exception."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nab_cutoffs import validate_recent_cutoffs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        validate_recent_cutoffs(args.project.read_text(), datetime.now(UTC) - timedelta(days=7))
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

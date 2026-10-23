"""Remove reviewed Nab cutoffs once the global seven-day window covers them."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nab_cutoffs import remove_expired_cutoffs
from tomlkit.exceptions import ParseError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        source = args.project.read_text()
        updated = remove_expired_cutoffs(source, datetime.now(UTC) - timedelta(days=7))
        if source != updated:
            args.project.write_text(updated)
    except (OSError, KeyError, ValueError, ParseError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

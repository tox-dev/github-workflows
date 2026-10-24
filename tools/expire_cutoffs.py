"""Remove reviewed package cutoffs once the global seven-day window covers them."""

from __future__ import annotations

import argparse
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nab_cutoffs import remove_expired_cutoffs, remove_expired_release_creator_cutoffs
from tomlkit.exceptions import ParseError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        source = args.project.read_text()
        threshold = datetime.now(UTC) - timedelta(days=7)
        tool = tomllib.loads(source)["tool"]
        updated = remove_expired_cutoffs(source, threshold) if "nab" in tool else source
        if "release-creator" in tool:
            updated = remove_expired_release_creator_cutoffs(updated, threshold)
        if source != updated:
            args.project.write_text(updated)
    except (OSError, KeyError, TypeError, ValueError, ParseError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

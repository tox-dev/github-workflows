"""Remove reviewed Nab cutoffs once the global seven-day window covers them."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import tomlkit
from nab_cutoffs import expired_cutoffs
from tomlkit.exceptions import ParseError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        source = args.project.read_text()
        names, positions = expired_cutoffs(source, datetime.now(UTC) - timedelta(days=7))
        if names or positions:
            document = tomlkit.parse(source)
            nab = document["tool"]["nab"]
            for name in names:
                settings = nab["packages"][name]
                del settings["uploaded-prior-to"]
                if not settings:
                    del nab["packages"][name]
            for index in sorted(positions, reverse=True):
                rule = nab["package-rules"][index]
                del rule["uploaded-prior-to"]
                if set(rule) == {"match"}:
                    del nab["package-rules"][index]
            if "package-rules" in nab and not nab["package-rules"]:
                del nab["package-rules"]
            args.project.write_text(tomlkit.dumps(document))
    except (OSError, KeyError, ValueError, ParseError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

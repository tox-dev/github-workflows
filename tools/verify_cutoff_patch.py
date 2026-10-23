"""Allow only expired Nab upload cutoffs to change in pyproject.toml."""

from __future__ import annotations

import argparse
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nab_cutoffs import expired_cutoffs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args()
    try:
        baseline = subprocess.run(
            ["git", "show", f"HEAD:{args.project.as_posix()}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        expected = tomllib.loads(baseline)
        names, positions = expired_cutoffs(baseline, datetime.now(UTC) - timedelta(days=7))
        nab = expected["tool"]["nab"]
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
        if expected != tomllib.loads(args.project.read_text()):
            parser.error("pyproject.toml has changes beyond expired Nab cutoffs")
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

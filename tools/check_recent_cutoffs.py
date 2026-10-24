"""Reject recent package cutoffs without an explicit reviewed exception."""

from __future__ import annotations

import argparse
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nab_cutoffs import validate_recent_cutoffs, validate_release_creator_cutoffs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    try:
        if (args.project.parent / "nab.toml").exists():
            parser.error("project nab.toml can override the reviewed cutoff policy")
        project = args.project.read_text()
        threshold = datetime.now(UTC) - timedelta(days=7)
        tool = tomllib.loads(project)["tool"]
        if "nab" in tool:
            validate_recent_cutoffs(project, threshold)
        if "release-creator" in tool:
            validate_release_creator_cutoffs(project, threshold)
        if "nab" not in tool and "release-creator" not in tool:
            raise ValueError("project has no lock cutoff policy")
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

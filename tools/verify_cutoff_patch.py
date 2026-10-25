"""Allow only expired package cutoffs to change in pyproject.toml."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nab_cutoffs import expired_cutoffs, expired_release_creator_cutoffs, remove_cutoffs, remove_release_creator_cutoffs


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
        original = tomllib.loads(baseline)
        actual = tomllib.loads(args.project.read_text())
        threshold = datetime.now(UTC) - timedelta(days=7)
        if "nab" in original["tool"]:
            names, positions = expired_cutoffs(baseline, threshold)
            before = original["tool"]["nab"]
            after = actual["tool"]["nab"]
            removed_names = {
                name for name in names if after.get("packages", {}).get(name, {}).get("uploaded-prior-to") is None
            }
            removed_positions = {
                index for index in positions if before["package-rules"][index] not in after.get("package-rules", [])
            }
            remove_cutoffs(before, removed_names, removed_positions)
        if "release-creator" in original["tool"]:
            names = expired_release_creator_cutoffs(baseline, threshold)
            before = original["tool"]["release-creator"].get("locks", {})
            after = actual["tool"]["release-creator"].get("locks", {})
            removed_names = {name for name in names if name not in after.get("exclude-newer-package", {})}
            if removed_names:
                remove_release_creator_cutoffs(before, removed_names)
        if os.environ.get("GITHUB_REPOSITORY") == "tox-dev/github-workflows":
            _accept_resolver_pin(original, actual, args.project.with_name("pylock.toml"))
        if original != actual:
            producer = "package" if "release-creator" in original["tool"] else "Nab"
            parser.error(f"pyproject.toml has changes beyond expired {producer} cutoffs")
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))


def _accept_resolver_pin(original: dict, actual: dict, lock: Path) -> None:
    before = original.get("dependency-groups", {}).get("release-resolver")
    after = actual.get("dependency-groups", {}).get("release-resolver")
    if before == after or not all(
        isinstance(pins, list) and len(pins) == 1 and isinstance(pins[0], str) and re.fullmatch(r"uv==[0-9.]+", pins[0])
        for pins in (before, after)
    ):
        return
    version = after[0].removeprefix("uv==")
    resolver = '"release-resolver" in dependency_groups'
    if not any(
        package.get("name") == "uv" and package.get("version") == version and resolver in package.get("marker", "")
        for package in tomllib.loads(lock.read_text())["packages"]
    ):
        raise ValueError(f"pylock.toml does not lock the updated resolver uv {version}")
    original["dependency-groups"]["release-resolver"] = after


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

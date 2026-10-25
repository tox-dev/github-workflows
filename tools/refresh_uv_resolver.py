"""Keep lock bytes stable when the shared uv resolver changes."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

import tomlkit
from packaging.markers import InvalidMarker, Marker
from tomlkit.exceptions import ParseError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("widen", "pin"))
    parser.add_argument("project", type=Path)
    parser.add_argument("lock", type=Path)
    args = parser.parse_args()
    try:
        project = tomlkit.parse(args.project.read_text())
        requirements = project["dependency-groups"]["release-resolver"]
        if len(requirements) != 1:
            raise ValueError("release-resolver must contain one uv requirement")
        if args.mode == "widen":
            if not str(requirements[0]).startswith("uv=="):
                raise ValueError("release-resolver must have an exact uv pin")
            requirements[0] = f"uv>={str(requirements[0]).removeprefix('uv==')}"
        else:
            if not str(requirements[0]).startswith("uv>="):
                raise ValueError("release-resolver must have the temporary uv range")
            lock = tomllib.loads(args.lock.read_text())
            if "release-resolver" not in lock["dependency-groups"]:
                raise ValueError("candidate lock omits release-resolver")
            selected = {"dependency_groups": frozenset({"release-resolver"}), "extras": frozenset()}
            versions = {
                package["version"]
                for package in lock["packages"]
                if package["name"] == "uv"
                and ("marker" not in package or Marker(package["marker"]).evaluate(selected, "lock_file"))
            }
            if len(versions) != 1:
                raise ValueError("candidate lock must select one uv resolver version")
            requirements[0] = f"uv=={versions.pop()}"
        args.project.write_text(tomlkit.dumps(project))
    except (InvalidMarker, OSError, KeyError, TypeError, ValueError, ParseError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

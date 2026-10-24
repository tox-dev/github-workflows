"""Require immutable revisions for external pre-commit hooks."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from yaml import YAMLError, safe_load


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    try:
        check_frozen(args.config)
    except (OSError, TypeError, ValueError, YAMLError) as error:
        parser.error(str(error))


def check_frozen(path: Path) -> None:
    config = safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("repos"), list):
        raise TypeError("hook configuration must contain a repository list")
    for repository in config["repos"]:
        if not isinstance(repository, dict) or not isinstance(repository.get("repo"), str):
            raise TypeError("hook repository must be a mapping with a URL")
        if repository["repo"] in {"local", "meta"}:
            continue
        revision = repository.get("rev")
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            raise ValueError(f"external hook revision must be a full lowercase commit SHA: {repository['repo']}")


if __name__ == "__main__":
    main()


__all__ = [
    "check_frozen",
    "main",
]

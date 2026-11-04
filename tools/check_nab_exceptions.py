"""Fail when a Nab cutoff exception has no expiry comment or has passed its expiry."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

_EXPIRY: Final = re.compile(r"#\s*expires\s+(\d{4}-\d{2}-\d{2})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    paths = parser.parse_args().paths
    today = datetime.now(UTC).date()
    try:
        problems = [problem for path in paths for problem in _problems(path, today)]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    if problems:
        sys.exit(1)


def _problems(path: Path, today: date) -> list[str]:
    text = path.read_text(encoding="utf-8")
    document = tomllib.loads(text)
    config: dict[str, Any] = document.get("tool", {}).get("nab", {}) if path.name == "pyproject.toml" else document
    lines = text.splitlines()
    problems = [
        f"{path}: [[package-rules]] {rule.get('match')} sets uploaded-prior-to, which expiry is not checked for;"
        " move it to a packages.<name> table"
        for rule in config.get("package-rules", [])
        if "uploaded-prior-to" in rule
    ]
    for name, body in config.get("packages", {}).items():
        if "uploaded-prior-to" in body:
            problems.extend(_exception_problems(lines, path, name, today))
    return problems


def _exception_problems(lines: list[str], path: Path, name: str, today: date) -> list[str]:
    where = f"{path}: packages.{name}"
    start = _start_line(lines, name)
    if start is None:
        return [f"{where} is not a table or dotted key that the expiry check can locate"]
    above = lines[start - 1] if start else ""
    if (match := _EXPIRY.fullmatch(above.strip())) is None:
        return [f"{where} uploaded-prior-to exception needs a '# expires YYYY-MM-DD' comment directly above it"]
    try:
        expires = date.fromisoformat(match[1])
    except ValueError:
        return [f"{where} has an invalid expiry date {match[1]}"]
    if expires < today:
        return [f"{where} uploaded-prior-to exception expired on {expires}; remove it or extend its expiry"]
    return []


def _start_line(lines: list[str], name: str) -> int | None:
    selector = rf'(?:"{re.escape(name)}"|{re.escape(name)})'
    header = re.compile(rf"\[\s*(?:tool\.nab\.)?packages\.{selector}\s*\]")
    dotted = re.compile(rf"(?:tool\.nab\.)?packages\.{selector}\.uploaded-prior-to\s*=")
    return next(
        (index for index, line in enumerate(lines) if header.match(line.lstrip()) or dotted.match(line.lstrip())),
        None,
    )


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

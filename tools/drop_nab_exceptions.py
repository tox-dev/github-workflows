"""Drop the Nab cutoff exceptions that a lock refreshed now no longer needs, and print each file it changed."""

import argparse
import re
import sys
import tomllib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from check_nab_exceptions import exception_line, nab_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    paths = parser.parse_args(namespace=_Options()).paths
    now = datetime.now(UTC)
    try:
        changed = [path for path in paths if _drop(path, now)]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
    for path in changed:
        print(path)


class _Options(argparse.Namespace):
    paths: list[Path]


def _drop(path: Path, now: datetime) -> bool:
    text = path.read_text(encoding="utf-8")
    config = nab_config(path, text)
    if (cutoff := _cutoff(config.get("uploaded-prior-to"), now)) is None:
        return False
    lines = text.splitlines(keepends=True)
    dropped = False
    for name, body in config.get("packages", {}).items():
        # A date admits that whole day, so it is redundant only once the day after it is under the cutoff.
        if (until := _moment(body.get("uploaded-prior-to"), timedelta(days=1))) is None or until > cutoff:
            continue
        if (remaining := _without(lines, name)) is None:
            continue
        lines = remaining
        dropped = True
        print(
            f"Cutoff exception dropped: {path}: packages.{name} uploaded-prior-to is at or before the refresh cutoff"
            f" {cutoff:%Y-%m-%dT%H:%M:%SZ}",
            file=sys.stderr,
        )
    if dropped:
        path.write_text("".join(lines), encoding="utf-8")
    return dropped


def _cutoff(value: object, now: datetime) -> datetime | None:
    if isinstance(value, str):
        return now - timedelta(days=int(days[1])) if (days := re.fullmatch(r"P(\d+)D", value)) else None
    return _moment(value, timedelta())


def _moment(value: object, date_offset: timedelta) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, date):
        return datetime.combine(value + date_offset, time(), UTC)
    return None


def _without(lines: list[str], name: str) -> list[str] | None:
    if (start := exception_line(lines, name)) is None:
        return None
    if not lines[start].lstrip().startswith("["):
        return _collapse(lines, _comment_start(lines, start), start + 1)
    end = next((index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")), len(lines))
    keys = [index for index in range(start + 1, end) if lines[index].strip() and not _is_comment(lines[index])]
    if len(keys) == 1:
        return _collapse(lines, _comment_start(lines, start), keys[0] + 1)
    value = next(index for index in keys if re.match(r"uploaded-prior-to\s*=", lines[index].lstrip()))
    expiry = [start - 1] if start and re.fullmatch(r"#\s*expires\s+\S+", lines[start - 1].strip()) else []
    return [line for index, line in enumerate(lines) if index not in {value, *expiry}]


def _comment_start(lines: list[str], start: int) -> int:
    while start and _is_comment(lines[start - 1]):
        start -= 1
    return start


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith("#")


def _collapse(lines: list[str], first: int, last: int) -> list[str]:
    remaining = [*lines[:first], *lines[last:]]
    if first and not remaining[first - 1].strip() and (first == len(remaining) or not remaining[first].strip()):
        del remaining[first - 1]
    return remaining


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

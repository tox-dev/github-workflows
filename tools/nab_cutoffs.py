from __future__ import annotations

import re
import tomllib
from datetime import UTC, datetime
from typing import Final

_DURATION: Final = re.compile(
    r"""
    ^P                  # ISO duration prefix
    (?P<days>[0-9]+)     # Nab supports whole days
    D$                  # Day unit and end
    """,
    re.VERBOSE,
)
_MINIMUM_DAYS: Final = 7

_REVIEWED_EXCEPTIONS = {
    **dict.fromkeys(
        ("nab", "nab-index", "nab-markersets", "nab-project", "nab-provider", "nab-resolver"),
        datetime(2026, 10, 19, tzinfo=UTC),
    ),
    "release-creator": datetime(2026, 10, 23, 2, 44, 40, tzinfo=UTC),
    "uv-build": datetime(2026, 10, 21, tzinfo=UTC),  # toml-fmt requires 0.13.4 until the cutoff matures.
}


def validate_recent_cutoffs(project: str, threshold: datetime) -> None:
    nab = tomllib.loads(project)["tool"]["nab"]
    global_cutoff = nab.get("uploaded-prior-to")
    if not isinstance(global_cutoff, str) or (match := _DURATION.fullmatch(global_cutoff)) is None:
        raise ValueError("global Nab cutoff must be a duration of at least P7D")
    if int(match["days"]) < _MINIMUM_DAYS:
        raise ValueError("global Nab cutoff must be a duration of at least P7D")
    candidates = [
        (name, settings["uploaded-prior-to"])
        for name, settings in nab.get("packages", {}).items()
        if "uploaded-prior-to" in settings
    ]
    candidates.extend(
        (name, rule["uploaded-prior-to"])
        for rule in nab.get("package-rules", [])
        if "uploaded-prior-to" in rule
        for name in rule["match"]
    )
    for name, value in candidates:
        if value is False:
            if name not in _REVIEWED_EXCEPTIONS:
                raise ValueError(f"Nab cutoff for {name} weakens the seven-day policy: {value}")
            continue
        if isinstance(value, str) and (match := _DURATION.fullmatch(value)) is not None:
            if name not in _REVIEWED_EXCEPTIONS and int(match["days"]) < _MINIMUM_DAYS:
                raise ValueError(f"Nab cutoff for {name} weakens the seven-day policy: {value}")
            continue
        if isinstance(value, bool):
            raise TypeError(f"invalid Nab cutoff for {name}: {value}")
        timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if timestamp.tzinfo is None:
            raise ValueError(f"Nab package cutoff has no timezone: {value}")
        if timestamp > threshold and timestamp > _REVIEWED_EXCEPTIONS.get(name, datetime.min.replace(tzinfo=UTC)):
            raise ValueError(f"unreviewed recent Nab cutoff for {name}: {timestamp.isoformat()}")


def remove_expired_cutoffs(project: str, threshold: datetime) -> str:
    import tomlkit

    names, positions = expired_cutoffs(project, threshold)
    if not names and not positions:
        return project
    document = tomlkit.parse(project)
    remove_cutoffs(document["tool"]["nab"], names, positions)
    return tomlkit.dumps(document)


def remove_cutoffs(nab: dict, names: set[str], positions: set[int]) -> None:
    for name in names:
        settings = nab["packages"][name]
        del settings["uploaded-prior-to"]
        if not settings:
            del nab["packages"][name]
    if "packages" in nab and not nab["packages"]:
        del nab["packages"]
    for index in sorted(positions, reverse=True):
        rule = nab["package-rules"][index]
        del rule["uploaded-prior-to"]
        if set(rule) == {"match"}:
            del nab["package-rules"][index]
    if "package-rules" in nab and not nab["package-rules"]:
        del nab["package-rules"]


def expired_cutoffs(project: str, threshold: datetime) -> tuple[set[str], set[int]]:
    nab = tomllib.loads(project)["tool"]["nab"]
    packages = {
        str(name)
        for name, settings in nab.get("packages", {}).items()
        if (value := settings.get("uploaded-prior-to")) is not None and _expired(value, threshold)
    }
    rules = {
        index
        for index, rule in enumerate(nab.get("package-rules", []))
        if (value := rule.get("uploaded-prior-to")) is not None and _expired(value, threshold)
    }
    return packages, rules


def _expired(value: str | datetime | bool, threshold: datetime) -> bool:
    if value is False or isinstance(value, str) and _DURATION.fullmatch(value) is not None:
        return False
    if isinstance(value, bool):
        raise TypeError(f"invalid Nab cutoff: {value}")
    timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if timestamp.tzinfo is None:
        raise ValueError(f"Nab package cutoff has no timezone: {value}")
    return timestamp <= threshold


__all__ = [
    "expired_cutoffs",
    "remove_cutoffs",
    "remove_expired_cutoffs",
    "validate_recent_cutoffs",
]

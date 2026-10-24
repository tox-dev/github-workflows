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

_REVIEWED_VERSIONS: Final = {
    **{
        (name, "0.0.22"): datetime(2026, 10, 18, 5, 45, 9, tzinfo=UTC)
        for name in ("nab", "nab-index", "nab-markersets", "nab-project", "nab-provider", "nab-resolver")
    },
    ("release-creator", "0.6.5"): datetime(2026, 10, 23, 19, 54, 50, tzinfo=UTC),
    ("release-creator", "0.6.6"): datetime(2026, 10, 23, 20, 48, 24, tzinfo=UTC),
    ("release-creator", "0.6.7"): datetime(2026, 10, 23, 21, 40, 6, tzinfo=UTC),
    ("release-creator", "1.0.0"): datetime(2026, 10, 24, 6, 7, 46, tzinfo=UTC),
    ("uv-build", "0.13.4"): datetime(2026, 10, 21, tzinfo=UTC),
}
_REVIEWED_EXCEPTIONS: Final = {
    name: min(reviewed for (package, _), reviewed in _REVIEWED_VERSIONS.items() if package == name)
    for name, _ in _REVIEWED_VERSIONS
}


def reviewed_cutoff(name: str, version: str) -> datetime | None:
    return _REVIEWED_VERSIONS.get((name, version))


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
    for name, settings in nab.get("index", {}).items():
        if "uploaded-prior-to" in settings:
            raise ValueError(f"Nab index cutoff for {name} bypasses the seven-day policy")
    validate_indexes(nab)
    for name, value in candidates:
        if value is False:
            raise ValueError(f"Nab cutoff for {name} weakens the seven-day policy: {value}")
        if isinstance(value, str) and (match := _DURATION.fullmatch(value)) is not None:
            if int(match["days"]) < _MINIMUM_DAYS:
                raise ValueError(f"Nab cutoff for {name} weakens the seven-day policy: {value}")
            continue
        if isinstance(value, bool):
            raise TypeError(f"invalid Nab cutoff for {name}: {value}")
        timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if timestamp.tzinfo is None:
            raise ValueError(f"Nab package cutoff has no timezone: {value}")
        if timestamp > threshold and timestamp not in {
            reviewed for (package, _), reviewed in _REVIEWED_VERSIONS.items() if package == name
        }:
            raise ValueError(f"unreviewed recent Nab cutoff for {name}: {timestamp.isoformat()}")


def validate_indexes(nab: dict) -> None:
    if any(index != {"name": "pypi", "url": "https://pypi.org/simple/"} for index in nab.get("indexes", [])):
        raise ValueError("custom Nab indexes are not approved for release locks")
    if nab.get("index") or any("index" in settings for settings in nab.get("packages", {}).values()):
        raise ValueError("custom Nab indexes are not approved for release locks")
    if any("index" in settings for settings in nab.get("package-rules", [])):
        raise ValueError("custom Nab indexes are not approved for release locks")


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
        if name in _REVIEWED_EXCEPTIONS
        and (value := settings.get("uploaded-prior-to")) is not None
        and _expired(
            value, threshold, {reviewed for (package, _), reviewed in _REVIEWED_VERSIONS.items() if package == name}
        )
    }
    rules = {
        index
        for index, rule in enumerate(nab.get("package-rules", []))
        if set(rule["match"]) <= _REVIEWED_EXCEPTIONS.keys()
        and (value := rule.get("uploaded-prior-to")) is not None
        and all(
            _expired(
                value, threshold, {reviewed for (package, _), reviewed in _REVIEWED_VERSIONS.items() if package == name}
            )
            for name in rule["match"]
        )
    }
    return packages, rules


def _expired(value: str | datetime | bool, threshold: datetime, reviewed: set[datetime]) -> bool:
    if value is False or isinstance(value, str) and _DURATION.fullmatch(value) is not None:
        return False
    if isinstance(value, bool):
        raise TypeError(f"invalid Nab cutoff: {value}")
    timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if timestamp.tzinfo is None:
        raise ValueError(f"Nab package cutoff has no timezone: {value}")
    return timestamp in reviewed and timestamp <= threshold


__all__ = [
    "expired_cutoffs",
    "remove_cutoffs",
    "remove_expired_cutoffs",
    "reviewed_cutoff",
    "validate_indexes",
    "validate_recent_cutoffs",
]

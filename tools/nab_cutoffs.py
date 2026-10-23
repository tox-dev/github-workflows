from __future__ import annotations

import tomllib
from datetime import UTC, datetime

_REVIEWED_EXCEPTIONS = {
    **dict.fromkeys(
        ("nab", "nab-index", "nab-markersets", "nab-project", "nab-provider", "nab-resolver"),
        datetime(2026, 10, 19, tzinfo=UTC),
    ),
    "release-creator": datetime(2026, 10, 23, 2, 44, 40, tzinfo=UTC),
}


def validate_recent_cutoffs(project: str, threshold: datetime) -> None:
    nab = tomllib.loads(project)["tool"]["nab"]
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
        if isinstance(value, str) and value.startswith("P"):
            continue
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
        name
        for name, settings in nab.get("packages", {}).items()
        if (value := settings.get("uploaded-prior-to")) is not None and _expired(value, threshold)
    }
    rules = {
        index
        for index, rule in enumerate(nab.get("package-rules", []))
        if (value := rule.get("uploaded-prior-to")) is not None and _expired(value, threshold)
    }
    return packages, rules


def _expired(value: str | datetime, threshold: datetime) -> bool:
    if isinstance(value, str) and value.startswith("P"):
        return False
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

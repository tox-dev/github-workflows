from __future__ import annotations

import tomllib
from datetime import datetime


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


def _expired(value: str, threshold: datetime) -> bool:
    if value.startswith("P"):
        return False
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"Nab package cutoff has no timezone: {value}")
    return timestamp <= threshold


__all__ = [
    "expired_cutoffs",
]

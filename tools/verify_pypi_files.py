"""Compare a complete local release with PyPI's Simple JSON listing."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import Version


class _SimpleFile(TypedDict):
    filename: str
    hashes: dict[str, str]
    yanked: NotRequired[bool | str]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("version")
    parser.add_argument("dist", type=Path)
    parser.add_argument("--wait-seconds", type=int, default=120)
    args = parser.parse_args()
    try:
        for path in verify_files(args.project, args.version, args.dist, args.wait_seconds):
            print(path)
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))


def verify_files(project: str, version: str, dist: Path, wait_seconds: int) -> list[Path]:
    """Check the local files against PyPI.

    :param project: Published project name.
    :param version: Published release version.
    :param dist: Directory containing every expected distribution.
    :param wait_seconds: Maximum time to wait for PyPI's listing.
    :returns: Local distribution paths for attestation verification.
    """
    if wait_seconds < 0 or not dist.is_dir():
        raise ValueError("release files require a directory and nonnegative wait")
    name = canonicalize_name(project, validate=True)
    release = Version(version)
    local: dict[str, str] = {}
    for path in dist.iterdir():
        if path.is_symlink() or not path.is_file() or path.name.startswith("."):
            raise ValueError(f"invalid distribution path: {path}")
        if _identity(path.name) != (name, release):
            raise ValueError(f"distribution belongs to another release: {path.name}")
        with path.open("rb") as stream:
            local[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    if not local:
        raise ValueError(f"distribution directory is empty: {dist}")
    deadline = time.monotonic() + wait_seconds
    while True:
        remote: dict[str, str] = {}
        try:
            files = _listing(name)
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise
            if (remaining := deadline - time.monotonic()) <= 0:
                raise
            time.sleep(min(2, remaining))
            continue
        except URLError as error:
            if not isinstance(error.reason, TimeoutError) or (remaining := deadline - time.monotonic()) <= 0:
                raise
            time.sleep(min(2, remaining))
            continue
        for file in files:
            if (identity := _identity(file["filename"])) is None:
                raise ValueError(f"PyPI has an unrecognized distribution filename: {file['filename']}")
            if identity != (name, release):
                continue
            filename = file["filename"]
            if filename in remote or file.get("yanked"):
                raise ValueError(f"duplicate or yanked PyPI file: {filename}")
            remote[filename] = file["hashes"]["sha256"]
        if extra := remote.keys() - local.keys():
            raise ValueError(f"PyPI has unexpected files: {', '.join(sorted(extra))}")
        if changed := {filename for filename in remote if remote[filename] != local[filename]}:
            raise ValueError(f"PyPI has different SHA256 digests: {', '.join(sorted(changed))}")
        if not (missing := local.keys() - remote.keys()):
            return [dist / filename for filename in sorted(local)]
        if (remaining := deadline - time.monotonic()) <= 0:
            raise ValueError(f"PyPI is missing files: {', '.join(sorted(missing))}")
        time.sleep(min(2, remaining))


def _identity(filename: str) -> tuple[str, Version] | None:
    try:
        return parse_wheel_filename(filename)[:2] if filename.endswith(".whl") else parse_sdist_filename(filename)
    except InvalidSdistFilename, InvalidWheelFilename:
        return None


def _listing(project: str) -> list[_SimpleFile]:
    request = Request(
        f"https://pypi.org/simple/{project}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json", "Cache-Control": "no-cache"},
    )
    try:
        with urlopen(request, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage]  # Fixed PyPI origin.
            payload = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return []
        raise
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise TypeError("PyPI returned an invalid Simple API response")
    if not isinstance((meta := payload.get("meta")), dict) or not str(meta.get("api-version", "")).startswith("1."):
        raise ValueError("unsupported PyPI Simple API version")
    for file in payload["files"]:
        if (
            not isinstance(file, dict)
            or not isinstance(file.get("filename"), str)
            or not isinstance((hashes := file.get("hashes")), dict)
            or not isinstance(hashes.get("sha256"), str)
        ):
            raise TypeError("PyPI returned an invalid file entry")
    return cast("list[_SimpleFile]", payload["files"])


if __name__ == "__main__":
    main()


__all__ = [
    "main",
    "verify_files",
]

"""Compare a complete local release with PyPI's Simple JSON listing."""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import time
from http.client import IncompleteRead
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi
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
    args = parser.parse_args()
    try:
        for path in verify_files(args.project, args.version, args.dist):
            print(path)
    except (OSError, TypeError, ValueError, IncompleteRead) as error:
        parser.error(str(error))


def verify_files(project: str, version: str, dist: Path) -> list[Path]:
    if not dist.is_dir():
        raise ValueError(f"distribution directory does not exist: {dist}")
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
    deadline = time.monotonic() + 120
    delay = 1
    while True:
        remote: dict[str, str] = {}
        try:
            files = _listing(name)
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                raise
            if deadline - time.monotonic() <= 0:
                raise
            files = []
        except TimeoutError, ConnectionError, URLError, IncompleteRead, ssl.SSLError, json.JSONDecodeError:
            if deadline - time.monotonic() <= 0:
                raise
            files = []
        for file in files:
            if (identity := _identity(file["filename"])) is None:
                prefix, separator, suffix = file["filename"].rpartition(f"-{release}")
                if (
                    separator
                    and (not suffix or suffix[0] in ".-_")
                    and not (
                        suffix.startswith(".")
                        and (
                            suffix[1:2].isdigit()
                            or (suffix.startswith(".post") and suffix[5:6].isdigit())
                            or (suffix.startswith(".dev") and suffix[4:5].isdigit())
                        )
                    )
                    and canonicalize_name(prefix) == name
                ):
                    raise ValueError(f"PyPI has an unrecognized distribution filename: {file['filename']}")
                continue
            if identity != (name, release):
                continue
            filename = file["filename"]
            if filename in remote or file.get("yanked", False) is not False:
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
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, 30)


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
        with urlopen(  # ruff: ignore[suspicious-url-open-usage]  # Fixed PyPI origin.
            request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())
        ) as response:
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

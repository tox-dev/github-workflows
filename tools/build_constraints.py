"""Export hashed build constraints from selected PEP 751 lock targets."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from packaging.markers import Environment, default_environment
from packaging.pylock import Pylock, PylockSelectError, PylockValidationError
from packaging.tags import Tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("lock", type=Path)
    parser.add_argument("--target-platform")
    parser.add_argument("--targets")
    args = parser.parse_args()
    try:
        with args.lock.open("rb") as stream:
            lock = Pylock.from_dict(tomllib.load(stream))
        targets = _target_environments(args.target_platform, args.targets) if args.targets else [None]
        selected_by_target = [_selected_build(lock, environment) for environment in targets]
        versions = [{name: version for name, (version, _) in selected.items()} for selected in selected_by_target]
        if any(other != versions[0] for other in versions[1:]):
            parser.error("build package versions differ across requested targets")
        selected = selected_by_target[0]
        for other in selected_by_target[1:]:
            for name, (_, hashes) in other.items():
                selected[name][1].update(hashes)
        args.output.write_text(
            "".join(
                f"{name}=={version} {' '.join(f'--hash=sha256:{digest}' for digest in sorted(hashes))}\n"
                for name, (version, hashes) in sorted(selected.items())
            ),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        PylockValidationError,
        PylockSelectError,
    ) as error:
        parser.error(str(error))


def _target_environments(platform: str, values: str) -> list[Environment]:
    platforms = {
        "linux_x86_64": ("linux", "Linux", "x86_64", "posix"),
        "linux_aarch64": ("linux", "Linux", "aarch64", "posix"),
        "macos_x86_64": ("darwin", "Darwin", "x86_64", "posix"),
        "macos_arm64": ("darwin", "Darwin", "arm64", "posix"),
        "windows_amd64": ("win32", "Windows", "AMD64", "nt"),
        "windows_arm64": ("win32", "Windows", "ARM64", "nt"),
    }
    if platform not in platforms:
        raise ValueError(f"unknown target platform: {platform}")
    environments = []
    for value in values.replace(",", " ").split():
        version_text, separator, implementation = value.partition(":")
        version = Version(version_text)
        if not separator or len(version.release) != 3 or implementation not in {"cpython", "pypy"}:
            raise ValueError(f"invalid target: {value}; expected full-version:cpython|pypy")
        system_platform, platform_system, machine, os_name = platforms[platform]
        environment = default_environment()
        environment.update(
            python_version=f"{version.major}.{version.minor}",
            python_full_version=str(version),
            implementation_version=str(version),
            implementation_name=implementation,
            platform_python_implementation="CPython" if implementation == "cpython" else "PyPy",
            sys_platform=system_platform,
            platform_system=platform_system,
            platform_machine=machine,
            os_name=os_name,
            platform_release="",
            platform_version="",
        )
        environments.append(environment)
    if not environments:
        raise ValueError("at least one target is required")
    return environments


def _selected_build(lock: Pylock, environment: Environment | None) -> dict[str, tuple[Version, set[str]]]:
    if "build" in (lock.dependency_groups or ()):
        groups = {"build"}
    elif lock.dependency_groups:
        return {}
    else:
        groups = set()
    # Artifact choice is left to the installer; constraints carry every locked hash.
    tags: list[Tag] | None = None
    if environment is not None:
        tags = sorted(
            {
                tag
                for package in lock.packages
                for wheel in (package.wheels if package.wheels is not None else ())
                for tag in parse_wheel_filename(wheel.filename)[3]
            },
            key=str,
        )
    selected: dict[str, tuple[Version, set[str]]] = {}
    for package, _ in lock.select(environment=environment, tags=tags, dependency_groups=groups):
        if package.version is None or package.index is None:
            raise ValueError(f"build dependency {package.name} must be an index version")
        name = canonicalize_name(package.name)
        hashes = {
            artifact.hashes["sha256"]
            for artifact in [*(package.wheels or ()), *((package.sdist,) if package.sdist else ())]
            if "sha256" in artifact.hashes
        }
        if not hashes:
            raise ValueError(f"build dependency {package.name} has no SHA256 hash")
        selected[name] = (package.version, hashes)
    return selected


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

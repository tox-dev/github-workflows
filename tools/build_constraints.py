"""Export hashed build constraints from selected PEP 751 lock targets."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from packaging.markers import Environment, default_environment
from packaging.pylock import Pylock, PylockSelectError, PylockValidationError
from packaging.requirements import Requirement
from packaging.tags import Tag
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("locks", nargs="+", type=Path)
    parser.add_argument("--shared-policy", type=Path)
    parser.add_argument("--target-platform")
    parser.add_argument("--targets")
    args = parser.parse_args()
    if bool(args.target_platform) != bool(args.targets):
        parser.error("target-platform and targets must be supplied together")
    if len(args.locks) > 2:
        parser.error("at most one shared and one caller lock are supported")
    if args.shared_policy and len(args.locks) != 2:
        parser.error("shared-policy requires a shared and caller lock")
    try:
        locks = []
        for path in args.locks:
            with path.open("rb") as stream:
                locks.append(Pylock.from_dict(tomllib.load(stream)))
        requirements = _shared_requirements(args.shared_policy) if args.shared_policy else {}
        targets = _target_environments(args.target_platform, args.targets) if args.targets else [None]
        selected_by_target = [_selected_build(locks, environment, requirements) for environment in targets]
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


def _shared_requirements(path: Path) -> dict[str, Requirement]:
    with path.open("rb") as stream:
        project = tomllib.load(stream)
    requirements = (Requirement(value) for value in project["dependency-groups"]["build"])
    return {canonicalize_name(requirement.name): requirement for requirement in requirements}


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


def _selected_build(
    locks: list[Pylock], environment: Environment | None, requirements: dict[str, Requirement]
) -> dict[str, tuple[Version, set[str]]]:
    selected: dict[str, tuple[Version, set[str]]] = {}
    for index, lock in enumerate(locks):
        if "build" not in (lock.dependency_groups or ()):
            if len(locks) == 2:
                continue
            if lock.dependency_groups:
                raise ValueError("custom lock has dependency groups but no build group")
            groups: set[str] = set()
        else:
            groups = {"build"}
        # Artifact choice is left to the installer; constraints carry every locked hash.
        tags: list[Tag] | None = None
        if environment is not None:
            tags = sorted(
                {
                    tag
                    for package in lock.packages
                    for wheel in package.wheels or ()
                    for tag in parse_wheel_filename(wheel.filename)[3]
                },
                key=str,
            )
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
            if (existing := selected.get(name)) is not None and existing[0] != package.version:
                if index != 1 or not (requirement := requirements.get(name)):
                    raise ValueError(f"conflicting build dependency versions for {name}")
                if package.version not in requirement.specifier:
                    raise ValueError(f"caller build dependency {name}=={package.version} violates {requirement}")
            elif existing is not None:
                hashes.update(existing[1])
            selected[name] = (package.version, hashes)
    return selected


if __name__ == "__main__":
    main()


__all__ = [
    "main",
]

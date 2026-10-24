from __future__ import annotations

import argparse
import json
import os
import re
import stat
import tempfile
from datetime import UTC, datetime, timedelta
from hashlib import file_digest
from pathlib import Path
from typing import Final, TypedDict, cast

import yaml
from yaml.error import Mark
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


class _Asset(TypedDict):
    name: str
    digest: str
    created_at: str
    updated_at: str


class _Release(TypedDict):
    tag_name: str
    published_at: str
    draft: bool
    prerelease: bool
    assets: list[_Asset]


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh a signed mise release pin")
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("releases", type=Path)
    select.add_argument("output", type=Path)
    update = commands.add_parser("update")
    update.add_argument("workflow", type=Path)
    update.add_argument("step_name")
    update.add_argument("version")
    update.add_argument("expected_sha256")
    update.add_argument("binary", type=Path)
    update.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "select":
            version, digest = _select_release(args.releases)
            _write_outputs(args.output, version=version, sha256=digest)
        else:
            changed = _update_pin(args.workflow, args.step_name, args.version, args.expected_sha256, args.binary)
            _write_outputs(args.output, changed=str(changed).lower(), version=args.version, sha256=args.expected_sha256)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        parser.error(str(error))


def _select_release(path: Path) -> tuple[str, str]:
    cutoff = datetime.now(UTC) - timedelta(days=7)
    version_pattern: Final[re.Pattern[str]] = re.compile(r"v(\d{4})\.(\d{1,2})\.(\d+)")
    releases = (cast(_Release, json.loads(line)) for line in path.read_text().splitlines())
    eligible: list[tuple[tuple[int, ...], _Release]] = []
    for release in releases:
        if release["draft"] or release["prerelease"] or not (version := version_pattern.fullmatch(release["tag_name"])):
            continue
        published = datetime.fromisoformat(release["published_at"])
        if published <= cutoff:
            eligible.append((tuple(map(int, version.groups())), release))
    if not eligible:
        raise ValueError("no stable mise release was published at least seven days ago")
    for _, release in sorted(eligible, key=lambda item: item[0], reverse=True):
        version = release["tag_name"][1:]
        assets = [asset for asset in release["assets"] if asset["name"] == f"mise-v{version}-linux-x64"]
        if len(assets) != 1 or not re.fullmatch(r"sha256:[a-f0-9]{64}", assets[0]["digest"]):
            raise ValueError(f"mise {version} has no unique Linux x64 executable digest")
        if all(datetime.fromisoformat(assets[0][key]) <= cutoff for key in ("created_at", "updated_at")):
            return version, assets[0]["digest"].removeprefix("sha256:")
    raise ValueError("no mise executable was uploaded and unchanged for at least seven days")


def _update_pin(workflow: Path, step_name: str, version: str, expected_sha256: str, binary: Path) -> bool:
    if workflow.is_absolute() or workflow.parts[:2] != (".github", "workflows") or len(workflow.parts) != 3:
        raise ValueError("workflow must be a file in .github/workflows")
    if workflow.suffix not in {".yaml", ".yml"} or workflow.is_symlink():
        raise ValueError("workflow must be a regular YAML file")
    if not re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", version):
        raise ValueError("invalid mise version")
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("invalid mise digest")
    if binary.is_symlink() or not binary.is_file() or binary.with_name("mise-version").read_text().strip() != version:
        raise ValueError("mise-action did not install the selected version")
    with binary.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != expected_sha256:
            raise ValueError("verified mise binary differs from the GitHub release asset digest")
    source = workflow.read_text()
    root = yaml.compose(source)
    if not isinstance(root, MappingNode):
        raise TypeError("workflow needs a jobs mapping")
    jobs = _value(root, "jobs")
    if not isinstance(jobs, MappingNode):
        raise TypeError("workflow needs a jobs mapping")
    names = [name.value for name, _ in jobs.value if isinstance(name, ScalarNode)]
    if len(names) != len(set(names)):
        raise ValueError("duplicate YAML job name")
    matches = [
        step
        for _, job in jobs.value
        if isinstance(job, MappingNode) and isinstance(steps := _value(job, "steps"), SequenceNode)
        for step in steps.value
        if isinstance(step, MappingNode)
        and isinstance(name := _value(step, "name"), ScalarNode)
        and name.value == step_name
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one mise step named {step_name!r}; found {len(matches)}")
    step = matches[0]
    uses = _value(step, "uses")
    if not isinstance(uses, ScalarNode) or not re.fullmatch(r"jdx/mise-action@[a-f0-9]{40}", uses.value):
        raise ValueError("selected step must use one SHA-pinned jdx/mise-action")
    inputs = _value(step, "with")
    if not isinstance(inputs, MappingNode):
        raise TypeError("selected step must contain one with mapping")
    values = {key: _value(inputs, key) for key in ("version", "sha256")}
    step_start, step_end = _span(step)
    if any(
        not (step_start <= _span(node)[0] < _span(node)[1] <= step_end)
        for node in (inputs, *values.values())
        if node is not None
    ):
        raise ValueError("selected mise step uses YAML aliases outside its own mapping")
    if any(_occurrences(root, node) != 1 for node in (inputs, *values.values()) if node is not None):
        raise ValueError("selected mise inputs are aliased elsewhere in the workflow")
    if not all(
        isinstance(node, ScalarNode) and node.style in (None, "'", '"') and re.fullmatch(pattern, node.value)
        for (key, pattern), node in zip(
            (("version", r"\d{4}\.\d{1,2}\.\d+"), ("sha256", r"[a-f0-9]{64}")), values.values(), strict=True
        )
    ):
        raise ValueError("selected mise step needs one literal version and sha256")
    current = cast(ScalarNode, values["version"]).value
    if tuple(map(int, current.split("."))) > tuple(map(int, version.split("."))):
        raise ValueError(f"selected mise {version} is older than the current pin {current}")
    updated = source
    for key, value in sorted(
        (("version", version), ("sha256", expected_sha256)),
        key=lambda item: _span(cast(ScalarNode, values[item[0]]))[0],
        reverse=True,
    ):
        node = cast(ScalarNode, values[key])
        literal = f"{node.style}{value}{node.style}" if node.style else value
        start, end = _span(node)
        updated = f"{updated[:start]}{literal}{updated[end:]}"
    if updated == source:
        return False
    descriptor, name = tempfile.mkstemp(dir=workflow.parent, prefix=f".{workflow.name}.")
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(updated)
        os.chmod(name, stat.S_IMODE(workflow.stat().st_mode))
        os.replace(name, workflow)
    finally:
        Path(name).unlink(missing_ok=True)
    return True


def _value(mapping: MappingNode, key: str) -> Node | None:
    matches = [value for name, value in mapping.value if isinstance(name, ScalarNode) and name.value == key]
    if len(matches) > 1:
        raise ValueError(f"duplicate YAML key: {key}")
    return cast(Node, matches[0]) if matches else None


def _span(node: Node) -> tuple[int, int]:
    return cast(Mark, node.start_mark).index, cast(Mark, node.end_mark).index


def _occurrences(root: Node, target: Node, ancestors: frozenset[int] = frozenset()) -> int:
    count = int(root is target)
    if id(root) in ancestors:
        return count
    if isinstance(root, MappingNode):
        children = (node for pair in root.value for node in pair)
    elif isinstance(root, SequenceNode):
        children = iter(root.value)
    else:
        return count
    return count + sum(_occurrences(node, target, ancestors | {id(root)}) for node in children)


def _write_outputs(path: Path, **values: str) -> None:
    with path.open("a") as stream:
        for name, value in values.items():
            stream.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()


__all__ = ["main"]

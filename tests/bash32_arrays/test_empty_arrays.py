import re
from collections.abc import Iterator
from pathlib import Path

from conftest import WORKFLOWS, at, load_yaml, mapping, step_list, text


def test_unguarded_array_expansions_are_provably_non_empty() -> None:
    # Bash 3.2, the /bin/bash of macOS runners, aborts on "${arr[@]}" of an empty array under set -u. Bash 5 does
    # not, so CI only sees this through the scan. Each allowed name is an array that cannot be empty where it expands.
    expected = {
        (".github/workflows/check.yaml", "options"): "starts with --exclude-newer",
        ("check-nab-exceptions/action.yml", "files"): "starts with pyproject.toml",
        ("install-locked-tools/action.yml", "groups"): "filled only when the selection found a group",
        ("prepare-towncrier/action.yml", "args"): "set to three options before the call",
        ("publish-github-release/action.yml", "request"): "starts with two -f pairs",
        ("publish-post-release-pr/action.yml", "paths"): "checked non-empty before any other use",
        ("refresh-release-lock/action.yml", "paths"): "starts with pylock.toml",
        ("refresh-release-lock/action.yml", "requirements"): "set to one requirement in every mode",
        ("refresh-release-lock/action.yml", "selected_groups"): "used only inside the non-empty check",
        ("render-release-notes/action.yml", "args"): "starts with three options",
        ("stage-jetbrains-marketplace/action.yml", "args"): "starts with the marketplace subcommand",
    }
    found = {(path, name) for path, script in _run_scripts() for name in _unguarded_names(script)}

    assert found == set(expected)


def _run_scripts() -> Iterator[tuple[str, str]]:
    root = Path(__file__).resolve().parents[2]
    for action in sorted(root.glob("*/action.yml")):
        for step in step_list(at(load_yaml(action), "runs", "steps")):
            if "run" in step:
                yield action.relative_to(root).as_posix(), text(step["run"])
    for workflow in sorted(WORKFLOWS.glob("*.y*ml")):
        for job_value in mapping(at(load_yaml(workflow), "jobs")).values():
            job = mapping(job_value)
            if "${{" in text(job.get("runs-on", "")) and "steps" in job:
                for step in step_list(job["steps"]):
                    if "run" in step:
                        yield workflow.relative_to(root).as_posix(), text(step["run"])


def _unguarded_names(script: str) -> set[str]:
    without_guards = re.sub(r'\$\{(\w+)\[[@*]\]\+"\$\{\1\[[@*]\]\}"\}', "", script)
    return {match.group(1) for match in re.finditer(r"\$\{(\w+)\[[@*]\]\}", without_guards)}

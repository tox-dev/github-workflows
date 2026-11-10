import dataclasses
import os
import subprocess
from pathlib import Path
from typing import Final

import pytest
from conftest import WORKFLOWS, JsonObject, at, load_yaml, mapping, run, run_workflow_step, step, steps, text
from pytest import ParameterSet

_WORKFLOW: Final[str] = "publish-pre-commit-mirror.yaml"
_VALUES: Final[dict[str, str]] = {
    "github.token": "token",
    "inputs.package-name": "pyproject-fmt",
    "inputs.files-regex": r"(^|/)pyproject\.toml$",
    "inputs.exclude-newer": "7 days",
    "inputs.exclude-newer-package": "",
}


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _Scenario:
    upstream: str
    statuses: str
    rewrite: bool
    tags: tuple[str, ...]


_ONE_VERSION: Final[_Scenario] = _Scenario(upstream="1.0.0 1.0.1", statuses="0", rewrite=False, tags=("v1.0.1",))
_SCENARIOS: Final[list[ParameterSet]] = [
    pytest.param(_ONE_VERSION, id="one-version"),
    pytest.param(
        _Scenario(upstream="1.0.0 1.0.1", statuses="1 0", rewrite=True, tags=("v1.0.1",)),
        id="one-version-formatted",
    ),
    pytest.param(
        _Scenario(upstream="1.0.0 1.0.1 1.0.2", statuses="0", rewrite=False, tags=("v1.0.1", "v1.0.2")),
        id="two-versions",
    ),
    pytest.param(
        _Scenario(upstream="1.0.0 1.0.1 1.0.2", statuses="1 0", rewrite=True, tags=("v1.0.1", "v1.0.2")),
        id="two-versions-formatted",
    ),
]


@pytest.fixture
def workflow() -> JsonObject:
    return load_yaml(WORKFLOWS / _WORKFLOW)


def test_steps_run_in_order(workflow: JsonObject) -> None:
    assert [item["name"] for item in steps(workflow, "mirror")] == [
        "📥 Check out repository",
        "📦 Install uv",
        "⚙️ Configure Git identity",
        "🪞 Generate mirror",
        "📝 Update README with current version",
        "💅 Format generated files",
        "⚙️ Configure Git credentials",
        "🔄 Commit mirror changes",
        "🚀 Push mirror commits and tags",
        "🎉 Create GitHub releases",
    ]


@pytest.mark.parametrize(
    ("name", "condition"),
    [
        pytest.param(
            "📝 Update README with current version",
            "${{ steps.generate.outputs.mirrored == 'true' }}",
            id="readme",
        ),
        pytest.param("💅 Format generated files", "${{ steps.generate.outputs.mirrored == 'true' }}", id="format"),
        pytest.param("🔄 Commit mirror changes", "${{ steps.generate.outputs.mirrored == 'true' }}", id="commit"),
        pytest.param(
            "🚀 Push mirror commits and tags",
            "${{ github.ref == 'refs/heads/main' && steps.commit.outputs.tags != '' }}",
            id="push",
        ),
        pytest.param(
            "🎉 Create GitHub releases",
            "${{ github.ref == 'refs/heads/main' && steps.commit.outputs.tags != '' }}",
            id="release",
        ),
    ],
)
def test_step_runs_only_when_its_precondition_holds(workflow: JsonObject, name: str, condition: str) -> None:
    assert step(workflow, "mirror", name)["if"] == condition


def test_push_is_atomic_and_never_forces(workflow: JsonObject) -> None:
    push = text(step(workflow, "mirror", "🚀 Push mirror commits and tags")["run"])
    assert "--atomic" in push
    assert "--force" not in push
    assert " -f " not in push


def test_checkout_does_not_persist_credentials(workflow: JsonObject) -> None:
    checkout = step(workflow, "mirror", "📥 Check out repository")
    assert checkout["with"] == {"persist-credentials": "false"}
    workflow_text = (WORKFLOWS / _WORKFLOW).read_text()
    assert "set-url" not in workflow_text
    assert "x-access-token" not in workflow_text


def test_tools_are_pinned() -> None:
    workflow_text = (WORKFLOWS / _WORKFLOW).read_text()
    assert "pre-commit-mirror-maker==1.14.0" in workflow_text
    assert "prek==0.5.5" in workflow_text
    assert 'version: "0.13.7"' in workflow_text


@pytest.mark.parametrize(
    "forbidden",
    [
        pytest.param("${{", id="expressions"),
        pytest.param("|| true", id="masked-failures"),
    ],
)
def test_run_blocks_avoid_forbidden_constructs(workflow: JsonObject, forbidden: str) -> None:
    offenders = [
        item.get("name")
        for job in mapping(at(workflow, "jobs"))
        for item in steps(workflow, job)
        if forbidden in text(item.get("run", ""))
    ]
    assert offenders == []


def test_concurrency_queues_mirror_runs(workflow: JsonObject) -> None:
    assert workflow["concurrency"] == {
        "group": "pre-commit-mirror-${{ github.repository }}",
        "cancel-in-progress": "false",
    }


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    remote = tmp_path / "origin.git"
    run(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    return remote


@pytest.fixture
def clone(tmp_path: Path, origin: Path) -> Path:
    clone = tmp_path / "clone"
    run(tmp_path, "git", "init", "-q", "-b", "main", str(clone))
    (clone / ".version").write_text("1.0.0\n")
    (clone / "README.md").write_text('rev: "v1.0.0"\n')
    run(clone, "git", "add", ".")
    _commit(clone, "Initial mirror")
    run(clone, "git", "remote", "add", "origin", str(origin))
    run(clone, "git", "push", "-q", "origin", "main")
    return clone


def _commit(clone: Path, message: str) -> None:
    run(
        clone,
        "git",
        "-c",
        "user.name=Mirror test",
        "-c",
        "user.email=mirror@example.org",
        "commit",
        "-q",
        "-a",
        "-m",
        message,
    )


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uvx = bin_dir / "uvx"
    uvx.write_text(
        """\
#!/usr/bin/env bash
case " $* " in
*pre-commit-mirror-maker*)
  current=$(cat .version)
  applying=false
  for version in $MIRROR_UPSTREAM; do
    if [[ "$applying" == false ]]; then
      if [[ "$version" == "$current" ]]; then applying=true; fi
      continue
    fi
    echo "$version" >.version
    git add .
    git commit -q -m "Mirror: $version"
    git tag "v$version"
  done
  ;;
*)
  count=$(cat "$RUNNER_TEMP/prek-count" 2>/dev/null || echo 0)
  echo $((count + 1)) >"$RUNNER_TEMP/prek-count"
  if [[ "$count" == 0 && -n "${PREK_REWRITE:-}" ]]; then echo formatted >>"$PREK_REWRITE"; fi
  read -r -a statuses <<<"$PREK_STATUSES"
  exit "${statuses[count]}"
  ;;
esac
"""
    )
    gh = bin_dir / "gh"
    gh.write_text('#!/usr/bin/env bash\necho "$*" >>"$RUNNER_TEMP/gh.log"\n')
    for script in (uvx, gh):
        script.chmod(0o755)
    return bin_dir


@pytest.mark.parametrize(
    ("statuses", "accepted", "invocations"),
    [
        pytest.param("0", True, 1, id="clean-tree"),
        pytest.param("1 0", True, 2, id="rewritten-then-clean"),
        pytest.param("1 1", False, 2, id="rewritten-then-failing"),
        pytest.param("2", False, 1, id="hook-crashed"),
    ],
)
def test_format_step_accepts_only_a_clean_second_pass(
    tmp_path: Path,
    tools: Path,
    statuses: str,
    accepted: bool,
    invocations: int,
) -> None:
    result, _ = _step(tmp_path, tmp_path, tools, "💅 Format generated files", PREK_STATUSES=statuses)
    assert (result.returncode == 0) is accepted, result.stderr
    assert (tmp_path / "prek-count").read_text().strip() == str(invocations)


def test_no_new_version_is_a_noop(tmp_path: Path, clone: Path, tools: Path) -> None:
    head = _rev(clone, "HEAD")
    _ok(clone, tmp_path / "runner", tools, "⚙️ Configure Git identity")
    outputs = _ok(clone, tmp_path / "runner", tools, "🪞 Generate mirror", MIRROR_UPSTREAM="1.0.0")
    assert outputs == {"base": head, "mirrored": "false"}


def _rev(directory: Path, revision: str) -> str:
    return run(directory, "git", "rev-parse", revision).stdout.strip()


def _ok(clone: Path, runner: Path, tools: Path, name: str, **env: str) -> dict[str, str]:
    result, outputs = _step(clone, runner, tools, name, **env)
    assert result.returncode == 0, result.stderr
    return outputs


def _step(
    clone: Path,
    runner: Path,
    tools: Path,
    name: str,
    **env: str,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    runner.mkdir(exist_ok=True)
    return run_workflow_step(
        _WORKFLOW,
        "mirror",
        name,
        cwd=clone,
        runner_temp=runner,
        values=_VALUES,
        env={"PATH": f"{tools}:{os.environ['PATH']}"} | env,
    )


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_commit_outputs_every_new_tag(tmp_path: Path, clone: Path, tools: Path, scenario: _Scenario) -> None:
    result, outputs = _commit_mirror(clone, tmp_path / "runner", tools, scenario)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tags": " ".join(scenario.tags)}


def _commit_mirror(
    clone: Path,
    runner: Path,
    tools: Path,
    scenario: _Scenario,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    stub = {
        "MIRROR_UPSTREAM": scenario.upstream,
        "PREK_STATUSES": scenario.statuses,
        "PREK_REWRITE": "README.md" if scenario.rewrite else "",
    }
    _ok(clone, runner, tools, "⚙️ Configure Git identity")
    generated = _ok(clone, runner, tools, "🪞 Generate mirror", **stub)
    _ok(clone, runner, tools, "📝 Update README with current version", **stub)
    _ok(clone, runner, tools, "💅 Format generated files", **stub)
    return _step(clone, runner, tools, "🔄 Commit mirror changes", BASE=generated["base"], **stub)


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_commit_keeps_one_commit_per_version(tmp_path: Path, clone: Path, tools: Path, scenario: _Scenario) -> None:
    base = _rev(clone, "HEAD")
    _commit_mirror(clone, tmp_path / "runner", tools, scenario)
    assert _log(clone, base, "%s") == [f"Mirror: {tag.removeprefix('v')}" for tag in scenario.tags]


def _log(clone: Path, base: str, pretty: str) -> list[str]:
    return run(clone, "git", "log", "--reverse", f"--format={pretty}", f"{base}..HEAD").stdout.splitlines()


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_commit_is_authored_by_the_bot(tmp_path: Path, clone: Path, tools: Path, scenario: _Scenario) -> None:
    base = _rev(clone, "HEAD")
    _commit_mirror(clone, tmp_path / "runner", tools, scenario)
    assert set(_log(clone, base, "%an")) == {"Github Actions"}


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_newest_tag_points_at_the_final_tree(tmp_path: Path, clone: Path, tools: Path, scenario: _Scenario) -> None:
    _commit_mirror(clone, tmp_path / "runner", tools, scenario)
    assert _rev(clone, f"{scenario.tags[-1]}^{{tree}}") == _rev(clone, "HEAD^{tree}")


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_formatting_lands_in_the_newest_commit(tmp_path: Path, clone: Path, tools: Path, scenario: _Scenario) -> None:
    _commit_mirror(clone, tmp_path / "runner", tools, scenario)
    readme = run(clone, "git", "show", "HEAD:README.md").stdout
    assert ("formatted" in readme) is scenario.rewrite


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_published_tags_reach_origin_with_the_branch(
    tmp_path: Path,
    clone: Path,
    origin: Path,
    tools: Path,
    scenario: _Scenario,
) -> None:
    _publish(clone, tmp_path / "runner", tools, scenario)
    expected = {"refs/heads/main": _rev(clone, "HEAD")}
    expected |= {f"refs/tags/{tag}": _rev(clone, f"{tag}^{{commit}}") for tag in scenario.tags}
    assert _remote_refs(origin) == expected


def _remote_refs(origin: Path) -> dict[str, str]:
    lines = run(origin, "git", "for-each-ref", "--format=%(refname) %(objectname)").stdout.splitlines()
    return {ref: sha for ref, sha in (line.split() for line in lines)}


def _publish(clone: Path, runner: Path, tools: Path, scenario: _Scenario) -> None:
    result, outputs = _commit_mirror(clone, runner, tools, scenario)
    assert result.returncode == 0, result.stderr
    _ok(clone, runner, tools, "🚀 Push mirror commits and tags", NEW_TAGS=outputs["tags"])
    _ok(clone, runner, tools, "🎉 Create GitHub releases", NEW_TAGS=outputs["tags"])


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_each_new_tag_gets_a_release(tmp_path: Path, clone: Path, tools: Path, scenario: _Scenario) -> None:
    _publish(clone, tmp_path / "runner", tools, scenario)
    releases = (tmp_path / "runner" / "gh.log").read_text().splitlines()
    assert releases == [f"release create {tag} --generate-notes" for tag in scenario.tags]


def test_identical_published_tag_is_skipped(tmp_path: Path, clone: Path, tools: Path) -> None:
    result, _ = _commit_mirror(clone, tmp_path / "first", tools, _ONE_VERSION)
    assert result.returncode == 0, result.stderr
    run(clone, "git", "push", "-q", "origin", "refs/tags/v1.0.1")
    run(clone, "git", "reset", "-q", "--hard", "origin/main")
    run(clone, "git", "tag", "-d", "v1.0.1")
    result, outputs = _commit_mirror(clone, tmp_path / "second", tools, _ONE_VERSION)
    assert result.returncode == 0, result.stderr
    assert outputs == {"tags": ""}
    assert "v1.0.1 is already published with identical mirror content" in result.stdout


def test_different_published_tag_fails(tmp_path: Path, clone: Path, tools: Path) -> None:
    run(clone, "git", "checkout", "-q", "-b", "diverged")
    (clone / "README.md").write_text("diverged\n")
    _commit(clone, "Diverge")
    run(clone, "git", "tag", "v1.0.1")
    run(clone, "git", "push", "-q", "origin", "refs/tags/v1.0.1")
    run(clone, "git", "tag", "-d", "v1.0.1")
    run(clone, "git", "checkout", "-q", "main")
    result, _ = _commit_mirror(clone, tmp_path / "runner", tools, _ONE_VERSION)
    assert result.returncode == 1
    assert "v1.0.1 is published with a different mirror tree" in result.stderr


@pytest.mark.parametrize(
    ("readme", "expected"),
    [
        pytest.param('  rev: "v1.0.0"\n', '  rev: "v2.0.0"\n', id="quoted"),
        pytest.param("    rev: v1.0.0\n", "    rev: v2.0.0\n", id="unquoted"),
        pytest.param("rev: 1.0.0\n", "rev: v2.0.0\n", id="no-v-prefix"),
    ],
)
def test_readme_rev_keeps_its_quoting(tmp_path: Path, readme: str, expected: str) -> None:
    (tmp_path / ".version").write_text("2.0.0\n")
    (tmp_path / "README.md").write_text(readme)

    result, _ = run_workflow_step(
        _WORKFLOW,
        "mirror",
        "📝 Update README with current version",
        cwd=tmp_path,
        runner_temp=tmp_path,
        values={},
        env={},
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "README.md").read_text() == expected


def test_readme_without_rev_line_fails(tmp_path: Path) -> None:
    (tmp_path / ".version").write_text("2.0.0\n")
    (tmp_path / "README.md").write_text("no hook snippet\n")

    result, _ = run_workflow_step(
        _WORKFLOW,
        "mirror",
        "📝 Update README with current version",
        cwd=tmp_path,
        runner_temp=tmp_path,
        values={},
        env={},
    )

    assert result.returncode != 0
    assert "README.md has no rev: line to update to v2.0.0" in result.stderr

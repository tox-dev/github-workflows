from __future__ import annotations

import os
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path
from textwrap import dedent

import pytest
import yaml


@pytest.mark.parametrize(
    ("requirement", "versions", "mode", "include_group", "error"),
    [
        pytest.param("uv>=0.13.5", ("0.13.5",), "widen", True, "exact uv pin", id="non-exact-start"),
        pytest.param('uv==0.13.5", "other', ("0.13.5",), "widen", True, "one uv requirement", id="extra-requirement"),
        pytest.param("uv==0.13.5", ("0.13.5",), "pin", True, "temporary uv range", id="pin-without-widen"),
        pytest.param("uv>=0.13.5", ("0.13.5",), "pin", False, "omits release-resolver", id="missing-group"),
        pytest.param("uv>=0.13.5", ("0.13.5", "0.13.6"), "pin", True, "one uv resolver", id="ambiguous-candidate"),
        pytest.param("uv>=0.13.5", (), "pin", True, "one uv resolver", id="missing-candidate"),
    ],
)
def test_resolver_upgrade_rejects_invalid_state(
    tmp_path: Path, requirement: str, versions: tuple[str, ...], mode: str, include_group: bool, error: str
) -> None:
    source = Path(__file__).resolve().parents[2] / "tools/refresh_uv_resolver.py"
    project = tmp_path / "pyproject.toml"
    project.write_text(f'[dependency-groups]\nrelease-resolver = ["{requirement}"]\n')
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        ('dependency-groups = ["release-resolver"]\n' if include_group else "dependency-groups = []\n")
        + ("".join(_uv_package(version) for version in versions) if versions else "packages = []\n")
    )

    result = subprocess.run(
        [sys.executable, str(source), mode, str(project), str(lock)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert error in result.stderr


def test_resolver_widen_starts_at_the_current_pin(tmp_path: Path) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text('[dependency-groups]\nrelease-resolver = ["uv==0.13.6"]\n')
    lock = tmp_path / "pylock.toml"
    lock.write_text('dependency-groups = ["release-resolver"]\n' + _uv_package("0.13.6"))

    result = _resolver(tmp_path, "widen")

    assert result.returncode == 0, result.stderr
    assert tomllib.loads(project.read_text())["dependency-groups"]["release-resolver"] == ["uv>=0.13.6"]


def test_resolver_pin_ignores_uv_from_other_groups(tmp_path: Path) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text('[dependency-groups]\nrelease-resolver = ["uv>=0.13.5"]\n')
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["release-resolver", "test"]\n'
        + _uv_package("0.13.6")
        + "[[packages]]\nname = 'uv'\nversion = '0.14.0'\nmarker = '\"test\" in dependency_groups'\n"
    )

    result = _resolver(tmp_path, "pin")

    assert result.returncode == 0, result.stderr
    assert tomllib.loads(project.read_text())["dependency-groups"]["release-resolver"] == ["uv==0.13.6"]


def _resolver(root: Path, mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "tools/refresh_uv_resolver.py"),
            mode,
            str(root / "pyproject.toml"),
            str(root / "pylock.toml"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("repository", "pin", "locked", "accepted"),
    [
        pytest.param("tox-dev/github-workflows", "uv==0.13.6", "0.13.6", True, id="shared-resolver"),
        pytest.param("tox-dev/github-workflows", "uv==0.13.6", "0.13.5", False, id="lock-mismatch"),
        pytest.param("tox-dev/github-workflows", "uv>=0.13.6", "0.13.6", False, id="range"),
        pytest.param("tox-dev/other", "uv==0.13.6", "0.13.6", False, id="other-repository"),
    ],
)
def test_writer_accepts_only_the_locked_resolver_pin(
    tmp_path: Path, repository: str, pin: str, locked: str, accepted: bool
) -> None:
    project = tmp_path / "pyproject.toml"
    project.write_text('[dependency-groups]\nrelease-resolver = ["uv==0.13.5"]\n[tool.release-creator.locks]\n')
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "Pin"],
        cwd=tmp_path,
        check=True,
    )
    project.write_text(project.read_text().replace("uv==0.13.5", pin))
    (tmp_path / "pylock.toml").write_text('dependency-groups = ["release-resolver"]\n' + _uv_package(locked))

    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "tools/verify_cutoff_patch.py")],
        cwd=tmp_path,
        env=os.environ | {"GITHUB_REPOSITORY": repository},
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode == 0) is accepted, result.stderr


def test_resolver_upgrade_import_has_no_side_effect() -> None:
    source = Path(__file__).resolve().parents[2] / "tools/refresh_uv_resolver.py"

    assert runpy.run_path(str(source), run_name="imported")["__all__"] == ["main"]


def test_weekly_resolver_upgrade_is_opt_in() -> None:
    source = Path(__file__).resolve().parents[2]
    caller = yaml.safe_load((source / ".github/workflows/update-tools.yaml").read_text())
    reusable = yaml.safe_load((source / ".github/workflows/upgrade-release-tools.yaml").read_text())
    action = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())

    assert caller["jobs"]["update"]["with"]["upgrade-resolver"] is True
    refresh = next(
        step for step in reusable["jobs"]["generate-lock"]["steps"] if step.get("uses") == "$/refresh-release-lock"
    )
    assert refresh["with"]["upgrade-resolver"] == "${{ inputs.upgrade-resolver }}"
    assert action["inputs"]["upgrade-resolver"]["default"] == "false"


def test_resolver_upgrade_uses_candidate_to_regenerate_lock(tmp_path: Path, action_scripts: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    steps = yaml.safe_load((source / "refresh-release-lock/action.yml").read_text())["runs"]["steps"]
    names = [step.get("name", "") for step in steps]
    old_index = names.index("Resolve all project groups and extras")
    new_index = names.index("Resolve with the updated uv resolver")
    assert names.index("Widen the shared uv pin") < old_index
    assert old_index < names.index("Pin the updated uv resolver") < new_index
    installer = steps[new_index - 1]
    assert installer["uses"] == "$/install-locked-tools"
    assert installer["with"]["groups"] == "release-resolver"
    assert installer["with"].get("lock-source", "caller") == "caller"

    project = tmp_path / "pyproject.toml"
    project.write_text('[dependency-groups]\nrelease-resolver = ["uv==0.13.5"]\n')
    (tmp_path / "pylock.toml").write_text('dependency-groups = ["release-resolver"]\n' + _uv_package("0.13.5"))
    (tmp_path / "candidate.toml").write_text(
        'lock-version = "old-output"\ndependency-groups = ["release-resolver"]\n' + _uv_package("0.13.6")
    )
    (tmp_path / "final.toml").write_text(
        'lock-version = "new-output"\ndependency-groups = ["release-resolver"]\n' + _uv_package("0.13.6")
    )
    _fake_uv(tmp_path / "release-resolver/bin/uv", "candidate.toml")
    _fake_uv(tmp_path / "updated-release-resolver/bin/uv", "final.toml")
    tool = source / "tools/refresh_uv_resolver.py"
    for mode in ("widen", "pin"):
        if mode == "pin":
            _run_step(action_scripts, old_index, tmp_path)
        result = subprocess.run(
            [sys.executable, str(tool), mode, str(project), str(tmp_path / "pylock.toml")],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    _run_step(action_scripts, new_index, tmp_path)

    assert tomllib.loads(project.read_text())["dependency-groups"]["release-resolver"] == ["uv==0.13.6"]
    assert tomllib.loads((tmp_path / "pylock.toml").read_text())["lock-version"] == "new-output"
    assert (tmp_path / "checked-with-candidate").exists()


def _uv_package(version: str) -> str:
    return f"[[packages]]\nname = 'uv'\nversion = '{version}'\nmarker = '\"release-resolver\" in dependency_groups'\n"


def _fake_uv(path: Path, lock: str) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        dedent(
            f"""\
            #!{sys.executable}
            import pathlib
            import shutil
            import sys

            root = pathlib.Path.cwd()
            if "--check" in sys.argv:
                assert (root / "pylock.toml").read_bytes() == (root / "{lock}").read_bytes()
                (root / "checked-with-candidate").touch()
            else:
                shutil.copyfile(root / "{lock}", root / "pylock.toml")
            """
        )
    )
    path.chmod(0o755)


def _run_step(action_scripts: Path, index: int, root: Path) -> None:
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", str(action_scripts / f"refresh-release-lock-{index}.sh")],
        cwd=root,
        env=os.environ | {"MODE": "refresh", "KEEP_UV_LOCK": "false", "RUNNER_TEMP": str(root)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

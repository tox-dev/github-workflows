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

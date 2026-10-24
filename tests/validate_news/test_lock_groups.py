from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest


def test_lock_groups_reads_recorded_selection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\nrelease = []\nrelease-news = []\nrelease-check = []\n"
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        '[tool.nab]\ncommand-line = ["nab", "lock", "--groups", "release-news", "release-check", '
        '"--output", "pylock.toml"]\n'
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "release-news release-check\n"


@pytest.mark.parametrize(
    ("command", "message"),
    [
        pytest.param('["nab", "lock", "--output", "pylock.toml"]', "cannot read lock groups", id="missing-flag"),
        pytest.param('"nab lock --groups release-news"', "must be a list of strings", id="string-command"),
        pytest.param('["nab", 42]', "must be a list of strings", id="non-string-argument"),
        pytest.param(
            '["nab", "lock", "--groups", "--output", "pylock.toml"]',
            "Nab lock records no selected groups",
            id="empty-groups",
        ),
    ],
)
def test_lock_groups_rejects_missing_selection(tmp_path: Path, command: str, message: str) -> None:
    lock = tmp_path / "pylock.toml"
    lock.write_text(f"[tool.nab]\ncommand-line = {command}\n")

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_lock_groups_import_has_no_cli_side_effect(capsys: pytest.CaptureFixture[str]) -> None:
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), run_name="lock_groups")

    assert capsys.readouterr() == ("", "")


def test_lock_groups_reads_full_project_selection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project.optional-dependencies]\nweb = []\n[dependency-groups]\nrelease-news = []\ntest = []\n"
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["project-runtime", "release-news", "test"]\nextras = ["web"]\ndefault-groups = []\n'
        "[tool.nab]\ncreated-at = 2026-10-24T00:00:00Z\n"
        "[tool.release-creator]\ncreated-at = 2026-10-24T00:00:00Z\n"
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout) == (0, "release-news\n")


def test_lock_groups_includes_workspace_members_and_exclusions(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["packages/*"]\nexclude = ["packages/unused"]\n'
        "[dependency-groups]\nrelease-news = []\n"
    )
    for name, groups, extras in (
        ("included", "test = []\nrelease-package = []\n", "web = []\n"),
        ("unused", "stale = []\n", "stale = []\n"),
    ):
        member = tmp_path / "packages" / name
        member.mkdir(parents=True)
        (member / "pyproject.toml").write_text(
            f"[dependency-groups]\n{groups}[project.optional-dependencies]\n{extras}"
        )
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["project-runtime", "release-news", "release-package", "test"]\n'
        'extras = ["web"]\ndefault-groups = []\n[tool.release-creator]\n'
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout) == (0, "release-news release-package\n")


def test_lock_groups_accepts_declared_workspace_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "bare"\n[tool.uv.workspace]\nmembers = ["packages/*"]\n'
        "[dependency-groups]\nrelease-news = []\n"
    )
    for name in ("meta", "other"):
        member = tmp_path / "packages" / name
        member.mkdir(parents=True)
        (member / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\n[dependency-groups]\nrelease-{name} = []\n'
            + ("[tool.uv.sources]\nbare = { workspace = true }\n" if name == "meta" else "")
        )
    (tmp_path / "packages" / "notes.txt").write_text("not a project")
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["project-runtime", "release-news", "release-meta", "release-other"]\n'
        "extras = []\ndefault-groups = []\n[tool.release-creator]\n"
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout) == (0, "release-news release-meta release-other\n")


@pytest.mark.parametrize(
    ("groups", "extras", "message"),
    [
        pytest.param('"release-news"', "[]", "invalid dependency groups", id="groups-not-list"),
        pytest.param('["release-news", 1]', "[]", "invalid dependency groups", id="non-string-group"),
        pytest.param('["project-runtime", "release-news"]', '"web"', "invalid extras", id="extras-not-list"),
        pytest.param('["project-runtime", "release-news"]', "[1]", "invalid extras", id="non-string-extra"),
        pytest.param(
            '["project-runtime", "release-news"]',
            '["web", "unknown"]',
            "invalid or undeclared extras",
            id="undeclared-extra",
        ),
        pytest.param(
            '["project-runtime", "release-news"]',
            '["web", "web"]',
            "invalid or undeclared extras",
            id="duplicate-extra",
        ),
    ],
)
def test_lock_groups_rejects_malformed_project_selections(
    tmp_path: Path, groups: str, extras: str, message: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[dependency-groups]\nrelease-news = []\n[project.optional-dependencies]\nweb = []\n"
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(f"dependency-groups = {groups}\nextras = {extras}\ndefault-groups = []\n[tool.release-creator]\n")

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


def test_lock_groups_rejects_invalid_workspace_patterns(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv.workspace]\nmembers = [1]\n")
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["project-runtime"]\nextras = []\ndefault-groups = []\n[tool.release-creator]\n'
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "workspace patterns must be strings" in result.stderr


def test_lock_groups_rejects_workspace_member_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["external"]\n')
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "pyproject.toml").write_text("[dependency-groups]\nrelease-hidden = []\n")
    (project / "external").symlink_to(outside, target_is_directory=True)
    lock = project / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["project-runtime", "release-hidden"]\n'
        "extras = []\ndefault-groups = []\n[tool.release-creator]\n"
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "workspace members must be inside the project" in result.stderr


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("missing = { workspace = true }", id="undeclared-member"),
        pytest.param('bare = { git = "https://example.org/bare" }', id="git-source"),
        pytest.param('bare = { workspace = true, git = "https://example.org/bare" }', id="mixed-source"),
    ],
)
def test_lock_groups_rejects_unapproved_workspace_sources_in_pr_and_release(tmp_path: Path, source: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "bare"\nrequires-python = ">=3.15"\n'
        '[tool.uv.workspace]\nmembers = ["meta"]\n[dependency-groups]\nrelease-news = []\n'
    )
    member = tmp_path / "meta"
    member.mkdir()
    (member / "pyproject.toml").write_text(
        f'[project]\nname = "meta"\nrequires-python = ">=3.15"\n[tool.uv.sources]\n{source}\n'
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'lock-version = "1.0"\ncreated-by = "release-creator"\nrequires-python = ">=3.15"\n'
        'dependency-groups = ["project-runtime", "release-news"]\n'
        "default-groups = []\npackages = []\n[tool.release-creator]\ncreated-at = 2026-10-20T00:00:00Z\n"
    )
    tools = Path(__file__).resolve().parents[2] / "tools"

    for command in (
        ["python3", str(tools / "lock_groups.py"), str(lock)],
        [
            sys.executable,
            str(tools / "check_lock_groups.py"),
            str(lock),
            "release-news",
            "--project",
            str(tmp_path / "pyproject.toml"),
        ],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        assert result.returncode != 0
        assert "uv source must name a workspace project" in result.stderr


@pytest.mark.parametrize(
    ("groups", "extras", "message"),
    [
        pytest.param('["project-runtime", "release-news"]', '["web"]', "omits dependency groups", id="group"),
        pytest.param('["project-runtime", "release-news", "test"]', "[]", "omits extras", id="extra"),
    ],
)
def test_lock_groups_rejects_incomplete_project_lock(tmp_path: Path, groups: str, extras: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project.optional-dependencies]\nweb = []\n[dependency-groups]\nrelease-news = []\ntest = []\n"
    )
    lock = tmp_path / "pylock.toml"
    lock.write_text(f"dependency-groups = {groups}\nextras = {extras}\ndefault-groups = []\n[tool.release-creator]\n")

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize(
    ("extra_group", "message"),
    [
        pytest.param("release-x\\nchanged=false", "invalid dependency groups", id="output-injection"),
        pytest.param("release-other", "invalid or undeclared", id="undeclared"),
        pytest.param("release-news", "invalid or undeclared", id="duplicate"),
    ],
)
def test_lock_groups_rejects_extra_full_lock_group(tmp_path: Path, extra_group: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[dependency-groups]\nrelease-news = []\n")
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        f'dependency-groups = ["project-runtime", "release-news", "{extra_group}"]\n'
        "extras = []\ndefault-groups = []\n[tool.release-creator]\n"
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize(
    "default_groups",
    [pytest.param("[]", id="empty"), pytest.param('["test"]', id="test"), pytest.param(None, id="missing")],
)
def test_lock_groups_requires_empty_defaults(tmp_path: Path, default_groups: str | None) -> None:
    (tmp_path / "pyproject.toml").write_text("[dependency-groups]\nrelease-news = []\ntest = []\n")
    lock = tmp_path / "pylock.toml"
    defaults = f"default-groups = {default_groups}\n" if default_groups is not None else ""
    lock.write_text(
        'dependency-groups = ["project-runtime", "release-news", "test"]\n'
        f"{defaults}[tool.release-creator]\ncreated-at = 2026-10-24T00:00:00Z\n"
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) is (default_groups == "[]")


def test_lock_groups_accepts_project_without_dependency_groups(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "example"\nversion = "1"\n')
    lock = tmp_path / "pylock.toml"
    lock.write_text(
        'dependency-groups = ["project-runtime"]\nextras = []\ndefault-groups = []\n[tool.release-creator]\n'
    )

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode, result.stdout) == (0, "\n")


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        pytest.param('"release-news"', "omits release groups", id="omitted-release-group"),
        pytest.param('"release-news", "release-check", "unknown"', "invalid or undeclared", id="undeclared-group"),
        pytest.param('"release-news\\nmode=refresh", "release-check"', "invalid or undeclared", id="output-injection"),
    ],
)
def test_lock_groups_rejects_untrusted_selection(tmp_path: Path, groups: str, message: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[dependency-groups]\nrelease-news = []\nrelease-check = []\n")
    lock = tmp_path / "pylock.toml"
    lock.write_text(f'[tool.nab]\ncommand-line = ["nab", "lock", "--groups", {groups}]\n')

    result = subprocess.run(
        ["python3", str(Path(__file__).resolve().parents[2] / "tools/lock_groups.py"), str(lock)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert message in result.stderr

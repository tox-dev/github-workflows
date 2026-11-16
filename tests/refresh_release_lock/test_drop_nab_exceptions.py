import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

_SCRIPT: Final = Path(__file__).resolve().parents[2] / "tools/drop_nab_exceptions.py"
_OLD: Final = "2000-01-01T00:00:00Z"
_NEW: Final = "2999-01-01T00:00:00Z"


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        pytest.param(
            "pyproject.toml",
            '[tool.nab]\nuploaded-prior-to = "P7D"\n# release-creator needs one.\n# expires 2000-01-02\n'
            f"packages.release-creator.uploaded-prior-to = {_OLD}\n# expires 2999-01-02\n"
            f"packages.ty.uploaded-prior-to = {_NEW}\n",
            f'[tool.nab]\nuploaded-prior-to = "P7D"\n# expires 2999-01-02\npackages.ty.uploaded-prior-to = {_NEW}\n',
            id="dotted-key-with-comments",
        ),
        pytest.param(
            "pyproject.toml",
            '[tool.nab]\nuploaded-prior-to = "P7D"\n\n# release-creator needs one.\n# expires 2000-01-02\n'
            f'[tool.nab.packages."release-creator"]\nuploaded-prior-to = {_OLD}\n\n# python-sbom needs one.\n'
            f'# expires 2999-01-02\n[tool.nab.packages."python-sbom"]\nuploaded-prior-to = {_NEW}\n',
            '[tool.nab]\nuploaded-prior-to = "P7D"\n\n# python-sbom needs one.\n'
            f'# expires 2999-01-02\n[tool.nab.packages."python-sbom"]\nuploaded-prior-to = {_NEW}\n',
            id="table-before-another-table",
        ),
        pytest.param(
            "pyproject.toml",
            f'[tool.nab]\nuploaded-prior-to = "P7D"\n\n# expires 2000-01-02\n[tool.nab.packages.six]\n'
            f"uploaded-prior-to = {_OLD}\n",
            '[tool.nab]\nuploaded-prior-to = "P7D"\n',
            id="last-table",
        ),
        pytest.param(
            "pyproject.toml",
            '[tool.nab]\nuploaded-prior-to = "P7D"\n# six needs universal dependencies.\n# expires 2000-01-02\n'
            f"[tool.nab.packages.six]\nassume-universal-deps = true\nuploaded-prior-to = {_OLD}\n",
            '[tool.nab]\nuploaded-prior-to = "P7D"\n# six needs universal dependencies.\n'
            "[tool.nab.packages.six]\nassume-universal-deps = true\n",
            id="table-with-other-settings",
        ),
        pytest.param(
            "nab.toml",
            f'uploaded-prior-to = "P7D"\n[packages.six]\nassume-universal-deps = true\nuploaded-prior-to = {_OLD}\n',
            'uploaded-prior-to = "P7D"\n[packages.six]\nassume-universal-deps = true\n',
            id="nab-toml-table-without-expiry",
        ),
        pytest.param(
            "pyproject.toml",
            f'tool.nab.packages.six.uploaded-prior-to = {_OLD}\ntool.nab.uploaded-prior-to = "P7D"\n',
            'tool.nab.uploaded-prior-to = "P7D"\n',
            id="first-line",
        ),
        pytest.param(
            "pyproject.toml",
            '[tool.nab]\nuploaded-prior-to = "P7D"\n# expires 2000-01-02\npackages.six.uploaded-prior-to = 2000-01-01\n',
            '[tool.nab]\nuploaded-prior-to = "P7D"\n',
            id="date-value",
        ),
        pytest.param(
            "pyproject.toml",
            "[tool.nab]\nuploaded-prior-to = 2026-10-01\n# expires 2000-01-02\n"
            "packages.six.uploaded-prior-to = 2026-09-30T23:59:59Z\n# expires 2000-01-02\n"
            "packages.ty.uploaded-prior-to = 2026-10-01\n",
            "[tool.nab]\nuploaded-prior-to = 2026-10-01\n# expires 2000-01-02\n"
            "packages.ty.uploaded-prior-to = 2026-10-01\n",
            id="absolute-cutoff",
        ),
    ],
)
def test_drop_removes_exceptions_under_the_refresh_cutoff(
    tmp_path: Path, filename: str, content: str, expected: str
) -> None:
    path = tmp_path / filename
    path.write_text(content)

    result = subprocess.run([sys.executable, str(_SCRIPT), str(path)], text=True, capture_output=True, check=False)

    assert (result.returncode, path.read_text(), result.stdout) == (0, expected, f"{path}\n")
    assert "Cutoff exception dropped:" in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            f'[tool.nab]\nuploaded-prior-to = "P7D"\n# expires 2999-01-02\npackages.six.uploaded-prior-to = {_NEW}\n',
            id="young-exception",
        ),
        pytest.param(f"[tool.nab]\n# expires 2000-01-02\npackages.six.uploaded-prior-to = {_OLD}\n", id="no-cutoff"),
        pytest.param(
            f'[tool.nab]\nuploaded-prior-to = "PT12H"\n# expires 2000-01-02\npackages.six.uploaded-prior-to = {_OLD}\n',
            id="unsupported-relative-cutoff",
        ),
        pytest.param(
            '[tool.nab]\nuploaded-prior-to = "P7D"\n# expires 2000-01-02\n'
            "packages.six.uploaded-prior-to = 2000-01-01T00:00:00\n",
            id="exception-without-time-zone",
        ),
        pytest.param(
            '[tool.nab]\nuploaded-prior-to = "P7D"\n# expires 2000-01-02\npackages.six.uploaded-prior-to = "P3D"\n',
            id="relative-exception",
        ),
        pytest.param(
            f'[tool.nab]\nuploaded-prior-to = "P7D"\npackages = {{ six = {{ uploaded-prior-to = {_OLD} }} }}\n',
            id="inline-table",
        ),
        pytest.param(
            '[tool.nab]\nuploaded-prior-to = "P7D"\n[tool.nab.packages.six]\nassume-universal-deps = true\n',
            id="override-without-cutoff",
        ),
    ],
)
def test_drop_keeps_exceptions_it_cannot_prove_redundant(tmp_path: Path, content: str) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(content)

    result = subprocess.run([sys.executable, str(_SCRIPT), str(path)], text=True, capture_output=True, check=False)

    assert (result.returncode, result.stdout, result.stderr, path.read_text()) == (0, "", "", content)


def test_drop_prints_only_changed_files(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.nab]\nuploaded-prior-to = "P7D"\npackages.six.uploaded-prior-to = {_OLD}\n'
    )
    (tmp_path / "nab.toml").write_text('uploaded-prior-to = "P7D"\n')

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), str(tmp_path / "pyproject.toml"), str(tmp_path / "nab.toml")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert (result.returncode, result.stdout) == (0, f"{tmp_path / 'pyproject.toml'}\n")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        pytest.param("[tool.nab\n", "Expected ']' at the end of a table declaration (at line 1, column 10)", id="toml"),
        pytest.param(None, "No such file or directory", id="missing"),
    ],
)
def test_drop_reports_unreadable_files(tmp_path: Path, content: str | None, message: str) -> None:
    path = tmp_path / "pyproject.toml"
    if content is not None:
        path.write_text(content)

    result = subprocess.run([sys.executable, str(_SCRIPT), str(path)], text=True, capture_output=True, check=False)

    assert result.returncode == 1
    assert result.stderr.startswith("::error::")
    assert message in result.stderr


def test_drop_import_has_no_cli_side_effect() -> None:
    importer = f"import runpy, sys; sys.path.insert(0, {str(_SCRIPT.parent)!r}); runpy.run_path({str(_SCRIPT)!r}, run_name='imported')"

    result = subprocess.run([sys.executable, "-c", importer], text=True, capture_output=True, check=False)

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")

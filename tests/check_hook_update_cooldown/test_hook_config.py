from __future__ import annotations

import json
import runpy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock
from urllib.request import urlopen

import pytest
from pytest_mock import MockerFixture


@pytest.fixture
def pypi_file() -> dict[str, object]:
    return {
        "url": "https://files.pythonhosted.org/example-1.2.0.whl",
        "digests": {"sha256": "a" * 64},
        "upload_time_iso_8601": (datetime.now(UTC) - timedelta(days=10)).isoformat(),
    }


@pytest.fixture
def pypi_request(mocker: MockerFixture, pypi_file: dict[str, object]) -> MagicMock:
    return cast("MagicMock", mocker.create_autospec(urlopen, return_value=_response("example", pypi_file)))


def _response(name: str, pypi_file: dict[str, object]) -> BytesIO:
    return BytesIO(json.dumps({"info": {"name": name, "version": "1.2.0"}, "urls": [pypi_file]}).encode())


@pytest.fixture
def check_config(mocker: MockerFixture, pypi_request: MagicMock) -> Callable[[Path, Path, bool, int], None]:
    namespace = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "tools/check_hook_config.py"), run_name="check_hook_config"
    )
    mocker.patch.dict(namespace["check_config"].__globals__, {"urlopen": pypi_request})
    return cast("Callable[[Path, Path, bool, int], None]", namespace["check_config"])


@pytest.fixture
def configs(tmp_path: Path) -> tuple[Path, Path]:
    base = tmp_path / "base.yaml"
    proposed = tmp_path / "proposed.yaml"
    base.write_text(
        "repos:\n  - repo: https://example.org/hook\n    rev: old\n    hooks:\n"
        "      - id: sample\n        additional_dependencies:\n          - example==1.0.0\n"
    )
    return base, proposed


def test_app_update_accepts_cooled_direct_pin(
    configs: tuple[Path, Path], check_config: Callable[..., None], pypi_request: MagicMock
) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("rev: old", "rev: new").replace("example==1.0.0", "example==1.2.0"))

    check_config(base, proposed, True, 7)
    assert pypi_request.call_args.args[0].full_url == "https://pypi.org/pypi/example/1.2.0/json"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("upload_time_iso_8601", "recent", id="recent"),
        pytest.param("yanked", True, id="yanked"),
        pytest.param("url", "https://example.org/wheel.whl", id="foreign-host"),
        pytest.param("digests", {}, id="missing-hash"),
    ],
)
def test_app_update_rejects_untrusted_pypi_file(
    configs: tuple[Path, Path],
    check_config: Callable[..., None],
    pypi_file: dict[str, object],
    pypi_request: MagicMock,
    field: str,
    value: object,
) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("example==1.0.0", "example==1.2.0"))
    pypi_file[field] = (datetime.now(UTC) - timedelta(days=1)).isoformat() if value == "recent" else value
    pypi_request.return_value = _response("example", pypi_file)

    with pytest.raises(ValueError, match="uncooled or untrusted PyPI artifact"):
        check_config(base, proposed, True, 7)


def test_app_update_accepts_cooled_managed_pin(
    configs: tuple[Path, Path], check_config: Callable[..., None], pypi_file: dict[str, object], pypi_request: MagicMock
) -> None:
    base, proposed = configs
    proposed.write_text(
        base.read_text().replace(
            "          - example==1.0.0\n",
            '          - example==1.0.0\n          - "other==1.2.0" # release-creator managed\n',
        )
    )

    pypi_request.return_value = _response("other", pypi_file)
    check_config(base, proposed, True, 7)
    assert pypi_request.call_args.args[0].full_url == "https://pypi.org/pypi/other/1.2.0/json"


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        pytest.param("example>=1.2.0", "not an exact PyPI pin", id="range"),
        pytest.param("other==1.2.0", "direct dependencies beyond an exact pin", id="another-package"),
        pytest.param("example @ https://example.org/wheel.whl", "direct dependencies beyond an exact pin", id="url"),
    ],
)
def test_app_update_rejects_unsafe_direct_change(
    configs: tuple[Path, Path], check_config: Callable[..., None], replacement: str, message: str
) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("example==1.0.0", replacement))

    with pytest.raises(ValueError, match=message):
        check_config(base, proposed, True, 7)


def test_other_bot_cannot_change_pin(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("example==1.0.0", "example==1.2.0"))

    with pytest.raises(ValueError, match="beyond revisions"):
        check_config(base, proposed, False, 7)


def test_app_update_keeps_direct_range(
    configs: tuple[Path, Path], check_config: Callable[..., None], pypi_file: dict[str, object], pypi_request: MagicMock
) -> None:
    base, proposed = configs
    base.write_text(base.read_text().replace("example==1.0.0", "example>=1"))
    proposed.write_text(
        base.read_text().replace(
            "          - example>=1\n", '          - example>=1\n          - "other==1.2.0" # release-creator managed\n'
        )
    )

    pypi_request.return_value = _response("other", pypi_file)
    check_config(base, proposed, True, 7)
    assert pypi_request.call_args.args[0].full_url == "https://pypi.org/pypi/other/1.2.0/json"


def test_app_update_rejects_managed_pin_removal(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    base.write_text(
        base.read_text().replace(
            "          - example==1.0.0\n",
            '          - example==1.0.0\n          - "other==1.0.0" # release-creator managed\n',
        )
    )
    proposed.write_text(configs[0].read_text().replace('          - "other==1.0.0" # release-creator managed\n', ""))

    with pytest.raises(ValueError, match="removes managed dependencies"):
        check_config(base, proposed, True, 7)


def test_app_update_accepts_managed_pin_refresh(
    configs: tuple[Path, Path], check_config: Callable[..., None], pypi_file: dict[str, object], pypi_request: MagicMock
) -> None:
    base, proposed = configs
    base.write_text(
        base.read_text().replace(
            "          - example==1.0.0\n",
            '          - example==1.0.0\n          - "other==1.0.0" # release-creator managed\n',
        )
    )
    proposed.write_text(base.read_text().replace("other==1.0.0", "other==1.2.0"))

    pypi_request.return_value = _response("other", pypi_file)
    check_config(base, proposed, True, 7)
    assert pypi_request.call_args.args[0].full_url == "https://pypi.org/pypi/other/1.2.0/json"


def test_app_update_accepts_flow_mapping_managed_marker(
    configs: tuple[Path, Path], check_config: Callable[..., None], pypi_file: dict[str, object], pypi_request: MagicMock
) -> None:
    base, proposed = configs
    proposed.write_text(
        base.read_text().replace(
            "      - id: sample\n        additional_dependencies:\n          - example==1.0.0\n",
            "      - {id: sample, additional_dependencies: [\n"
            "          example==1.0.0,\n"
            '          "other==1.2.0" # release-creator managed\n'
            "        ]}\n",
        )
    )

    pypi_request.return_value = _response("other", pypi_file)
    check_config(base, proposed, True, 7)
    assert pypi_request.call_args.args[0].full_url == "https://pypi.org/pypi/other/1.2.0/json"


def test_app_update_rejects_flow_comment_as_pin_marker(
    configs: tuple[Path, Path], check_config: Callable[..., None]
) -> None:
    base, proposed = configs
    proposed.write_text(
        base.read_text().replace(
            "additional_dependencies:\n          - example==1.0.0",
            "additional_dependencies: [example==1.0.0, other==1.2.0] # release-creator managed",
        )
    )

    with pytest.raises(ValueError, match="changes direct dependencies"):
        check_config(base, proposed, True, 7)


def test_app_update_rejects_duplicate_keys(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("    rev: old", "    rev: old\n    rev: new"))

    with pytest.raises(ValueError, match="duplicate mapping keys"):
        check_config(base, proposed, True, 7)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param("", "must be a mapping", id="empty-file"),
        pytest.param("[]\n", "must be a mapping", id="list-root"),
        pytest.param("repos: bad\n", "repositories must be lists", id="scalar-repos"),
        pytest.param("repos:\n  - bad\n", "repository must be a mapping", id="scalar-repository"),
        pytest.param(
            "repos:\n  - repo: https://example.org/hook\n", "repository must contain hooks", id="missing-hooks"
        ),
        pytest.param(
            "repos:\n  - repo: https://example.org/hook\n    hooks:\n      - bad\n",
            "hook must be a mapping",
            id="scalar-hook",
        ),
        pytest.param(
            "repos:\n  - repo: https://example.org/hook\n    hooks:\n"
            "      - id: sample\n        additional_dependencies: bad\n",
            "additional_dependencies must be a list",
            id="scalar-dependencies",
        ),
        pytest.param(
            "repos:\n  - repo: https://example.org/hook\n    hooks:\n"
            "      - id: sample\n        additional_dependencies: [example==1.0.0, {name: bad}]\n",
            "additional_dependencies must be a list",
            id="mapping-dependency",
        ),
    ],
)
def test_app_update_rejects_malformed_hook_config(
    configs: tuple[Path, Path], check_config: Callable[..., None], source: str, message: str
) -> None:
    base, proposed = configs
    proposed.write_text(source)

    with pytest.raises((TypeError, ValueError), match=message):
        check_config(base, proposed, True, 7)


def test_app_update_rejects_changed_hook_count(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text() + "      - id: added\n")

    with pytest.raises(ValueError, match="beyond revisions and managed dependencies"):
        check_config(base, proposed, True, 7)


def test_app_update_rejects_changed_aliased_hook(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    source = base.read_text().replace("- repo:", "- &repository\n    repo:")
    base.write_text(source.replace("          - example==1.0.0\n", "          - example==1.0.0\n  - *repository\n"))
    proposed.write_text(base.read_text().replace("id: sample", "id: changed"))

    with pytest.raises(ValueError, match="beyond revisions and managed dependencies"):
        check_config(base, proposed, True, 7)


def test_app_update_rejects_duplicate_dependency(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(
        base.read_text().replace(
            "          - example==1.0.0\n",
            '          - example==1.0.0\n          - "example==1.2.0" # release-creator managed\n',
        )
    )

    with pytest.raises(ValueError, match="duplicates a dependency"):
        check_config(base, proposed, True, 7)


@pytest.mark.parametrize(
    "metadata",
    [
        pytest.param({"info": {"name": "other", "version": "1.2.0"}, "urls": [{}]}, id="wrong-name"),
        pytest.param({"info": {"name": "example", "version": "1.1.0"}, "urls": [{}]}, id="wrong-version"),
        pytest.param({"info": {"name": "example", "version": "1.2.0"}, "urls": []}, id="no-files"),
        pytest.param({"info": {"name": "example", "version": "1.2.0"}, "urls": "bad"}, id="files-type"),
    ],
)
def test_app_update_rejects_invalid_pypi_listing(
    configs: tuple[Path, Path],
    check_config: Callable[..., None],
    pypi_request: MagicMock,
    metadata: dict[str, object],
) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("example==1.0.0", "example==1.2.0"))
    pypi_request.return_value = BytesIO(json.dumps(metadata).encode())

    with pytest.raises(ValueError, match="invalid PyPI hook dependency"):
        check_config(base, proposed, True, 7)


def test_app_cannot_change_hook_command(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("id: sample", "id: other"))

    with pytest.raises(ValueError, match="beyond revisions and managed dependencies"):
        check_config(base, proposed, True, 7)


def test_app_cannot_add_unmarked_dependency(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text() + "          - example==1.2.0\n")

    with pytest.raises(ValueError, match="changes direct dependencies"):
        check_config(base, proposed, True, 7)


def test_app_cannot_shorter_cooldown(configs: tuple[Path, Path], check_config: Callable[..., None]) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text())

    with pytest.raises(ValueError, match="at least seven days"):
        check_config(base, proposed, True, 6)


def test_cli_accepts_revision_only_change(
    configs: tuple[Path, Path], mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    base, proposed = configs
    proposed.write_text(base.read_text().replace("rev: old", "rev: new"))
    mocker.patch("sys.argv", ["check_hook_config.py", str(base), str(proposed), "--managed", "false"])

    runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/check_hook_config.py"), run_name="__main__")

    assert capsys.readouterr() == ("", "")


def test_cli_reports_invalid_config(
    configs: tuple[Path, Path], mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    base, proposed = configs
    proposed.write_text("repos: bad\n")
    mocker.patch("sys.argv", ["check_hook_config.py", str(base), str(proposed), "--managed", "true"])

    with pytest.raises(SystemExit, match="2"):
        runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/check_hook_config.py"), run_name="__main__")

    assert "hook repositories must be lists" in capsys.readouterr().err

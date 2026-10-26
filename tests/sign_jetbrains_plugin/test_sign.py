from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from conftest import action


@pytest.mark.parametrize(
    "credential_format",
    [
        pytest.param("pem", id="pem"),
        pytest.param("base64", id="base64"),
        pytest.param("encrypted", id="encrypted"),
    ],
)
def test_signs_and_verifies_exact_archive(
    action_scripts: Path,
    certificate: tuple[Path, Path],
    unsigned_archive: Path,
    tmp_path: Path,
    credential_format: str,
) -> None:
    private_key, chain = certificate
    password = ""
    if credential_format == "encrypted":
        encrypted_key = tmp_path / "encrypted.pem"
        subprocess.run(
            [
                "openssl",
                "pkcs8",
                "-topk8",
                "-v2",
                "aes-256-cbc",
                "-in",
                str(private_key),
                "-out",
                str(encrypted_key),
                "-passout",
                "pass:fixture-pass",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        private_key = encrypted_key
        password = "fixture-pass"
    key_text = private_key.read_text()
    chain_text = chain.read_text()
    if credential_format == "base64":
        key_text = base64.b64encode(key_text.encode()).decode()
        chain_text = base64.b64encode(chain_text.encode()).decode()
    java = shutil.which("java")
    assert java is not None
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "sign-jetbrains-plugin",
        version="",
        ARCHIVE=str(unsigned_archive),
        SHA256=hashlib.sha256(unsigned_archive.read_bytes()).hexdigest(),
        JAVA_HOME_17_X64=str(Path(java).resolve().parents[1]),
        CERTIFICATE_CHAIN=chain_text,
        PRIVATE_KEY=key_text,
        PRIVATE_KEY_PASSWORD=password,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "signing-key.pem").exists()
    assert not (tmp_path / "signing-key-decrypted.pem").exists()
    assert not (tmp_path / "signing-chain.pem").exists()
    signed = unsigned_archive.with_name("Plugin 2-1.0-signed.zip")
    assert dict(line.split("=", 1) for line in (tmp_path / "output").read_text().splitlines()) == {
        "archive": str(signed),
        "sha256": hashlib.sha256(signed.read_bytes()).hexdigest(),
    }
    with ZipFile(unsigned_archive) as unsigned, ZipFile(signed) as signed_zip:
        assert {name: unsigned.read(name) for name in unsigned.namelist()} == {
            name: signed_zip.read(name) for name in signed_zip.namelist()
        }


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param("digest", id="wrong-digest"),
        pytest.param("corrupt", id="corrupt-zip"),
        pytest.param("duplicate", id="duplicate-member"),
    ],
)
def test_rejects_invalid_unsigned_archive(
    action_scripts: Path,
    unsigned_archive: Path,
    tmp_path: Path,
    invalid: str,
) -> None:
    archive = unsigned_archive
    if invalid == "corrupt":
        archive.write_bytes(b"not a ZIP")
    elif invalid == "duplicate":
        with ZipFile(archive, "a") as content:
            content.writestr("Plugin/lib/Plugin.jar", b"changed")
    assert (
        action(
            tmp_path,
            tmp_path,
            action_scripts,
            "sign-jetbrains-plugin",
            version="",
            ARCHIVE=str(archive),
            SHA256="0" * 64 if invalid == "digest" else hashlib.sha256(archive.read_bytes()).hexdigest(),
        ).returncode
        != 0
    )


def test_rejects_missing_java(action_scripts: Path, unsigned_archive: Path, tmp_path: Path) -> None:
    assert (
        action(
            tmp_path,
            tmp_path,
            action_scripts,
            "sign-jetbrains-plugin",
            version="",
            ARCHIVE=str(unsigned_archive),
            SHA256=hashlib.sha256(unsigned_archive.read_bytes()).hexdigest(),
            JAVA_HOME_17_X64=str(tmp_path / "missing"),
        ).returncode
        != 0
    )


@pytest.mark.parametrize("existing", [pytest.param("file", id="file"), pytest.param("symlink", id="symlink")])
def test_rejects_existing_signed_archive(
    action_scripts: Path, unsigned_archive: Path, tmp_path: Path, existing: str
) -> None:
    signed = tmp_path / "Plugin 2-1.0-signed.zip"
    if existing == "symlink":
        signed.symlink_to(unsigned_archive)
    else:
        signed.write_bytes(b"existing")
    result = action(
        tmp_path,
        tmp_path,
        action_scripts,
        "sign-jetbrains-plugin",
        version="",
        ARCHIVE=str(unsigned_archive),
        SHA256=hashlib.sha256(unsigned_archive.read_bytes()).hexdigest(),
    )
    assert result.returncode != 0
    assert "signed archive already exists" in result.stderr


@pytest.fixture
def unsigned_archive(tmp_path: Path) -> Path:
    archive = tmp_path / "Plugin 2-1.0.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as content:
        content.writestr("Plugin/lib/Plugin.jar", b"plugin payload")
    return archive


@pytest.fixture
def certificate(tmp_path: Path) -> tuple[Path, Path]:
    private_key = tmp_path / "key.pem"
    chain = tmp_path / "chain.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(chain),
            "-subj",
            "/CN=JetBrains test",
            "-days",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return private_key, chain

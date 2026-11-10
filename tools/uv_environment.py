"""Remove caller uv settings from isolated tool installs."""

import os


def clean_uv_environment() -> dict[str, str]:
    excluded = {
        "UV_CONFIG_FILE",
        "UV_INDEX",
        "UV_INDEX_URL",
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_FIND_LINKS",
        "UV_EXCLUDE_NEWER",
        "UV_EXCLUDE_NEWER_PACKAGE",
        "UV_INSECURE_HOST",
        "UV_SYSTEM_CERTS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {name: value for name, value in os.environ.items() if name not in excluded}


__all__ = [
    "clean_uv_environment",
]

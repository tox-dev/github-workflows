Make the Actions install their own tools, such as Nab, `packaging`, `certifi`, and `pypi-attestations`, from PyPI even
when the caller's repository or environment configures another index. The installer now ignores `uv.toml`, `[tool.uv]`
in `pyproject.toml`, and the `UV_INDEX`, `UV_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_EXTRA_INDEX_URL`, `UV_FIND_LINKS`,
`UV_CONFIG_FILE`, `UV_INSECURE_HOST`, `UV_SYSTEM_CERTS`, `SSL_CERT_FILE`, and `SSL_CERT_DIR` variables, as `cooled-prek`
already does.

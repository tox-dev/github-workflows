Generate the primary `pylock.toml` with `nab lock --all-groups --all-extras --no-cache`, adding `--upgrade` in
`refresh` mode, and compare a regenerated lock in `check` mode. The `release-creator locks` path and the uv resolver
steps are gone, so relock a `release-creator locks` lock with Nab before re-pinning. Nab runs without `SSL_CERT_FILE`
and `SSL_CERT_DIR`.

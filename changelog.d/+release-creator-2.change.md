Lock release-creator 2.0.0 for the shared release tools during its seven-day review window. Caller locks must be
regenerated with `release-creator locks` 2.0.0, because its `--check` compares the recorded uv version and no longer
writes the `[tool.nab]` stamp. The `calver` bump is gone from release-creator, so it is no longer documented here.

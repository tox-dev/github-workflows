Make `validate-news` reject a pull request that removes `pylock.toml` when the project has a `nab.toml`, as it already
did for a `[tool.nab]` table in `pyproject.toml`.

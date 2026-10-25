Let `validate-news` accept a pull request that removes `pylock.toml` when the project has no `[tool.nab]` table and no
`additional-lock` is configured, so nothing would produce a lock.

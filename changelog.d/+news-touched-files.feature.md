Run each `validate-news` check only when the pull request touches what it validates: fragment validation when the
fragment directory changes, the Towncrier configuration check when `towncrier.toml` or the `tool.towncrier` table
changes, the lock check when a `pyproject.toml`, `pylock.toml`, root `pylock.*.toml`, or `nab.toml` changes, and the
lock-removal guard when `pylock.toml` is deleted. Workflow changes no longer trigger the lock check, and every root
`pylock.*.toml` does, whether or not it is the configured `additional-lock`. The fragment requirement for human pull
requests still runs on every pull request.

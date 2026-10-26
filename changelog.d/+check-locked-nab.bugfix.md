Make `refresh-release-lock` in `check` mode install the Nab version that the committed `pylock.toml` records in
`[tool.nab] nab-version`, and fail if the lock records none. A Nab release newer than that version rewrites the field,
so every committed lock failed the check until the weekly refresh. `refresh` mode still installs the newest Nab under
the cutoff, and `nab-git-commit` still installs from that commit in both modes.

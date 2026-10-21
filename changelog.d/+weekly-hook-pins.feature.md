Refresh exact pre-commit hook dependency pins in the weekly release-tool PR, with an opt-in to retain a project's
checked-in `uv.lock` alongside its selectable `pylock.toml`. Allow explicit package exceptions to the seven-day cutoff
when a declared minimum is newer than that cutoff.

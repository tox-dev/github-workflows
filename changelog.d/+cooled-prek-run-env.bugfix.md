`cooled-prek` builds hook environments under the seven-day cutoff, then runs the hooks with the caller's environment, so
a system hook that calls `uv run` resolves the project from its own lock instead of under the cutoff.

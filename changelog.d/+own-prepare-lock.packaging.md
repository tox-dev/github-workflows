Lock github-workflows' own `release-prepare` tools in a small `pylock.toml` made by Nab under the seven-day cutoff,
so its release preparation installs them hash-checked from its own lock like every caller.

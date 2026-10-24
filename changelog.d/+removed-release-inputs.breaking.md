Remove `recheck-hook-update-cooldown.minimum-days` and the unused `validate-python-release` inputs `changelog`,
`artifact-base-url`, `artifact-label`, and `local-tool-source`. Recheck uses a fixed seven-day minimum; release notes
are rendered by the caller's notes job.

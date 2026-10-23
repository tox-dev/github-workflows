Remove the unused `build-python-distribution.source`, `recheck-hook-update-cooldown.workflow`, and
`recheck-hook-update-cooldown.job-name` inputs. The build Action uses the repository root; the cooldown reruns
`hook-cooldown` in `check.yaml`.

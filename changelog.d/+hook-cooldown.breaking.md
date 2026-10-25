Remove the `check-hook-update-cooldown` and `recheck-hook-update-cooldown` Actions and the `recheck-hook-cooldown.yaml`
workflow. Pull requests that change `.pre-commit-config.yaml` are no longer checked for hook revision age or dependency
closure cooling; drop the `hook-cooldown` job and its scheduled rerun from callers.

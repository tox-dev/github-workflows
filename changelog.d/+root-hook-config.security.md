Run every prek command with `--config .pre-commit-config.yaml`, and reject a `prek.toml`, a `.pre-commit-config.yml`, or
a nested `.pre-commit-config.yaml` in the hook cooldown and frozen hook checks. prek used to run those files without any
revision, cooldown, or dependency check.

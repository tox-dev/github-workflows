Remove the `lock` job from `validate-python-release.yaml` and `prepare-towncrier-release.yaml`, and the lock check from
`check-tagged-source`. `validate-news` still checks the lock on the pull request that changes it. Both workflows drop
the `additional-lock`, `additional-lock-groups`, `additional-lock-selection`, `additional-matrix-python`,
`additional-matrix-platforms`, and `additional-matrix-implementations` inputs, and `check-tagged-source` drops them
along with `exclude-newer` and `exclude-newer-package`; remove them from callers. Without the `lock` job,
`prepare-towncrier-release.yaml` no longer skips a dispatch from a branch other than `main`.

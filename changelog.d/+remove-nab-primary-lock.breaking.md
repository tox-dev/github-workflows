Remove the Nab primary lock path and the `lock-groups` input of `refresh-release-lock` and `upgrade-release-tools`.
`pylock.toml` must now come from `release-creator locks`; relock a Nab primary lock before re-pinning. Nab remains for
secondary `additional-lock` matrices.

Reduce `validate-release-patch` to applying the patch and checking its paths and file modes, and remove its `version`
and `checks` inputs; remove them from callers. It no longer rejects a `main` branch that moved, a patch that leaves the
changelog unchanged, or RST conflict markers, and it no longer runs `release-creator validate-fragment-deletions`,
`release-creator notes`, the hook configuration check, or `prek`.

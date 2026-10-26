Remove the `validate` job from `prepare-towncrier-release.yaml`, which recalculated the version and ran
`release-creator` and `prek` on the patch that `assemble` had just produced; `push` now depends on `assemble` alone. The
workflow no longer installs the `release-validate` group.

Remove the `install-local-release-creator` Action and the `local-tool-source` input of `install-locked-tools` and
`prepare-towncrier-release.yaml`. A lock may no longer list release-creator as a local directory package.

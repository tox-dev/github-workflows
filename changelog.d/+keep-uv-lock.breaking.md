Remove the `keep-uv-lock` input of `refresh-release-lock`, `validate-news`, `check-tagged-source`,
`prepare-towncrier-release.yaml`, `upgrade-release-tools.yaml`, and `validate-python-release.yaml`. A committed
`uv.lock` is no longer refreshed or checked.

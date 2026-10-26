Remove the temporary `nab-git-commit` input from `refresh-release-lock`, `validate-news`,
`prepare-towncrier-release.yaml`, `upgrade-release-tools.yaml`, and `validate-python-release.yaml`. The Actions always
install Nab from PyPI; remove the input from callers.

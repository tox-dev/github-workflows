Remove the `upgrade-resolver` input of `refresh-release-lock` and `upgrade-release-tools`. The shared uv resolver pin
is upgraded only in github-workflows, which the Action now detects from the repository name.

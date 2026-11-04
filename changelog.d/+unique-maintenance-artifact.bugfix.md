A workflow that calls both `update-python-dependencies` and `upgrade-release-tools` no longer fails in
`open-maintenance-pr` with `None of the provided artifact IDs were found`. Each reusable now uploads its patch under its
own artifact name.

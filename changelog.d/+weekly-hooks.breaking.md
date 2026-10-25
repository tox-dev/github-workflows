Remove the hook refresh from `upgrade-release-tools.yaml`. The weekly updater no longer runs
`prek update --freeze --cooldown-days 7` or `release-creator hooks`, and its writer accepts only the lock patch; let
Dependabot's `pre-commit` ecosystem update hook revisions instead.

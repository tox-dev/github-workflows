`prepare-towncrier-release` and `prepare-release-creator` install only the changelog formatter's hook instead of every
hook, so release preparation and its pull request dry run finish faster, and a hook the release never runs cannot fail
it.

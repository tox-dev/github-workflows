`prepare-towncrier-release` and `prepare-release-creator` take a `dry-run` input that assembles the release and skips
the push, so a pull request check fails when merging it would break the next release.

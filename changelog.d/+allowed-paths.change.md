`validate-release-patch` takes an `allowed-paths` input of glob patterns. When it is set, the patch may change only the
paths matching those patterns, and the Towncrier configuration is no longer read. Without it, the Action checks the
changelog and fragment deletions as before.

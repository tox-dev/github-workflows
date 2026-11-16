`upgrade-release-tools.yaml` no longer fails on an expired cutoff exception that its own refresh makes redundant: it
deletes that exception in the refresh pull request, keeps the refreshed lock's `created-at`, and then fails only on an
undated exception or an expired one the new lock still needs. `refresh-release-lock` gains `drop-redundant-exceptions`
for this.

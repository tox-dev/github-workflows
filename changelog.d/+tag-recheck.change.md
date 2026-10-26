Stop re-checking the release tag before publishing. `publish-github-release` no longer requires the remote tag to
resolve to `commit`, which now only sets the target of a new Release. `publish-jetbrains-marketplace` no longer requires
the remote tag to target `commit` or fails on an earlier upload of the tag from another commit. Drop the step that
re-checks the tag before `publish-github-release` from callers that copied the README example.

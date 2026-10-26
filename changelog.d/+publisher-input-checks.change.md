Stop validating caller input in the publishing Actions. `publish-github-release` no longer rejects an empty tag, title,
or notes file, a `prerelease` other than `true` or `false`, an unknown `mode`, or asset directories with hidden,
non-regular, or unusually named entries. `publish-jetbrains-marketplace` no longer checks the archive name and type, the
plugin ID, the channel, the tag ref, the notes file type, the artifact IDs, or that `publish-token` is set.
`sign-jetbrains-plugin` no longer checks the archive name and type, and `publish-post-release-pr` no longer checks the
format of its inputs or the `allowed-paths` entries.

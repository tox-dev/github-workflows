Make `publish-github-release` update an existing draft's title, notes, and prerelease flag on a rerun instead of
failing, use the first Release when several share the tag, and create the draft in `publish` mode when none exists. It
no longer compares the title, notes, and prerelease flag of an existing Release; the read-after-write retry and the
asset name and digest checks stay.

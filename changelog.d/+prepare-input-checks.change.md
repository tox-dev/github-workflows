Stop validating caller input in the prepare and tag Actions. `prepare-towncrier` no longer rejects an unknown `phase`, a
`finalize` run without `version`, a `changelog-prefix` other than empty or `v`, an explicit `version` that is not newer
than existing tags, other hook configuration files, or an unknown changelog format; any changelog not ending in `.rst`
is formatted with `mdformat`. `read-towncrier-config` no longer checks that the paths are normalized and inside the
repository, that the changelog ends in `.md` or `.rst`, or that fragment categories are configured.
`select-previous-tag` no longer requires the tag to exist locally or limits it to one namespace separator, and
`commit-and-tag` no longer rejects an empty `token` or `app-slug` or an `annotated` value other than `true` or `false`;
any value other than `true` creates a lightweight tag.

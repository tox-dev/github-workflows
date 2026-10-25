Stop checking caller locks against PyPI metadata and upload times in `install-locked-tools`. `check_lock_groups.py` now
only checks that the selected groups exist, and Nab's regenerate-and-compare check in `refresh-release-lock` guards the
lock on pull requests, on tags, and in a new keyless `lock` job of `prepare-towncrier-release.yaml` that runs before
assembly.

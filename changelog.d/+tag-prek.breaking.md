Stop running `prek` on the tagged source. `check-tagged-source` now checks only the tag and the locks and no longer
installs the caller's `release-check` group; the release patch is still checked with `prek` before it is pushed.

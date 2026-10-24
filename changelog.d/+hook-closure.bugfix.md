Check the cooldown, immutable hook revisions, and complete Python hook dependency pins on every pull request that
changes the hook configuration, including human and fork pull requests. Check the hook pins again before running hooks
from a release tag. Allow the first complete set of managed pins in a human PR while keeping later pin changes limited
to the release App. Run hook installs from PyPI with the seven-day cutoff, ignoring repository uv configuration.

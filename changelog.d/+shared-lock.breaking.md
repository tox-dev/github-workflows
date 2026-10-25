Remove the Actions' shared `pylock.toml`, its weekly refresh, and the `lock-source` input of `install-locked-tools`.
The Actions now install their own tools from PyPI under a seven-day cutoff, and `install-locked-tools` installs only
from the caller's `pylock.toml`. Build constraints come from the caller lock's `build` group alone, without the shared
Cython and setuptools pins.

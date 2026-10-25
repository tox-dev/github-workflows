Skip the cooling check of github-workflows' own lock when installing shared tools, and the second PyPI check of a
secondary lock's build selection when `export-build-constraints` already verified that lock.

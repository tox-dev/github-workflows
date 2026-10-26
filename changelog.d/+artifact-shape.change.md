Stop checking the shape of built artifacts that the release jobs produce themselves. `validate-python-release.yaml` no
longer requires an empty `dist` directory or exactly one wheel and one sdist at the tag's version, and
`build-python-distribution` no longer requires an empty `dist` directory. `reconcile-pypi-artifacts` no longer rejects
an empty `dist`, an invalid project name, or local files that are hidden, symbolic links, directories, or belong to
another release; it compares every file in `dist` with PyPI.

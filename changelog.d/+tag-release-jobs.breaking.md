Restructure `validate-python-release.yaml`. A keyless `lock` job checks the locks in parallel with `build`, which now
checks the tag inline, including that it resolves to `GITHUB_SHA`, and exports its own build constraints; the
`source-check` and `constraints` jobs and the `build-constraints` artifact are gone. The workflow no longer needs
`actions: read` or `pull-requests: read`, and its `validate` job runs only `check-wheel-contents`, without
`twine check`.

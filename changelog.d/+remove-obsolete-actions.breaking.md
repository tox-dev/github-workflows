Remove the `install-nab`, `label-bot-news`, `refresh-hook-pins`, `resolve-pr-from-run`, and
`validate-python-distribution` Actions. `select-previous-tag` no longer accepts `package`, `executable`, or
`stable-only`; `validate-release-patch` no longer accepts `expected-patch-sha`; and `render-release-notes` no longer
emits `previous`. The release validation workflow no longer uploads the `release-validation-notes` artifact.

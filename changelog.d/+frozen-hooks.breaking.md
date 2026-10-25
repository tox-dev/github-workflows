Remove the `verify-frozen-hooks` Action with its frozen revision, tagged hook provenance, and hook dependency closure
checks. The shared prepare workflow and `check-tagged-source` no longer run it; drop it from custom tag jobs.
`prepare-towncrier` and `validate-release-patch` now reject a `prek.toml` or a nested hook configuration before they
run `prek`.

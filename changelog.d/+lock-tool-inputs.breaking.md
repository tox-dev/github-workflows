Remove the `verify-lock` and `verify-groups` inputs from `install-locked-tools` and `verify-groups` from
`export-build-constraints`, together with the `check_lock_groups.py` check behind them; remove them from callers.
`install-locked-tools` no longer checks that the requested groups exist in the lock or requires `venv` with `groups`,
`export-build-constraints` no longer rejects an unknown platform, a malformed or empty target list, or targets that
select different build package versions, and `refresh-release-lock` and `upgrade-release-tools.yaml` no longer validate
`mode`, `additional-lock`, and the secondary matrix inputs.

Remove the `validate-release-patch` `patch` input. The Action reads the patch from
`${{ runner.temp }}/release-patch/release.patch`, where every caller downloaded it.

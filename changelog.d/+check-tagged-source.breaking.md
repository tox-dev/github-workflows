Remove the `check-tagged-source` Action, and stop checking the tag in `validate-python-release.yaml`: the workflow no
longer requires the tag to resolve to `GITHUB_SHA` or to sit on `main`, and checks out the tag with the default fetch
depth. Remove `check-tagged-source` steps from callers.

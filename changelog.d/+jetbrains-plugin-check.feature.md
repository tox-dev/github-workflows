Add `jetbrains-plugin-check.yaml`, a reusable JetBrains plugin check that builds the ZIP and records its SHA256, runs
`verifyPlugin` for each IDE in a matrix input, runs the Xvfb UI tests with a configurable start timeout, and gates on
all of them. A release caller passes the tag as `plugin-version` and signs the ZIP from the recorded digest.

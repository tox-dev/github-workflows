Require a release tag, source commit, signed ZIP artifact, and release notes artifact when publishing a JetBrains
plugin. The Action now records an acceptance receipt and blocks an ambiguous retry until a maintainer reconciles the
Marketplace update. Publishing now requires Deployments read access and a `release` environment so retries can detect
prior attempts after Actions runs or receipt artifacts expire.

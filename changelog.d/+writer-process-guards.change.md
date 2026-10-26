Stop `publish-jetbrains-marketplace` from inspecting earlier `release` environment deployments for the tag before an
upload; the job no longer needs Deployments read access. Stop `publish-post-release-pr` from failing when an open pull
request's title, body, or base changed, when several pull requests match, or when a merged pull request lost its
`skip news` label; it re-applies the label instead.

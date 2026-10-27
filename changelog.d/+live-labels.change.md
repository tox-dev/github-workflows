`validate-news` reads the pull request's current labels from the API, so re-running an older Changelog run after adding
`skip news` passes instead of failing on the labels the original event carried. Callers grant `pull-requests: read` to
the job.

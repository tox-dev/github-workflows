`publish-github-release` creates the draft on the existing tag without naming a target commit. GitHub compared the
target's workflow files with the default branch tip and refused the job's token with
`Resource not accessible by integration` whenever a pull request that changed a workflow merged while the release was
building. The Action now fails before creating the draft if the tag is missing or points at another commit.

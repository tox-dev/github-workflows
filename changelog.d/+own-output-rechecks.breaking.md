Remove the `app-slug` and `commit-message` inputs from `publish-post-release-pr`; remove them from callers. The Action
no longer compares the candidate's author, committer, and message with the App bot and the expected message, re-reads
the branch, pull request head, or base after writing, or checks the files of an already merged pull request against the
current base.

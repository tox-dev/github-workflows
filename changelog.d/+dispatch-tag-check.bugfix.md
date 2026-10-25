Let `check-tagged-source` accept a `workflow_dispatch` or other non-tag run, such as one from `main` with a `tag` input,
when the checkout is the commit that tag names and that commit is on `main`. Tag runs still require the tag,
`GITHUB_SHA`, and the checkout to match.

# Publish a pre-commit mirror

`publish-pre-commit-mirror.yaml` keeps a pre-commit mirror repository of a Python package's hook in step with PyPI. Run
it daily: it generates the mirror with pre-commit-mirror-maker 1.14.0, formats the result with prek 0.5.5, and commits
each new version as `Mirror: <version>`. On `main`, one atomic push updates the branch and creates a `v<version>` tag
per new version, then a GitHub release with generated notes is created for each tag. A run with no new upstream version
changes nothing.

```yaml
name: Mirror
on:
  push:
    branches: [main]
  workflow_dispatch:
  schedule:
    - cron: "30 8 * * *"
permissions: {}
jobs:
  mirror:
    uses: tox-dev/github-workflows/.github/workflows/publish-pre-commit-mirror.yaml@SHA
    permissions:
      contents: write
    with:
      package-name: pyproject-fmt
      files-regex: '(^|/)pyproject\.toml$'
```

| Input                         | Default  | Purpose                                                                             |
| ----------------------------- | -------- | ----------------------------------------------------------------------------------- |
| `package-name` **(required)** |          | Package that pre-commit-mirror-maker wraps, such as `pyproject-fmt`.                |
| `files-regex` **(required)**  |          | Regular expression for the files the mirrored hook accepts.                         |
| `exclude-newer`               | `7 days` | Cutoff for the tools the workflow installs, see [cutoffs](locked-tools.md#cutoffs). |
| `exclude-newer-package`       | empty    | Newline-separated `name=date` overrides.                                            |

The repository needs a pre-commit configuration for prek and a `README.md` with a `rev:` line, which the newest commit
updates to the new tag, keeping its quoting style; a README without one fails the run. The push uses the workflow's
`GITHUB_TOKEN`, so rulesets must let `github-actions[bot]` push to `main` and create tags. Pushes made with that token
start no other workflow. Runs are serialized per repository and time out after 15 minutes.

Behaviour worth knowing:

- Formatting runs twice. The first run may rewrite files and exit 1; the second must pass on the rewritten tree. Any
  other exit status fails the job.
- When one run mirrors several versions, only the newest commit gets the README update and the formatting. Older tags
  keep the tree pre-commit-mirror-maker generated.
- A version whose tag already exists on origin is a no-op when the regenerated tree matches the tag, so the daily run
  succeeds with a notice. A different tree fails the run and names both trees. A published tag is never moved, because a
  moved tag changes the rev users have pinned; bump the package version to publish new content.
- On a ref other than `main` the workflow generates and commits locally but pushes nothing.
- The job runs the repository's hooks while it holds `contents: write`. Trigger it on pushes to `main`, schedules, and
  manual dispatches.

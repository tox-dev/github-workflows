# Security scanning

Two reusable workflows upload results to the repository's code scanning page. Neither has triggers of its own, so the
caller keeps its schedule, branches, and pull request events.

## CodeQL: `codeql.yaml`

One analysis job per language, with `security-events: write` to upload results. Results are categorised as
`/language:<language>`.

```yaml
name: 🛡️ CodeQL
on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 9 * * 2"
  workflow_dispatch:
permissions: {}
concurrency:
  group: codeql-${{ github.ref }}-${{ github.run_attempt > 1 && github.run_id || 'current' }}
  cancel-in-progress: ${{ github.run_attempt == 1 }}
jobs:
  analyze:
    name: 🛡️ Analyze
    uses: tox-dev/github-workflows/.github/workflows/codeql.yaml@SHA
    permissions:
      contents: read
      security-events: write
    with:
      languages: '["actions","python"]'
      paths-ignore: '["tests"]'
```

The concurrency group cancels superseded first attempts but never a manual re-run.

| Input          | Default                | Purpose                                                                                                         |
| -------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------- |
| `languages`    | `["actions","python"]` | JSON array of CodeQL languages, one job each.                                                                   |
| `paths-ignore` | `[]`                   | JSON array of paths CodeQL skips, written to its configuration. Ignored when `config-file` is set.              |
| `queries`      | `security-extended`    | Query suite or comma-separated query list.                                                                      |
| `config-file`  | empty                  | Repository path to a CodeQL configuration file. Use it instead of `paths-ignore`; the file lists its own paths. |
| `build-mode`   | `none`                 | `none` or `autobuild`, for each language.                                                                       |

Pitfall: `build-mode: manual` is passed through to CodeQL, but the job runs nothing between the init and analyze steps
and a caller cannot add steps inside a reusable job, so a manual build has nothing to analyze. Keep a compiled language
that needs manual build steps in a local workflow.

Each check is named `<caller job name> / 🛡️ Analyze <language>`. With the caller job named `🛡️ Analyze`, the checks are
`🛡️ Analyze / 🛡️ Analyze actions` and `🛡️ Analyze / 🛡️ Analyze python`. Rulesets that required the earlier
`🛡️ Analyze <language>` name must require the new one. The workflow pins CodeQL Action v4.39.1 for both the init and
analyze steps.

## OpenSSF Scorecard: `scorecard.yaml`

Runs `ossf/scorecard-action` v2.5.0, publishes the results to the Scorecard API (which feeds the public badge), and
uploads the SARIF file to code scanning with the CodeQL Action. It takes no inputs and no secrets. Publishing only works
for public repositories.

The caller must grant every permission the job requests; each comment says which Scorecard check needs it:

```yaml
name: 🛡️ scorecard
on:
  branch_protection_rule:
  schedule:
    - cron: "30 7 * * 2"
  push:
    branches: ["main"]
  workflow_dispatch:
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
permissions: {}
jobs:
  analysis:
    name: 🛡️ Scorecard analysis
    permissions:
      actions: read # read workflow runs for the Packaging check
      checks: read # read check runs for the CI-Tests and SAST checks
      contents: read # check out and scan the repository
      id-token: write # authenticate the results published to the scorecard API
      issues: read # read issue activity for the Maintained check
      pull-requests: read # read reviews for the Code-Review check
      security-events: write # upload the SARIF results to code scanning
      statuses: read # read commit statuses for the CI-Tests check
    uses: tox-dev/github-workflows/.github/workflows/scorecard.yaml@SHA
```

The `branch_protection_rule` trigger rescores the repository when its branch protection changes. A fork that should not
publish can guard the job with `if: github.repository == 'owner/name'`.

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
    - cron: 0 9 * * 2
  workflow_dispatch:
permissions: {}
concurrency:
  group: codeql-${{ github.ref }}-${{ github.run_attempt > 1 && github.run_id ||
    'current' }}
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
uploads the SARIF file to code scanning with the CodeQL Action. It takes no inputs and no secrets. The action is
[free for public repositories](https://github.com/ossf/scorecard-action#scorecards-github-action); a private repository
needs GitHub Advanced Security.

The caller must grant every permission the job requests; each comment says which Scorecard check needs it:

```yaml
name: 🛡️ scorecard
on:
  branch_protection_rule:
  schedule:
    - cron: 30 7 * * 2
  push:
    branches: [main]
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

The Scorecard API rejects published results from a workflow that breaks its
[workflow restrictions](https://github.com/ossf/scorecard-action#workflow-restrictions), and the step only logs a
warning, so the badge stops updating while the run stays green. The reusable job already meets the job-level rules: it
runs only approved actions, has no `run` steps, env, defaults, containers, or services, and uses a GitHub-hosted Ubuntu
runner. The caller workflow must keep the global rules:

- no top-level `env` or `defaults`;
- no workflow-level write permissions, so keep `permissions: {}` at the top;
- no other job in the same workflow with `id-token: write`.

A repository with classic branch protection should consider moving to rulesets, which the Branch-Protection check can
read without an admin token.

## Verify the actions lockfile: `verify-actions-lock.yaml`

A [workflow lockfile](https://docs.github.com/en/actions/concepts/security/workflow-dependency-lockfiles),
`.github/workflows/actions.lock`, records the commit behind every action a workflow uses, its transitive actions
included. The runner runs that commit and rejects a job whose locked commit the tag no longer reaches, so the workflows
can keep readable tags such as `actions/checkout@v7.0.1`. This workflow runs `gh actions-lock --verify` from
[gh-actions-lock](https://github.com/github/gh-actions-lock) and fails when a workflow uses an action the lockfile does
not cover. It takes no inputs and no secrets.

Generate the lockfile once with `gh actions-lock`, which also rewrites SHA-pinned `uses:` lines to the tag they resolve
to, and call this workflow from the pull request checks:

```yaml
jobs:
  lockfile:
    name: 🔒 Verify actions lockfile
    uses: tox-dev/github-workflows/.github/workflows/verify-actions-lock.yaml@SHA
    permissions:
      contents: read
```

Dependabot updates the lockfile entry in the same pull request that bumps an action. The lockfile leaves three things to
the workflow:

- A reusable workflow call (`jobs.<id>.uses`) is not locked, so keep pinning it by full SHA. The actions inside it are
  locked by the lockfile of the repository that defines it, which applies even when the caller has none.
- Composite actions in this repository keep their SHA pins, since a lockfile covers workflows, not `action.yml` files.
- Container images are not locked; pin them by digest.

zizmor reads the lockfile from 1.32.0 on; older releases report every tag ref as `unpinned-uses`. zizmor checks only
that a workflow is listed, not that every action has an entry; a missing pin fails only the verify job.

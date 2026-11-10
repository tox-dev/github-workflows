# GitHub workflows

Reusable workflows and composite Actions shared by the tox-dev repositories. They run tox and CodeQL, check pull request
news, rehearse and prepare releases, push App-authored release commits and tags, publish GitHub Releases, JetBrains
plugins, pre-commit mirrors and LaTeX PDFs, and keep dependencies current. Each repository keeps its own dispatch form,
publisher, GitHub environments, and required check names; the shared pieces hold the steps every repository repeats and
the checks that guard its keys.

Two rules run through all of them:

- **Keys stay away from project code.** Jobs that run hooks, tests, or builds hold read-only tokens. A writer job gets
  the App key or `contents: write`, checks the patch or artifact it was handed, and refuses `pull_request`,
  `pull_request_target`, `workflow_run`, `issue_comment`, and `merge_group` triggers. Writer jobs run no project code,
  except the pre-commit mirror, which runs the repository's hooks and refuses those triggers for that reason.
- **Tools arrive cooled.** Release tools install hash-checked from the caller's `pylock.toml`; tools the Actions need
  for themselves install from PyPI only once a release is seven days old, by default. See
  [Locked tools and cutoffs](docs/locked-tools.md).

## What is here

Reusable workflows, called with `uses: tox-dev/github-workflows/.github/workflows/<file>@SHA`. The caller job must grant
at least the listed permissions; "App key" means it also passes the `RELEASE_APP_PRIVATE_KEY` secret.

| Workflow                          | Purpose                                                                        | Caller grants                                    | Docs                                                                                       |
| --------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `check.yaml`                      | Run tox environments, one job per row, with a gate.                            | `contents: read`                                 | [PR checks](docs/pr-checks.md#run-tox-environments-checkyaml)                              |
| `cooled-hooks.yaml`               | Run every prek hook over the tree, environments built under the cutoff.        | `contents: read`                                 | [PR checks](docs/pr-checks.md#run-hooks-under-the-cooldown-cooled-hooksyaml)               |
| `prepare-towncrier-release.yaml`  | Build the Towncrier changelog, push the release commit and tag; or dry run.    | `contents: read`, `pull-requests: read`; App key | [Prepare](docs/release-prepare.md#prepare-towncrier-releaseyaml)                           |
| `prepare-release-creator.yaml`    | Same for multi-package or Rust repositories with a caller-assembled changelog. | `contents: read`, `pull-requests: read`; App key | [Prepare](docs/release-prepare.md#prepare-release-creatoryaml)                             |
| `validate-python-release.yaml`    | Build a wheel and sdist from the tag against locked build constraints.         | `contents: read`                                 | [Publish](docs/release-publish.md#validate-python-releaseyaml)                             |
| `build-maturin-wheels.yaml`       | Build maturin wheels for a matrix, plus the sdist.                             | `contents: read`                                 | [Publish](docs/release-publish.md#build-maturin-wheelsyaml)                                |
| `release-notes.yaml`              | Render the GitHub Release body from the changelog.                             | `contents: read`                                 | [Publish](docs/release-publish.md#release-notesyaml)                                       |
| `github-release.yaml`             | Verify the PyPI files, then publish the GitHub Release.                        | `contents: write`                                | [Publish](docs/release-publish.md#github-releaseyaml)                                      |
| `upgrade-release-tools.yaml`      | Refresh `pylock.toml` and open a pull request.                                 | `contents: read`; App key                        | [Maintenance](docs/maintenance.md#refresh-the-release-lock-upgrade-release-toolsyaml)      |
| `update-python-dependencies.yaml` | Bump dependency floors, relock, and open a pull request.                       | `contents: read`; App key                        | [Maintenance](docs/maintenance.md#bump-dependency-floors-update-python-dependenciesyaml)   |
| `open-maintenance-pr.yaml`        | Turn a patch from a read-only job into one pull request.                       | `contents: read`; App key                        | [Maintenance](docs/maintenance.md#open-a-maintenance-pull-request-open-maintenance-pryaml) |
| `codeql.yaml`                     | CodeQL analysis, one job per language.                                         | `contents: read`, `security-events: write`       | [Security](docs/security-scanning.md#codeql-codeqlyaml)                                    |
| `scorecard.yaml`                  | OpenSSF Scorecard analysis, published and uploaded to code scanning.           | eight scopes, listed on its page                 | [Security](docs/security-scanning.md#openssf-scorecard-scorecardyaml)                      |
| `verify-actions-lock.yaml`        | Check that the actions lockfile pins every action the workflows use.           | `contents: read`                                 | [Security](docs/security-scanning.md#verify-the-actions-lockfile-verify-actions-lockyaml)  |
| `jetbrains-plugin-check.yaml`     | Build, verify, and UI-test a JetBrains plugin.                                 | `contents: read`                                 | [JetBrains](docs/jetbrains.md#check-a-plugin-jetbrains-plugin-checkyaml)                   |
| `publish-pre-commit-mirror.yaml`  | Mirror a Python package's hook as a pre-commit repository.                     | `contents: write`                                | [pre-commit mirror](docs/pre-commit-mirror.md)                                             |
| `latex-to-pages.yaml`             | Compile a LaTeX document and deploy the PDF to GitHub Pages.                   | `contents: write`, `pages: read`                 | [LaTeX](docs/latex-pages.md)                                                               |

Composite Actions, called with `uses: tox-dev/github-workflows/<name>@SHA`:

| Action                           | Purpose                                                                 | Docs                                                                                   |
| -------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `required-checks`                | Gate job: fail unless every needed job succeeded.                       | [PR checks](docs/pr-checks.md#gate-on-needed-jobs-required-checks)                     |
| `validate-news`                  | Require a news fragment on human PRs; check fragments and lock changes. | [PR checks](docs/pr-checks.md#check-pull-request-news-validate-news)                   |
| `build-python-distribution`      | Keyless wheel and sdist build for PR jobs.                              | [PR checks](docs/pr-checks.md#build-a-distribution-build-python-distribution)          |
| `install-locked-tools`           | Install selected groups from the caller's `pylock.toml`.                | [Locked tools](docs/locked-tools.md#install-locked-tools-install-locked-tools)         |
| `export-build-constraints`       | Write hashed build constraints from a lock.                             | [Locked tools](docs/locked-tools.md#export-build-constraints-export-build-constraints) |
| `refresh-release-lock`           | Refresh or check the Nab lock.                                          | [Locked tools](docs/locked-tools.md#refresh-release-lock)                              |
| `check-nab-exceptions`           | Fail on an undated or expired cutoff exception.                         | [Locked tools](docs/locked-tools.md#expire-cutoff-exceptions)                          |
| `cooled-prek`                    | Run prek with hook environments under the seven-day cutoff.             | [Locked tools](docs/locked-tools.md#run-prek-under-the-cutoff-cooled-prek)             |
| `read-towncrier-config`          | Read changelog path, fragment directory, and format from `HEAD`.        | [Prepare](docs/release-prepare.md#read-towncrier-config)                               |
| `prepare-towncrier`              | Select the version, build and format the changelog, write a patch.      | [Prepare](docs/release-prepare.md#prepare-towncrier)                                   |
| `validate-release-patch`         | Apply a release patch and check its paths and modes.                    | [Prepare](docs/release-prepare.md#validate-release-patch)                              |
| `commit-and-tag`                 | Commit as the App bot and push `main` and the tag atomically.           | [Prepare](docs/release-prepare.md#commit-and-tag)                                      |
| `render-release-notes`           | Render the Release body to a file.                                      | [Publish](docs/release-publish.md#render-release-notes)                                |
| `select-previous-tag`            | Find the preceding release tag.                                         | [Publish](docs/release-publish.md#select-previous-tag)                                 |
| `reconcile-pypi-artifacts`       | Compare built files with PyPI and verify their attestations.            | [Publish](docs/release-publish.md#reconcile-pypi-artifacts)                            |
| `publish-github-release`         | Create, resume, or verify a GitHub Release with its assets.             | [Publish](docs/release-publish.md#publish-github-release)                              |
| `sign-jetbrains-plugin`          | Sign a plugin ZIP in a no-checkout job.                                 | [JetBrains](docs/jetbrains.md#sign-sign-jetbrains-plugin)                              |
| `stage-jetbrains-marketplace`    | Check a signed ZIP against the Marketplace before and after upload.     | [JetBrains](docs/jetbrains.md#stage-and-verify-stage-jetbrains-marketplace)            |
| `publish-jetbrains-marketplace`  | Upload a signed ZIP once per tag, with a receipt.                       | [JetBrains](docs/jetbrains.md#publish-publish-jetbrains-marketplace)                   |
| `prepare-jetbrains-post-release` | Prepare the next `-dev` version commit without a token.                 | [JetBrains](docs/jetbrains.md#prepare-jetbrains-post-release)                          |
| `publish-post-release-pr`        | Push a prepared commit and open its pull request.                       | [JetBrains](docs/jetbrains.md#publish-post-release-pr)                                 |

## Quick start

A typical Python library wires the pieces up with the caller files below. Read [Release flow](docs/release.md) for how
they connect and the one-time setup: a repository-only release App, the `release-auth` and `release` environments, and
the lock groups.

`.github/workflows/check.yaml` runs the tests and the release dry run, and holds the required gate:

```yaml
name: 🧪 check
on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: ["main"]
    tags-ignore: ["**"]
permissions: {}
concurrency:
  group: check-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    name: 🧪 Test
    uses: tox-dev/github-workflows/.github/workflows/check.yaml@SHA # 6.6.0
    permissions:
      contents: read
    with:
      include: |
        [{"env": "3.15"}, {"env": "3.14", "python": "3.14"}, {"env": "type"}, {"env": "pkg_meta"}]
  release:
    name: 🏷️ Release dry run
    uses: ./.github/workflows/prepare-release.yaml # zizmor: ignore[self-repository] actionlint rejects the $/ form
    permissions:
      contents: read
      pull-requests: read
    with:
      dry-run: true
  gate:
    name: 🚦 Required checks pass
    if: ${{ !cancelled() }}
    needs: [test, release]
    runs-on: ubuntu-26.04
    permissions: {}
    steps:
      - uses: tox-dev/github-workflows/required-checks@SHA # 6.6.0
        with:
          needs: ${{ toJSON(needs) }}
```

The release job references the caller's own workflow with `./` so that actionlint accepts it; a repository that does not
run actionlint can write `$/.github/workflows/prepare-release.yaml` instead, see
[Dry run on pull requests](docs/release-prepare.md#dry-run-on-pull-requests).

`.github/workflows/prepare-release.yaml` is dispatched by hand to release, and called by the gate as a dry run:

```yaml
name: Prepare release
on:
  workflow_dispatch:
    inputs:
      bump:
        type: choice
        options: [auto, major, minor, patch]
        default: auto
  workflow_call:
    inputs:
      dry-run:
        type: boolean
        required: true
permissions: {}
jobs:
  prepare:
    uses: tox-dev/github-workflows/.github/workflows/prepare-towncrier-release.yaml@SHA # 6.6.0
    permissions:
      contents: read
      pull-requests: read
    with:
      bump: ${{ inputs.bump || 'auto' }}
      dry-run: ${{ inputs.dry-run == true }}
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

The remaining files, each shown in full on its page:

| Caller file                                    | Calls                                                              | Example                                                              |
| ---------------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------- |
| `news.yaml` (on `labeled`/`unlabeled` too)     | `install-locked-tools`, `validate-news`                            | [PR checks](docs/pr-checks.md#check-pull-request-news-validate-news) |
| `release.yaml` (on tag push)                   | `validate-python-release`, `release-notes`, PyPI, `github-release` | [Publish](docs/release-publish.md#a-complete-tag-workflow)           |
| `update-dependencies.yaml` (weekly)            | `update-python-dependencies` or `upgrade-release-tools`            | [Maintenance](docs/maintenance.md)                                   |
| `codeql.yaml`, `scorecard.yaml` (weekly, push) | `codeql`, `scorecard`                                              | [Security](docs/security-scanning.md)                                |

Require two checks in the `main` ruleset: the gate (`🚦 Required checks pass`) and the news job.

## Versioning and pinning

Releases are tagged `X.Y.Z` with no `v` prefix and no moving major tag such as `v6`. Each is listed in the
[changelog](CHANGELOG.md). Pin every workflow and Action from this repository to the full commit SHA of a release tag,
with the version in a trailing comment:

```yaml
uses: tox-dev/github-workflows/.github/workflows/check.yaml@2a3b863f4563ce9891d2cee1ed381b6f82654836 # 6.6.0
```

A full SHA is the only reference GitHub cannot move, as its
[security guidance for third-party actions](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions)
explains. `SHA` in the examples means that commit. Pin every piece to the same release: a reusable workflow runs the
Actions from its own commit, so mixed pins mix versions.

Before moving a pin across releases, read each "Breaking changes" section you skip:
[6.0.0](CHANGELOG.md#release-6-0-0-breaking-changes), [5.0.0](CHANGELOG.md#release-5-0-0-breaking-changes),
[4.0.0](CHANGELOG.md#release-4-0-0-breaking-changes), [3.0.1](CHANGELOG.md#release-3-0-1-breaking-changes),
[3.0.0](CHANGELOG.md#release-3-0-0-breaking-changes), [2.0.0](CHANGELOG.md#release-2-0-0-breaking-changes), and
[1.0.0](CHANGELOG.md#release-1-0-0-breaking-changes). Most breaking changes ship in a major release, but 3.0.1 shows
that a patch release can carry one too.

## What stays in your repository

The shared pieces leave these to each caller on purpose:

- **PyPI upload.** Trusted publishing does not work from a reusable workflow, so the upload job lives in the caller's
  tag workflow.
- **Project-specific build steps**, such as PGO, README generation, or vendoring, beyond the documented pre- and
  post-build commands.
- **Required check names, triggers, and schedules.** Callers name their gate and schedule their own runs.
- **Cutoff exceptions.** The caller adds and removes `[tool.nab]` exceptions; the shared checks only enforce their
  expiry dates.

## Documentation

- [Release flow](docs/release.md): how the pieces connect, the diagram, and the one-time repository setup.
- [Prepare and tag a release](docs/release-prepare.md) and [Publish a release](docs/release-publish.md).
- [Pull request checks](docs/pr-checks.md): tox, the gate, news fragments, and the release dry run.
- [Maintenance pull requests](docs/maintenance.md): lock refresh, dependency bumps, generated changes.
- [Locked tools and cutoffs](docs/locked-tools.md): the caller's lock, cutoffs, exceptions, and prek.
- [Security scanning](docs/security-scanning.md), [JetBrains plugins](docs/jetbrains.md),
  [pre-commit mirror](docs/pre-commit-mirror.md), and [LaTeX to Pages](docs/latex-pages.md).
- [Troubleshooting](docs/troubleshooting.md): error messages from the job logs and what to do about each.

See [Contributing](CONTRIBUTING.md) for local checks and news fragments.

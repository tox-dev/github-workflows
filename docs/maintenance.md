# Maintenance pull requests

Three reusable workflows keep a repository's dependencies current without giving project code a write token. Each one
splits the work in two: a read-only job produces a patch, and a separate writer job, the only one that sees the App key,
checks the patch and opens or updates one pull request. The pull request then runs the normal checks before anyone
merges it.

| Workflow                          | Use it when                                                                               |
| --------------------------------- | ----------------------------------------------------------------------------------------- |
| `upgrade-release-tools.yaml`      | You want a weekly refresh of `pylock.toml` (and a secondary build lock) under the cutoff. |
| `update-python-dependencies.yaml` | You also want dependency floors in `pyproject.toml`, `tox.toml` and similar bumped.       |
| `open-maintenance-pr.yaml`        | Your own read-only job generates some other change, such as regenerated diagrams.         |

All three need the same setup:

- A repository-only release App with Contents and Pull requests write access, installed on this repository only.
- The `release-auth` environment, restricted to `main`, holding the `RELEASE_APP_PRIVATE_KEY` secret and the
  `RELEASE_APP_CLIENT_ID` variable (a repository variable works too).
- The caller passes the secret by name. GitHub requires this mapping even when the key exists only in the writer job's
  environment.
- Trigger the caller on `push`, `schedule`, `workflow_dispatch`, or `release`.

## Refresh the release lock: `upgrade-release-tools.yaml`

The read-only job first runs [`check-nab-exceptions`](locked-tools.md#expire-cutoff-exceptions), so every scheduled run
fails on an expired or undated cutoff exception even when no release input changed. It then runs
[`refresh-release-lock`](locked-tools.md#refresh-release-lock) in `refresh` mode, which rebuilds the universal
`pylock.toml` with `nab lock --all-groups --all-extras --no-cache --upgrade`: runtime dependencies, all extras, and all
dependency groups. The project's `[tool.nab]` table sets the cutoff and any per-package exception; the caller adds and
removes those exceptions itself. uv only installs tools and never resolves the lock.

When the lock changes, the job uploads a patch that may change only `pylock.toml` and the configured secondary lock.
[`open-maintenance-pr`](#open-a-maintenance-pull-request-open-maintenance-pryaml) checks it before minting the App token
and opens or updates one pull request from `automation/update-release-tools` to `main`, labelled `dependencies` and
`skip news`. Create both labels and allow the App to push that branch.

```yaml
name: Upgrade release tools
on:
  workflow_dispatch:
  schedule:
    - cron: 0 8 * * 2
permissions: {}
jobs:
  upgrade:
    uses: >-
      tox-dev/github-workflows/.github/workflows/upgrade-release-tools.yaml@SHA
    permissions:
      contents: read
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

| Input                               | Default                                 | Purpose                                                                                     |
| ----------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------- |
| `pull-request-title`                | `🔧 build(deps): refresh release tools` | Pull request title, also the commit subject.                                                |
| `pull-request-body`                 | `Refresh the project lock.`             | Pull request body.                                                                          |
| `additional-lock`                   | empty                                   | Basename of a secondary Nab lock, such as `pylock.build.toml`, refreshed in the same PR.    |
| `additional-lock-groups`            | empty                                   | Dependency groups to select in the secondary lock; empty selects build requirements.        |
| `additional-lock-selection`         | `build-or-groups`                       | Set `project` for a secondary lock that selects the project's runtime dependencies instead. |
| `additional-matrix-python`          | empty                                   | Python range for the secondary lock.                                                        |
| `additional-matrix-platforms`       | empty                                   | Space-separated Nab platform IDs for the secondary lock.                                    |
| `additional-matrix-implementations` | empty                                   | Space-separated implementations for the secondary lock.                                     |
| `exclude-newer`                     | `7 days`                                | Cutoff for the tools the Actions install from PyPI, see [cutoffs](locked-tools.md#cutoffs). |
| `exclude-newer-package`             | empty                                   | Newline-separated `name=date` overrides of that cutoff.                                     |

Secret: `RELEASE_APP_PRIVATE_KEY` (required). No outputs.

Pitfalls:

- `pylock.toml` must come from `nab lock --all-groups --all-extras`. Relock a `release-creator locks` lock with Nab
  before re-pinning.
- Tests install test, type, and documentation tools afresh to catch upstream dependency changes; only release jobs use
  the locked groups.
- The workflow never updates a committed `uv.lock`. Build constraints come from the lock's `build` group at runtime.
- With a secondary lock, pass the same `additional-lock` and matrix inputs to
  [`validate-news`](pr-checks.md#check-pull-request-news-validate-news) in the PR workflow. It then checks changes to
  either lock against the project, including a PR that changes only the secondary lock.

## Bump dependency floors: `update-python-dependencies.yaml`

The workflow bumps the direct requirements in the files you name with `bump-deps-index`, regenerates `pylock.toml`, runs
the repository's hooks, and opens a dependency pull request. Choose `kind` by what you ship:

- `kind: app` (default): every bumped floor waits out the cooldown, and so does every locked release.
- `kind: library`: the groups in `fresh-groups` take their newest release at once, passing
  `--exclude-newer-group GROUP=false` for each, so tests run against what users install. Every other group, the build
  backend, and the hooks stay cooled.

```yaml
name: Update Python dependencies
on:
  workflow_dispatch:
    inputs:
      cooldown:
        description: Upload age a bumped release needs, such as 7 days; 0 days turns the cooldown off
        type: string
        default: 7 days
      expedite:
        description: Space-separated packages whose newest release skips the cooldown for this run
        type: string
        default: ""
  schedule:
    - cron: 0 8 * * 2
permissions: {}
jobs:
  update:
    permissions:
      contents: read
    uses: tox-dev/github-workflows/.github/workflows/update-python-dependencies.yaml@SHA
    with:
      files: |
        pyproject.toml tox.toml
      cooldown: ${{ inputs.cooldown || '7 days' }}
      expedite: ${{ inputs.expedite || '' }}
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

| Input                   | Default                                                          | Purpose                                                                                                                                                                                                                           |
| ----------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `files` **(required)**  |                                                                  | Newline-separated groups. Each line is one `bump-deps-index --file` run over its space-separated paths, so a file that needs a different cutoff belongs on its own line. Paths must be plain relative paths, without `..`.        |
| `cooldown`              | `7 days`                                                         | Upload age a bumped release needs, `N days` only. `0 days` turns the bump cooldown off for the run.                                                                                                                               |
| `expedite`              | empty                                                            | Whitespace-separated package names that take their newest release for this run, past the cooldown. It changes only the bump: a locked package also needs a committed `[tool.nab.packages.NAME]` exception, which later runs keep. |
| `kind`                  | `app`                                                            | `app` or `library`, see above. Any other value fails.                                                                                                                                                                             |
| `fresh-groups`          | `project test`                                                   | Groups `kind: library` keeps fresh. `project` means the `[project]` runtime dependencies and extras. Names are validated; ignored for `app`; `library` needs at least one.                                                        |
| `exclude-newer`         | `7 days`                                                         | Cutoff for installing `bump-deps-index` and the locked tools. The tool is tooling, so the default keeps it cooled.                                                                                                                |
| `exclude-newer-package` | empty                                                            | Newline-separated `name=date` overrides; a dated entry admits a tool release younger than the cutoff.                                                                                                                             |
| `allowed-paths`         | empty                                                            | Newline-separated globs for files a repository hook rewrites, such as a generated README. `pylock.toml` and every path in `files` are always allowed.                                                                             |
| `branch`                | `update-python-dependencies`                                     | Passed to `open-maintenance-pr`.                                                                                                                                                                                                  |
| `title`                 | `Update Python dependencies`                                     | Pull request title and commit subject.                                                                                                                                                                                            |
| `body`                  | `Update dependency floors and the lock from the scheduled scan.` | Pull request body.                                                                                                                                                                                                                |
| `labels`                | empty                                                            | Newline-separated labels; each must exist.                                                                                                                                                                                        |

Secret: `RELEASE_APP_PRIVATE_KEY` (required). No named output. Remote effect: one dependency pull request into `main`
through `open-maintenance-pr`, or none when nothing changed.

How the read-only job runs:

1. Installs the caller's locked `release-prepare` group, so the caller's `pylock.toml` needs that group, and
   `bump-deps-index` (a release that supports `--exclude-newer-group` and `--exclude-newer-package`) under
   `exclude-newer`.
1. Runs `bump-deps-index` once per `files` line.
1. Runs [`refresh-release-lock`](locked-tools.md#refresh-release-lock) to upgrade the lock with Nab. A lock whose only
   change is Nab's `created-at` stamp is restored, so a timestamp alone never opens a pull request.
1. Runs [`cooled-prek`](locked-tools.md#run-prek-under-the-cutoff-cooled-prek) `run --all-files` once. Hooks may rewrite
   files; a hook failure that changes nothing fails the job, and the pull request's checks verify the rewritten result.
   Put a repository's own formatting, README generation, and other steps in its prek hooks.

## Open a maintenance pull request: `open-maintenance-pr.yaml`

Use this for any generated change your own read-only job produces. Run the repository's hooks and generation in that
job, before the artifact exists; the reusable workflow never runs project code.

The caller writes the change as a binary Git patch named `maintenance.patch`, uploads it as an artifact, and passes the
artifact ID. The artifact name is free, but give it one unique within the run: two maintenance workflows in one run that
share a name make the download fail with `None of the provided artifact IDs were found`.

The workflow runs two jobs:

- `validate` applies the patch to a scratch index, leaving the checkout unchanged, and checks that every changed path
  matches `allowed-paths` and that each change adds, modifies or deletes a regular non-executable file. A patch that
  changes nothing fails. It records the patch digest.
- `open` is the only job that mints the App token, with Contents and Pull requests write for this repository only. It
  runs in the `release-auth` environment, verifies the digest `validate` recorded, commits as `github-actions[bot]`, and
  force-pushes `branch` with a lease. It then edits the open pull request from `branch` into `base`, adding `labels`, or
  opens one. Runs for the same branch are serialized and never cancelled.

```yaml
jobs:
  generate:
    runs-on: ubuntu-26.04
    permissions:
      contents: read
    outputs:
      artifact-id: ${{ steps.upload.outputs.artifact-id }}
    steps:
      # ... produce the changes in the working tree, then write $RUNNER_TEMP/maintenance.patch
      - id: upload
        uses: actions/upload-artifact@UPLOAD_SHA
        with:
          name: maintenance-patch-diagrams
          path: ${{ runner.temp }}/maintenance.patch
          if-no-files-found: error
  open:
    needs: generate
    permissions:
      contents: read
    uses: tox-dev/github-workflows/.github/workflows/open-maintenance-pr.yaml@SHA
    with:
      artifact-id: ${{ needs.generate.outputs.artifact-id }}
      allowed-paths: |
        docs/*.md
        site/static/diagrams/*.svg
      branch: automation/update-diagrams
      title: Update diagrams
      body: Regenerate the diagrams from the scheduled scan.
      labels: skip news
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

| Input                          | Default | Purpose                                                                                                                |
| ------------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------- |
| `artifact-id` **(required)**   |         | ID of the patch artifact from the same workflow run.                                                                   |
| `allowed-paths` **(required)** |         | Newline-separated shell glob patterns: an exact path or a glob. Dots are literal, and `*` also matches `/`.            |
| `branch` **(required)**        |         | Branch holding the maintenance commit. A later run force-pushes it with a lease, replacing the earlier commit.         |
| `base`                         | `main`  | Branch the pull request targets.                                                                                       |
| `title` **(required)**         |         | Pull request title, also the commit subject.                                                                           |
| `body`                         | empty   | Pull request body.                                                                                                     |
| `labels`                       | empty   | Newline-separated labels to add. Each label must already exist in the repository; an existing PR keeps its old labels. |

Secret: `RELEASE_APP_PRIVATE_KEY` (required). The caller grants its job `contents: read`.

Remote effect: one force-pushed commit on `branch` and one pull request into `base`. An open pull request on the same
branch is updated; two open pull requests on one branch fail. The `open` job records the pull request number, but the
workflow declares no `workflow_call` output, so the caller cannot read it.

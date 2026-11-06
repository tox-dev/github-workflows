# Pull request checks

A typical repository requires two checks on `main`: one gate job in its check workflow, and the news fragment job in a
separate news workflow. Everything else feeds the gate: tests, type checks, and the release dry run.

| Piece                                                                          | Kind              | Role                                                                  |
| ------------------------------------------------------------------------------ | ----------------- | --------------------------------------------------------------------- |
| [`check.yaml`](#run-tox-environments-checkyaml)                                | reusable workflow | One job per tox environment.                                          |
| [Release dry run](#release-dry-run)                                            | caller job        | Assembles the next release without pushing it.                        |
| [`required-checks`](#gate-on-needed-jobs-required-checks)                      | Action            | The gate: fails unless every needed job succeeded.                    |
| [`validate-news`](#check-pull-request-news-validate-news)                      | Action            | Requires a news fragment on human pull requests; checks lock changes. |
| [`build-python-distribution`](#build-a-distribution-build-python-distribution) | Action            | Keyless wheel and sdist build for existing PR build jobs.             |

## Run tox environments: `check.yaml`

For a Python library tested with tox. It runs one job per `include` row: it installs tox with uv under the
`exclude-newer` cutoff, sets up the environment with `--notest --skip-missing-interpreters false`, then runs it with
`--skip-pkg-install`. It ends with a gate of its own over the rows. The caller keeps its own gate too, so the required
check name stays in the caller.

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
    uses: tox-dev/github-workflows/.github/workflows/check.yaml@SHA
    permissions:
      contents: read
    with:
      include: |
        [
          {"env": "3.15"},
          {"env": "3.15t", "python": "3.15t"},
          {"env": "3.14", "python": "3.14"},
          {"env": "type"},
          {"env": "pkg_meta"}
        ]
  gate:
    name: 🚦 Required checks pass
    if: ${{ !cancelled() }}
    needs: [test]
    runs-on: ubuntu-26.04
    permissions: {}
    steps:
      - uses: tox-dev/github-workflows/required-checks@SHA
        with:
          needs: ${{ toJSON(needs) }}
```

| Input                    | Default              | Purpose                                                                                                                                                                                              |
| ------------------------ | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `include` **(required)** |                      | JSON array of rows. Each needs `env`, the tox environment. `python` is a uv interpreter installed before tox runs, such as `3.15t`; leave it out for the runner's Python. `os` overrides the runner. |
| `os`                     | `ubuntu-26.04`       | Runner for rows without `os`.                                                                                                                                                                        |
| `apt-packages`           | empty                | Space-separated Ubuntu packages installed on Linux jobs before tox, such as `graphviz`.                                                                                                              |
| `tox-install`            | `tox --with tox-uv`  | Arguments to `uv tool install` that put tox and its plugins on `PATH`. A project that is tox-uv itself passes `tox --with .`.                                                                        |
| `exclude-newer`          | `7 days`             | Cutoff for the tox install. The tox environments themselves install fresh dependencies.                                                                                                              |
| `exclude-newer-package`  | empty                | Newline-separated `name=date` overrides.                                                                                                                                                             |
| `pytest-addopts`         | `-vv --durations=20` | `PYTEST_ADDOPTS` for the run.                                                                                                                                                                        |
| `diff-against`           | `HEAD`               | `DIFF_AGAINST` for the run, a Git revision.                                                                                                                                                          |
| `coverage`               | `false`              | `true` uploads each job's `.tox/.coverage.*` as `.coverage.<os>.<env>`, kept three days; a job with no coverage file fails.                                                                          |

To merge coverage, add a caller job that downloads with `actions/download-artifact` using the pattern `.coverage.*` and
runs its coverage environment.

Check names are `<caller job name> / 🧪 <env> on <os>`; with the example's `🧪 Test` caller job,
`🧪 Test / 🧪 3.15 on ubuntu-26.04`. The reusable gate shows up as `🧪 Test / 🚦 Required checks pass`; require the caller's
gate, not that one. The test jobs run project code, so grant them `contents: read` only.

## Run hooks under the cooldown: `cooled-hooks.yaml`

pre-commit.ci and a contributor's machine build hook environments from the newest releases. The scheduled maintenance
pull requests and release preparation build them with packages from the last seven days held back. A hook bumped to a
release younger than that, or one that rewrites files when its environment is built fresh, passes the pull request and
then fails those scheduled jobs. This workflow runs every hook over the whole tree the way they do, so the pull request
fails instead.

```yaml
  hooks:
    name: 🧹 Hooks under the cooldown
    uses: tox-dev/github-workflows/.github/workflows/cooled-hooks.yaml@SHA # 6.7.0
    permissions:
      contents: read
  gate:
    name: 🚦 Required checks pass
    if: ${{ !cancelled() }}
    needs: [test, hooks]
```

| Input                   | Default  | Meaning                                                                                |
| ----------------------- | -------- | -------------------------------------------------------------------------------------- |
| `exclude-newer`         | `7 days` | Upload cutoff for the lock reader that installs the caller's locked `release-prepare`. |
| `exclude-newer-package` | empty    | Newline-separated `name=date` cutoffs that override `exclude-newer` for one package.   |

prek comes from the caller's `release-prepare` lock group. Hook environments read cutoff exceptions from `[tool.nab]` in
`pyproject.toml`, as [`cooled-prek`](locked-tools.md#run-prek-under-the-cutoff-cooled-prek) describes. The prek cache is
keyed on `.pre-commit-config.yaml` and `pyproject.toml`, so a changed hook or exception rebuilds its environment.

## Release dry run

Add the caller's prepare workflow as a job with `dry-run: true` and list it in the gate's `needs`. The pull request then
fails when merging it would break the next release, for example a changelog formatter hook bumped to a release younger
than the seven-day cutoff, or a fragment the changelog build rejects. Keeping every other hook installable under the
cutoff is a job for the pull request's own formatting check. Setup and pitfalls are in
[Prepare and tag a release](release-prepare.md#dry-run-on-pull-requests).

```yaml
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
```

## Gate on needed jobs: `required-checks`

Fails unless every job in the `needs` context succeeded; jobs named in `allow-skipped` may also end skipped. Use it
instead of an inline `jq` check. Keep the caller's gate job, its name, and `if: ${{ !cancelled() }}`: the name is the
required check, and without the condition a failed dependency skips the gate, which a ruleset reads as passing.

```yaml
gate:
  name: 🚦 Required checks pass
  if: ${{ !cancelled() }}
  needs: [test, type]
  runs-on: ubuntu-26.04
  permissions: {}
  steps:
    - uses: tox-dev/github-workflows/required-checks@SHA
      with:
        needs: ${{ toJSON(needs) }}
```

| Input                  | Default | Purpose                                                                                                                                                                                                     |
| ---------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `needs` **(required)** |         | The `needs` context as `toJSON(needs)`.                                                                                                                                                                     |
| `allow-skipped`        | empty   | Newline-separated job IDs that may end skipped, such as a job that runs on one interpreter only. Each must appear in `needs`; a typo fails the Action and names it. A listed job that succeeded passes too. |

No output, no remote effect. It reads only the `needs` JSON and needs no checkout.

## Check pull request news: `validate-news`

Put the news check in its own workflow, triggered by `opened`, `reopened`, `synchronize`, `labeled`, and `unlabeled`,
and require its job in the main-branch ruleset alongside the gate. A label change then reruns only the news workflow, so
adding `skip news` after opening updates the required check without rerunning the tests.

```yaml
name: Changelog
on:
  pull_request:
    types: [opened, reopened, synchronize, labeled, unlabeled]
permissions: {}
jobs:
  changelog:
    runs-on: ubuntu-26.04
    permissions:
      contents: read
      pull-requests: read
    steps:
      - uses: actions/checkout@CHECKOUT_SHA
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@SETUP_UV_SHA
        with:
          version: latest-known
          python-version: '3.15'
      - uses: tox-dev/github-workflows/install-locked-tools@SHA
        with:
          groups: release-news
          venv: ${{ runner.temp }}/release-tools
      - uses: tox-dev/github-workflows/validate-news@SHA
```

The Action reads `tool.towncrier` from `pyproject.toml` or `towncrier.toml`. Each check runs only when the pull request,
compared with its merge base, touches what it validates:

- **Fragments.** When a file in the configured fragment directory changes, every added or modified fragment is checked
  against the configured categories, filename format, and nonempty content, then `towncrier check` runs against the
  base. Both run through `release-creator validate-news`, so the `release-news` group must hold release-creator and
  Towncrier.
- **Towncrier configuration.** When `towncrier.toml` or the `tool.towncrier` table changes, the configuration is checked
  and the changed fragments are validated.
- **Lock.** When any `pyproject.toml`, `pylock.toml`, a root `pylock.*.toml`, or `nab.toml` changes, it runs
  [`refresh-release-lock`](locked-tools.md#refresh-release-lock) in `check` mode.
- **Lock removal.** A pull request that deletes `pylock.toml` fails while anything still configures Nab: a `[tool.nab]`
  table, a `nab.toml`, or an `additional-lock`.

The fragment requirement is not tied to a file and runs on every pull request: a human pull request without a fragment
needs the `skip news` label; a bot pull request does not. A bot's supplied fragment is still checked and released
normally.

| Input                                                                                                                                                                    | Default                            | Purpose                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `additional-lock`, `additional-lock-groups`, `additional-lock-selection`, `additional-matrix-python`, `additional-matrix-platforms`, `additional-matrix-implementations` | empty; selection `build-or-groups` | The secondary lock, passed to the lock check. Use the same values as [`upgrade-release-tools`](maintenance.md#refresh-the-release-lock-upgrade-release-toolsyaml). |
| `exclude-newer`                                                                                                                                                          | `7 days`                           | Cutoff for the tools the lock check installs.                                                                                                                      |
| `exclude-newer-package`                                                                                                                                                  | empty                              | Newline-separated `name=date` overrides.                                                                                                                           |

Requirements and pitfalls:

- The Action needs a pull request event with a base ref, full history (`fetch-depth: 0`), and a Markdown or
  reStructuredText changelog.
- It reads the pull request's labels from the API rather than from the event, so re-running an older run sees the labels
  the pull request has now. The job needs `pull-requests: read`. It adds no labels and writes nothing to GitHub.
- Opening a pull request with labels, as `gh pr create --label` does, fires `labeled` a moment after `opened`. A label
  event within a minute of opening passes at once, since the run for `opened` reads the labels when it checks.
- Do not cancel runs in progress with a `concurrency` group: the cancelled run shows as a failed check while the other
  passes.

## Build a distribution: `build-python-distribution`

Kept for existing keyless pull request build jobs. It exports hashed build constraints from the caller's lock and builds
the checkout root into a wheel and sdist in `dist/` with uv-managed Python 3.15, with `SOURCE_DATE_EPOCH` set to the
last commit time. It does not upload or publish. Tagged release jobs use
[`validate-python-release.yaml`](release-publish.md#validate-python-releaseyaml) instead.

```yaml
  - uses: tox-dev/github-workflows/build-python-distribution@SHA
```

Inputs: `exclude-newer` (`7 days`) and `exclude-newer-package`, see [cutoffs](locked-tools.md#cutoffs). No named output;
later steps read `dist/`.

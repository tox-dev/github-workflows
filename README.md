# GitHub workflows

Composite actions (called Actions below) and reusable workflows install locked tools, check pull request news, run tox
and CodeQL, prepare releases, push App-authored release commits and tags, publish GitHub Releases, JetBrains plugins,
pre-commit mirrors and LaTeX PDFs, and keep dependencies current. Each repository keeps its dispatch form, publisher,
GitHub environment, and required check names.

## Install locked tools

`install-locked-tools` creates a virtual environment and installs selected groups from the caller's `pylock.toml`. The
caller's full project lock records runtime dependencies, every extra, and every dependency group across supported Python
versions and platforms. CI resolves test, type, and documentation dependencies fresh; release jobs install only the
selected release groups. The Action leaves tracked files unchanged. Source builds use constraints generated from the
lock's `build` group under the runner's temporary directory. A lock without a `build` group exports an empty constraints
file.

Installs are hash-checked. Lock integrity comes from Nab: `refresh-release-lock` in `check` mode regenerates the lock
and fails if it differs. It runs on pull requests through `validate-news`. The cutoff and any per-package exception live
in the caller's `[tool.nab]` table.

Select the groups each job needs. The shared prepare workflow uses `release-prepare`. A full lock records each group and
extra, but a new combination still needs an install check before a caller uses it.

- `venv`: directory for the virtual environment when `groups` is set.
- `groups`: whitespace-separated release dependency groups. Leave empty to export build constraints without installing
  release tools.
- `constraints-lock`: lock used to export build constraints; defaults to `pylock.toml`. Use a secondary lock when the
  build matrix differs from the release-tool matrix.
- `target-platform` and `targets`: Nab platform ID and space-separated `full-version:implementation` pairs for build
  constraints. Pass both when exporting constraints for a specific build target; otherwise the runner selects the
  target.
- `exclude-newer` and `exclude-newer-package`: cutoffs for the lock reader the Action installs from PyPI, see
  [Tools the Actions install](#tools-the-actions-install).

The `build-constraints` output names the hashed constraints file. The Action adds installed command launchers to
`GITHUB_PATH` for later steps while leaving the runner's `python`, `pip`, and `uv` commands on their original paths. Run
`actions/checkout` and `astral-sh/setup-uv` with Python 3.15 before it.

## Tools the Actions install

The Actions install the tools they run themselves, such as Nab, `packaging`, `certifi`, and `pypi-attestations`, from
PyPI with `uv pip install --exclude-newer`, without hashes. Each tool has only a minimum version, such as `nab>=0.0.22`,
and there is no shared lock, so a tool release reaches callers once it is older than the cutoff. Every Action and
reusable workflow that installs such a tool takes two inputs:

- `exclude-newer`: the cutoff, `7 days` by default. uv accepts a timestamp or a duration.
- `exclude-newer-package`: newline-separated `name=date` pairs, each passed to uv as `--exclude-newer-package`, to let a
  single package past the cutoff in an emergency.

```yaml
  - uses: tox-dev/github-workflows/refresh-release-lock@SHA
    with:
      mode: check
      exclude-newer-package: |
        nab=2026-10-24T00:00:00Z
```

The tools the caller's release jobs run, such as release-creator, Towncrier, and prek, still come hash-checked from the
caller's `pylock.toml`.

## Expire cutoff exceptions

A `[tool.nab]` exception that admits one package past the cutoff, `packages.<name>.uploaded-prior-to`, carries its
expiry date in a comment directly above the package table header or dotted key:

```toml
# expires 2026-11-09
[tool.nab.packages.release-creator]
uploaded-prior-to = 2026-11-02T21:45:00Z
```

Nab rejects unknown keys in a package table, so the date cannot sit beside the value. The date is the last day the
exception is valid. The check fails when an exception has no such comment, a malformed date, or a date that has passed,
and names the package. A standalone `nab.toml` is checked the same way. An exception in `[[tool.nab.package-rules]]` is
rejected, since the check does not read those tables; move it to a package table.

The check runs in three places:

- `upgrade-release-tools.yaml`, before it refreshes the lock. Every caller's scheduled run therefore fails on an expired
  or undated exception, even when no release input changed.

- `refresh-release-lock` in `check` mode, which `validate-news` calls when a pull request changes `pyproject.toml`,
  `pylock.toml`, a root `pylock.*.toml`, or `nab.toml`.

- The `check-nab-exceptions` Action on its own. It reads `pyproject.toml` and `nab.toml` from the checkout and takes no
  inputs:

  ```yaml
  - uses: tox-dev/github-workflows/check-nab-exceptions@SHA
  ```

Hook environments install under the same seven-day upload cutoff, with the repository's uv settings ignored. A package
with a `packages.<name>.uploaded-prior-to` exception in `[tool.nab]` is admitted up to that date in hook environments
too, so a hook dependency pinned to a release newer than the cutoff, such as `sphinx` for `docstrfmt`, needs the same
temporary exception the release lock uses. Delete the exception once the release is a week old.

## Refresh release tools

Call `upgrade-release-tools.yaml` from a scheduled or manual workflow. Its read-only job refreshes the universal
`pylock.toml` with `nab lock --all-groups --all-extras --no-cache --upgrade`, which records runtime dependencies, all
extras, and all dependency groups. The project's `[tool.nab]` table sets the cutoff and any per-package exception; the
caller adds and removes those exceptions itself. uv only installs tools and never resolves the lock.

The job uploads a patch, which may change only `pylock.toml` and an explicitly configured secondary Nab lock. The writer
checks the patch before minting the App token. It then opens or updates one dependency PR from
`automation/update-release-tools` to `main`. A lock update runs the normal PR checks before merge.

The writer uses a repository-only release App with Contents and Pull requests write access. Install the App on this
repository, set `RELEASE_APP_CLIENT_ID` as a repository variable, and store `RELEASE_APP_PRIVATE_KEY` in the
`release-auth` environment. Restrict that environment to `main`. Create `dependencies` and `skip news` labels, and allow
the App to push the dependency branch. The caller supplies the secret by name; GitHub requires this mapping even when
the key exists only in the writer job's environment.

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

`pylock.toml` must come from `nab lock --all-groups --all-extras`; relock a `release-creator locks` lock with Nab before
re-pinning. Tests install test, type, and documentation tools afresh to detect upstream dependency changes. The updater
also refreshes a caller's secondary Nab build-matrix lock when `additional-lock` and its matrix inputs are set.

The optional `pull-request-title` and `pull-request-body` inputs replace the default text, and the title is also the
commit subject. The workflow never updates a committed `uv.lock`. Build constraints are generated from the lock's
`build` group at runtime.

For a second lock such as `pylock.build.toml`, set `additional-lock`, `additional-matrix-python`,
`additional-matrix-platforms`, and `additional-matrix-implementations`. `additional-lock-groups` selects dependency
groups in that lock; with no groups, the updater selects build requirements. Set `additional-lock-selection: project`
for a lock that selects the project's runtime dependencies instead. The updater writes both locks in the same dependency
PR. The writer accepts only those locks. Pass the same `additional-lock` and matrix inputs to `validate-news` in the PR
workflow. It checks changes to either lock against the project, including a PR that changes only the secondary lock.

`refresh-release-lock` is the read-only half of the updater. In `refresh` mode, it upgrades the full primary lock and
writes `$RUNNER_TEMP/maintenance.patch` if a lock changes. In `check` mode, it regenerates the primary lock without
upgrading and fails if anything other than Nab's recorded command line differs.

Check mode installs the Nab version that the committed `pylock.toml` records in `[tool.nab] nab-version`, and fails if
the lock has none, because a newer Nab would rewrite that field in every committed lock. Refresh mode installs the
newest Nab under the cutoff. Every Nab run unsets `SSL_CERT_FILE` and `SSL_CERT_DIR`, so Nab uses its own certificate
store.

`validate-news` calls check mode when a PR changes release inputs, including a workspace member's `pyproject.toml` or a
secondary lock. The resulting PR's normal formatting job runs `prek`; the writer checks patch paths and modes. Its
`changed` output is `true` only when the refresh produces a patch. Neither mode pushes a branch or requests a write
token.

Shared workflows run every `prek` command through the `cooled-prek` Action, which passes
`--config .pre-commit-config.yaml`. Without that flag, prek prefers a root `prek.toml` and also runs nested
configurations, which no guard checks.

## Update Python dependencies

`update-python-dependencies.yaml` bumps the direct requirements in the files you name, regenerates `pylock.toml`, runs
the repository's hooks, and opens a dependency pull request. With `kind: app` (default) every bumped floor waits out the
cooldown, and so does every locked release. With `kind: library`, the groups in `fresh-groups` take their newest release
at once, and every other group waits.

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

- `files` **(required)**: Newline-separated groups. Each line is one `bump-deps-index --file` run over its
  space-separated paths, so a file that needs a different cutoff belongs in its own run. Paths are plain relative paths.
- `cooldown`: Upload age a bumped release needs; `7 days` by default, `N days` only. `0 days` turns the bump cooldown
  off for the run.
- `expedite`: Whitespace-separated package names. Each one takes its newest release for this run, past the cooldown. It
  changes only the bump. The lock still follows the cutoff in the caller's `[tool.nab]` table, so a locked package needs
  a committed `[tool.nab.packages.NAME]` exception, which the next run keeps.
- `kind`: `app` (default) cools every bump. `library` keeps the `fresh-groups` dependencies fresh, passing
  `--exclude-newer-group GROUP=false` for each, and cools the rest. Its tooling groups, the build backend, and the hooks
  stay cooled.
- `fresh-groups`: Space-separated dependency groups for `kind: library`, default `project test`. `project` is the
  `[project]` runtime dependencies and extras. The group names are validated, and the list is ignored for `app`.
- `exclude-newer` and `exclude-newer-package`: The upload cutoff for the `bump-deps-index` install from PyPI, `7 days`
  by default, and newline-separated `name=date` overrides for it. The tool itself is tooling, so the default keeps it
  cooled. A dated package override admits a tool release that is younger than the cutoff.
- `allowed-paths`: Newline-separated glob patterns for files that a repository hook rewrites, such as a generated
  README. `pylock.toml` and every path in `files` are always allowed.
- `branch`, `title`, `body`, `labels`: Passed to `open-maintenance-pr`. Defaults: `update-python-dependencies`,
  `Update Python dependencies`, and no labels.

The workflow installs the locked release tools from the caller's `release-prepare` group, so the caller's `pylock.toml`
needs that group. It runs `refresh-release-lock` to upgrade the lock with Nab, then runs `cooled-prek` once. Hooks may
rewrite files; a hook failure that changes nothing fails the job, and the pull request checks verify the rewritten
result. Put a repository's own formatting, README generation, and other steps in its prek hooks. Besides the locked
release tools, it installs Nab from PyPI under the seven-day cutoff, and `bump-deps-index` under `exclude-newer`, at a
release that supports `--exclude-newer-group` and `--exclude-newer-package`.

**Output:** No named output. **Remote effect:** Through `open-maintenance-pr`, one dependency pull request into `main`,
or none when nothing changed.

## Open a maintenance pull request

`open-maintenance-pr.yaml` opens or updates one pull request from a patch that a read-only job of the caller uploaded.
The caller uploads the patch as an artifact named `maintenance-patch` and passes its artifact ID.

The reusable workflow runs two jobs. `validate` applies the patch to a scratch index and leaves the checkout unchanged,
then checks that every changed path matches `allowed-paths` and that each change is a regular non-executable file or a
deletion. `open` is the only job that mints the App token. It runs in the `release-auth` environment, verifies the patch
digest that `validate` recorded, commits, and force-pushes `branch` with a lease. It then edits the open pull request
from `branch` into `base`, or opens one.

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
          name: maintenance-patch
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

- `artifact-id` **(required)**: ID of the `maintenance-patch` artifact from the same workflow run.
- `allowed-paths` **(required)**: Newline-separated shell glob patterns. A pattern is an exact path or a glob. Dots are
  literal, and `*` also matches `/`.
- `branch` **(required)**: Branch that holds the maintenance commit. A later run force-pushes it with a lease, replacing
  the earlier commit.
- `base`: Branch the pull request targets; default `main`.
- `title` **(required)**: Pull request title, also the commit subject.
- `body`: Pull request body.
- `labels`: Newline-separated labels to add. Each label must already exist in the repository.

The caller grants `contents: read` to its job and passes `RELEASE_APP_PRIVATE_KEY`. The App needs Contents and Pull
requests write access on this repository only, as for `upgrade-release-tools`. Repository hooks and the caller's own
generation run in the read-only job, before the artifact exists. The reusable workflow never runs project code.

**Output:** `number`, the pull request number. **Remote effect:** One force-pushed commit on `branch` and one pull
request into `base`. An open pull request with the same branch is updated; two open pull requests on one branch fail.

The `open` job refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`, and `merge_group`
callers. Its first step fails with an error that names the event, before the checkout and before the App token exists.
Trigger the caller on `push`, `schedule`, `workflow_dispatch`, or `release`.

## Check pull request news

`validate-news` reads `tool.towncrier` from `pyproject.toml`. It checks every added or modified fragment in the
configured directory against the configured categories, filename format, and nonempty content. A valid fragment runs
`towncrier check` against the PR base. A human PR without a fragment needs `skip news`; a bot PR without a fragment does
not. A bot's supplied fragment is checked and included in the normal release flow. The Action reads repository files and
Git history and reads the PR's current labels; it does not add labels or write to GitHub.

Each check runs only when the pull request touches what it validates, compared with the merge base:

- Fragment validation runs when a file in the configured fragment directory changes.
- The Towncrier configuration is checked when `towncrier.toml` or the `tool.towncrier` table of `pyproject.toml`
  changes; such a change also validates the changed fragments.
- The lock check runs `refresh-release-lock` in `check` mode when any `pyproject.toml`, `pylock.toml`, a root
  `pylock.*.toml`, or `nab.toml` changes.
- The lock-removal guard runs when the pull request deletes `pylock.toml`.

The requirement for a fragment on human PRs is not tied to a file and runs on every pull request.

Put the `changelog` job in a separate `news.yaml` workflow triggered by `opened`, `reopened`, `synchronize`, `labeled`,
and `unlabeled`. Require its status in the main-branch ruleset alongside the gate job. A label change then runs only the
news workflow. Install Towncrier from the caller's release lock before calling the Action:

```yaml
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

The Action expects a pull request base ref and a Markdown or reStructuredText changelog. The caller should also run on
`labeled` and `unlabeled` events, so a label added after opening the PR updates the required check. The Action reads the
PR's labels from the API rather than from the event, so re-running an older run sees the labels the PR has now; the job
needs `pull-requests: read` for that.

Opening a PR with labels, as `gh pr create --label` does, fires `labeled` a moment after `opened`. A label event within
a minute of opening passes at once, since the run for `opened` reads the labels when it checks. Do not cancel runs in
progress with a `concurrency` group: the cancelled run would show as a failed check while the other one passes.

## Check a tox library

`check.yaml` is a reusable workflow for a Python library tested with tox. It runs one job per `include` row, installs
tox with uv under the `exclude-newer` cutoff, sets up each tox environment with `--notest`, then runs it with
`--skip-pkg-install`. It ends with its own gate over the rows. The caller keeps a gate of its own, as below, so the
required check name stays in the caller. Pin it to a release commit SHA.

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

- `include` **(required)**: JSON array of matrix rows. Each row needs `env`, the tox environment. `python` is a uv
  interpreter the job installs before tox runs, such as `3.15t`; leave it out for the runner's Python. `os` overrides
  the runner for that row.
- `os`: Runner for rows without `os`; default `ubuntu-26.04`.
- `apt-packages`: Space-separated Ubuntu packages installed on Linux jobs before tox, such as `graphviz`.
- `tox-install`: Arguments to `uv tool install` that put tox and its plugins on `PATH`; default `tox --with tox-uv`. A
  project that is tox-uv itself passes `tox --with .`.
- `exclude-newer` and `exclude-newer-package`: The cutoff for the tox install, as in the Actions above; default
  `7 days`. The tox environments themselves install fresh dependencies.
- `pytest-addopts`: `PYTEST_ADDOPTS` for the test run; default `-vv --durations=20`.
- `diff-against`: `DIFF_AGAINST` for the test run, a Git revision; default `HEAD`.
- `coverage`: `true` uploads each job's `.tox/.coverage.*` as an artifact named for its runner and row, kept three days.
  A caller job merges them with `actions/download-artifact` using the pattern `.coverage.*` and runs its coverage
  environment.

The check names are `<caller job name> / 🧪 <env> on <os>`; the example's caller job is `🧪 Test`. Require the caller's
gate job, not the reusable one. The test jobs run project code, so the caller grants them `contents: read` only.

## Analyze with CodeQL

`codeql.yaml` is a reusable CodeQL workflow. It has one analysis job per language and no triggers, so the caller keeps
its schedule, branches, and pull request events. The caller grants `security-events: write`, because the analysis
uploads results to code scanning.

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

- `languages`: JSON array of CodeQL languages, one job each; default `["actions","python"]`.
- `paths-ignore`: JSON array of paths CodeQL skips, written to its configuration; default `[]`.
- `queries`: Query suite or comma-separated query list; default `security-extended`.
- `config-file`: Repository path to a CodeQL configuration file. Use it instead of `paths-ignore`, which has no effect
  when this is set; the file lists its own paths.
- `build-mode`: `none` (default), `autobuild`, or `manual`, for each language.

Each check name is `<caller job name> / 🛡️ Analyze <language>`. With the caller job named `🛡️ Analyze`, the checks are
`🛡️ Analyze / 🛡️ Analyze actions` and `🛡️ Analyze / 🛡️ Analyze python`. Rulesets that required the earlier
`🛡️ Analyze <language>` name must require the new one. The workflow pins CodeQL Action v4.39.1 for both the init and
analyze steps.

## Require needed jobs

`required-checks` fails unless every job in the `needs` context succeeded. Jobs named in `allow-skipped` may also end
skipped. Keep the caller's gate job, its name, and `if: ${{ !cancelled() }}`, because the name is the required check.
Use the Action instead of an inline `jq` check.

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

- `needs` **(required)**: The `needs` context as `toJSON(needs)`.
- `allow-skipped`: Newline-separated job IDs that may end skipped, such as a job that runs on one interpreter only. Each
  ID must also appear in `needs`; a typo fails the Action and names the typo. A listed job that succeeded passes too.

**Output:** No named output. **Remote effect:** None. The Action reads only the `needs` JSON and needs no checkout.

## Export constraints for a build matrix

`export-build-constraints` reads `pylock.toml` by default. Pass `lock` for a secondary lock such as `pylock.build.toml`,
plus `target-platform` and `targets` when the build matrix needs constraints for specific interpreters. The output
`path` names a temporary requirements file with hashes. The Action writes no tracked files.

```yaml
  - id: constraints
    uses: tox-dev/github-workflows/export-build-constraints@SHA
    with:
      lock: pylock.build.toml
      target-platform: linux_aarch64
      targets: 3.15.0:cpython
```

`targets` is a space-separated list of `full-version:implementation` pairs.

## Build a distribution for a pull request

`build-python-distribution` remains available for existing keyless PR build jobs. It exports hashed build constraints
from the caller's lock, and writes a wheel and sdist to `dist/`. It does not upload or publish them. Tagged release jobs
use `validate-python-release.yaml`.

```yaml
  - uses: tox-dev/github-workflows/build-python-distribution@SHA
```

The Action builds the checkout root and has no named output; subsequent steps read `dist/`.

## Build maturin wheels

`build-maturin-wheels.yaml` builds a maturin extension for a JSON build matrix and uploads the wheels and sdist under
the artifact names the caller's publisher reads. The `source` job checks out the commit, runs the optional pre-build
command once, and uploads the source. Each matrix entry runs in its own `build` job, and the `sdist` job builds the
sdist from the hash-checked build group. The `gate` job runs `required-checks` over `source`, `build`, and `sdist`;
`sdist` may end skipped when the `sdist` input is `false`. Jobs hold `contents: read` at most.

```yaml
jobs:
  build:
    uses: >-
      tox-dev/github-workflows/.github/workflows/build-maturin-wheels.yaml@SHA
    with:
      package-name: pyproject-fmt
      package-path: pyproject-fmt
      matrix: >-
        [
          {"os": "ubuntu-24.04", "target": "x86_64", "artifact": "linux-x86_64", "manylinux": "2_28",
           "python": "3.15 3.14t pypy3.11"},
          {"os": "ubuntu-24.04", "target": "aarch64", "artifact": "linux-aarch64", "args": "--zig"},
          {"os": "ubuntu-24.04", "target": "x86_64", "artifact": "linux-x86_64-315t",
           "python": "3.15t", "args": "--no-default-features --features extension-module"},
          {"os": "windows-2025", "target": "x64", "artifact": "windows-x64", "python": "3.15 3.14t"},
          {"os": "macos-15", "target": "aarch64", "artifact": "macos-aarch64", "python": "3.15 3.14t pypy3.11"}
        ]
      post-build-command: uv run --no-project pyproject-fmt/build_backend.py dist
    permissions:
      contents: read
```

Each matrix entry takes these keys:

- `os`: runner label, used as `runs-on`.
- `target`: Rust target triple passed to maturin.
- `artifact`: suffix of the uploaded `<package-name>-wheels-<artifact>` artifact.
- `python`: space-separated interpreters for `--interpreter`. Leave it out for cross targets, where maturin finds no
  host interpreter; a native entry without it builds for the job's Python 3.15.
- `manylinux`: manylinux or musllinux policy; default `auto`.
- `args`: extra maturin arguments, such as `--zig`.

`package-path` is the directory holding the package's `Cargo.toml`; the sdist is built from it. `release-build` defaults
to `false`, but any tag ref runs in release mode too, so a tag caller can omit it. Release mode and Windows entries
build without sccache, which breaks MSVC builds of C dependencies. `workflow_call` defaults cannot be expressions, so
the workflow combines the two inside.

`pre-build-command` runs once in the source job from the checkout root, so every wheel job builds the same tree. Use it
for a version bump, which must happen before the source artifact is written. `post-build-command` runs in each wheel job
after maturin, from the checkout root with the wheels in `dist`. Vendoring belongs there, because maturin skips the PEP
517 hook that would otherwise vendor files. Both commands run under `bash -c`; the caller installs whatever they need,
such as cargo-edit for `cargo set-version`.

The source job installs the `release-build` group of the caller's `pylock.toml` to read the maturin version. The sdist
job exports constraints from the `build` group. Both groups come from the lock that
[export-build-constraints](#export-constraints-for-a-build-matrix) reads. `exclude-newer` and `exclude-newer-package`
set the upload cutoff for those installs, as in [Tools the Actions install](#tools-the-actions-install). Set
`sdist: false` to skip the sdist job.

What stays in the caller:

- Profile-guided optimization. A PGO leg needs an instrumented build, a training run, and a profile check inside the
  same job. Simplint keeps its four PGO legs in a local job and passes the remaining matrix entries to this workflow.
- Version selection, README generation, and any other changes to the source beyond `pre-build-command`.
- Package checks on the built files, such as an sdist that must carry vendored code. The workflow inspects nothing
  inside the built files; check them in the package's own `tox -e pkg_meta` run.
- Publishing. Keep PyPI trusted publishing in the caller's tag workflow.

## Start with a caller

The [release preparation workflow](.github/workflows/prepare-release.yaml) in this repository calls the reusable
Towncrier workflow. Its `assemble` job uploads a patch. The `push` job downloads that artifact by ID and checks its
paths and modes before minting a repository-scoped App token. Set the tag style in the caller and the changelog path and
fragment directory in committed Towncrier configuration. Pin the reusable workflow to a release commit SHA; `SHA` in
these examples means that commit.

Assembly needs release history to select a tag. The writer can check out the source commit with `fetch-depth: 1`. All
jobs use `persist-credentials: false`. Assembly installs the caller's locked release tools and needs `contents: read`
and `pull-requests: read` to resolve PR authors. It starts `prek install-hooks` while building the changelog, then waits
for the hooks before formatting and uploading the patch. The writer uses the `release-auth` environment with
`RELEASE_APP_PRIVATE_KEY` and `RELEASE_APP_CLIENT_ID`. Restrict that environment to `main`. Install the App on this
repository only, with Contents write and Metadata read, and grant the necessary branch and tag ruleset bypass.

```text
main + fragments
       │
       ▼
prepare-towncrier ──► upload patch
                            │
                            ▼
                verify paths and modes
                            │
                            ▼
                 mint App token ──► commit-and-tag ──► main + tag
```

The tag starts the caller's publisher. Keep PyPI trusted publishing in that top-level workflow, in a separate job with
`id-token: write` because
[PyPI disallows reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/). Repositories with the
standard `uv` wheel and sdist build can call `validate-python-release.yaml` in the tag publisher. The
[self-release workflow](.github/workflows/release.yaml) shows the GitHub Release path; callers keep their ecosystem
uploads. The tag caller renders the Release body with `release-notes.yaml` and creates the Release with
`github-release.yaml`, as in
[Render release notes and publish the GitHub Release](#render-release-notes-and-publish-the-github-release).

## Prepare and tag with one reusable workflow

`prepare-towncrier-release.yaml` runs two jobs. `assemble` selects a tag and uploads a Towncrier patch without the App
key. `push` downloads that artifact by ID, checks its paths and file modes, reads the caller's `release-auth`
environment, and uses a repository-scoped App token to push the release commit and tag together.

```yaml
jobs:
  prepare:
    uses: >-
      tox-dev/github-workflows/.github/workflows/prepare-towncrier-release.yaml@SHA
    permissions:
      contents: read
      pull-requests: read
    with:
      bump: ${{ inputs.bump }}
      tag-prefix: v
      annotated: true
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

The caller supplies the `release-auth` environment secret by name; the App client ID comes from that environment's
`RELEASE_APP_CLIENT_ID` variable. The App token requests Contents write for this repository only. The caller grants its
GitHub token Contents and Pull requests read. Assembly installs `release-prepare`, which contains release-creator,
Towncrier, and prek. No job output crosses back to the caller. A successful run pushes a tag, which the caller's tag
workflow handles.

`bump`, `tag-prefix`, and `changelog-prefix` have the same meanings as the `prepare-towncrier` inputs below. `annotated`
selects an annotated tag. `release-auth-deployment` defaults to `true`; set it to `false` if the current App-key job
uses `release-auth` without creating a GitHub Deployment. The caller can place repository-specific checks in a preceding
job and make this job depend on it. One dispatch prepares one tag; run separate dispatches for separate packages. The
tag-triggered ecosystem publisher stays in the caller repository.

The `push` job refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`, and `merge_group`
callers. Its first step fails with an error that names the event, before the patch is downloaded and before the App
token exists. Trigger the caller on `push`, `schedule`, `workflow_dispatch`, or `release`.

### Dry run on pull requests

A release assembles under rules a pull request's own checks never apply: hooks install with packages from the last seven
days held back, fragments link to their pull requests, and the changelog builds and formats. A pull request that breaks
any of these merges green and fails the next release. `dry-run: true` runs `assemble` alone and skips `push`, so the
pull request fails instead. A dry run needs no App key and uses its own concurrency group per ref, so it never queues
behind a real release.

Make the caller's prepare workflow callable and run it from the workflow that holds the required gate, so the dry run
uses the same inputs as the release:

```yaml
# prepare-release.yaml
on:
  workflow_dispatch:
    inputs:
      bump:
        type: choice
        options: [auto, major, minor, patch]
        default: auto
  workflow_call:
jobs:
  prepare:
    uses: >-
      tox-dev/github-workflows/.github/workflows/prepare-towncrier-release.yaml@SHA
    permissions:
      contents: read
      pull-requests: read
    with:
      bump: ${{ inputs.bump || 'auto' }}
      dry-run: ${{ github.event_name != 'workflow_dispatch' }}
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

```yaml
# check.yaml
jobs:
  release:
    uses: ./.github/workflows/prepare-release.yaml
    permissions:
      contents: read
      pull-requests: read
  gate:
    needs: [release, test]
```

`prepare-release-creator.yaml` takes the same `dry-run` input.

## Read Towncrier configuration

`read-towncrier-config` reads `towncrier.toml` or `pyproject.toml` from the checkout's committed `HEAD`, so an untrusted
release patch cannot change the allowed paths.

```yaml
  - id: towncrier
    uses: tox-dev/github-workflows/read-towncrier-config@SHA
  - env:
      CHANGELOG: ${{ steps.towncrier.outputs.changelog }}
    run: printf '%s\n' "$CHANGELOG"
```

Outputs are `changelog`, `fragments`, and `format`: `rst` for a `.rst` changelog, otherwise `markdown`. The Action does
not modify the checkout or GitHub state.

## Prepare Towncrier release

`prepare-towncrier` chooses the next version, links fragments to their squash PRs, runs Towncrier and the selected
formatter hook through `prek`, then writes a binary Git patch at `$RUNNER_TEMP/release.patch`. It reads the changelog
path, fragment directory, and Markdown or RST format from committed Towncrier configuration through
`read-towncrier-config`. It does not commit or push. Version selection, fragment linking, the Towncrier build, and
formatting must all succeed.

```yaml
  - id: prepare
    uses: tox-dev/github-workflows/prepare-towncrier@SHA
    with:
      bump: ${{ inputs.bump }}
```

- `bump`: `auto` (default), `major`, `minor`, or `patch`. Passed to `release-creator tags --next`; `auto` uses the
  pending fragments. The caller's dispatch form decides which choices to expose.
- `tag-prefix`: Empty by default. Use `v` when release tags are spelled `v1.2.3`; version comparison still includes
  unprefixed numeric tags in the repository's history. This does not set the changelog heading prefix.
- `changelog-prefix`: Empty by default, so Towncrier writes `1.2.3` even if the tag is `v1.2.3`. Set `v` for a changelog
  whose release headings use `v1.2.3`.
- `version`: Explicit version for a caller with its own version selector. It takes precedence over `bump`.
- `phase`: `all` (default) runs the complete Action. The reusable workflow uses `build` to select the version, link
  authors, and build the changelog while hooks install; it then uses `finalize` to format, render, and write the patch.
  Pass the version selected by `build` to `finalize`.

The committed `tool.towncrier` configuration gives the `filename` and `directory`. `docstrfmt` formats a `.rst`
changelog and `mdformat` any other; the formatter must be a configured `prek` hook. The Action writes the patch at
`$RUNNER_TEMP/release.patch`; the reusable workflow uploads it by artifact ID.

**Output:** `version` is the selected tag string. Use `steps.prepare.outputs.version` as a job output and pass it to
both later Actions. **Working-tree effect:** Towncrier changes the changelog and consumes fragments; the patch records
those changes.

## Validate release patch

`validate-release-patch` applies the uploaded patch in the writer's checkout, checks its changed paths and file modes,
and leaves it staged for the commit Action. Download the patch artifact to `${{ runner.temp }}/release-patch` first. It
needs no release tools.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@SHA
```

**Output:** No named output. **Working-tree effect:** Applies and stages the patch. The Action reads the changelog path
and fragment directory from committed Towncrier configuration. Only the changelog and direct fragment deletions may
appear in the patch, as regular files. An unexpected path or mode fails the job. Set `allowed-paths` to
newline-separated glob patterns to replace that path rule: the patch may then change only the matching paths, and the
Towncrier configuration is not read. The [release-creator preparation](#prepare-release-creator-release) sets it.

## Commit and tag release

`commit-and-tag` commits the staged release patch with the GitHub App bot identity, creates the tag, and atomically
pushes the branch and tag to `origin`. A rejected push leaves neither remote ref updated. Mint the token after
validation with `actions/create-github-app-token`, narrowed to this repository and Contents write. Put `commit-and-tag`
last in the writer job: its Git credential helper remains available to later steps.

```yaml
  - id: token
    uses: actions/create-github-app-token@TOKEN_ACTION_SHA
    with:
      client-id: ${{ vars.RELEASE_APP_CLIENT_ID }}
      private-key: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
      owner: ${{ github.repository_owner }}
      repositories: ${{ github.event.repository.name }}
      permission-contents: write
  - uses: tox-dev/github-workflows/commit-and-tag@SHA
    with:
      version: ${{ needs.assemble.outputs.version }}
      token: ${{ steps.token.outputs.token }}
      app-slug: ${{ steps.token.outputs.app-slug }}
      message: release ${{ needs.assemble.outputs.version }}
```

- `version` **(required)**: Tag name to create, such as `1.2.3`.
- `token` **(required)**: Short-lived installation token from the repository-only App. The Action never reads the key.
- `app-slug` **(required)**: `app-slug` output from the token Action, used to resolve the bot's Git identity.
- `message` **(required)**: Commit message. It is also the annotated tag message when `annotated` is `true`.
- `annotated`: `false` (default) creates a lightweight tag; `true` creates an annotated tag. Match the repository's
  existing release history.

**Output:** No named output. **Remote effect:** One new commit on `main` and one tag at that commit. The App needs a
branch and tag ruleset bypass. A stale branch, invalid tag, or ruleset rejection fails the push.

## Prepare release-creator release

`prepare-release-creator.yaml` runs the same two-job split as
[prepare-towncrier-release](#prepare-and-tag-with-one-reusable-workflow). `assemble` has no App key. It selects the tag
from the tags and pending fragments, links fragments to their pull requests, optionally runs `cargo set-version`, runs
the caller's changelog command, adds New Contributors, formats the changelog with the `mdformat` prek hook, and uploads
the patch. `push` downloads that patch by ID, applies it with [validate-release-patch](#validate-release-patch) using
`allowed-paths`, mints a repository-scoped App token, and runs [commit-and-tag](#commit-and-tag-release).

```yaml
jobs:
  prepare:
    uses: >-
      tox-dev/github-workflows/.github/workflows/prepare-release-creator.yaml@SHA
    permissions:
      contents: read
      pull-requests: read
    with:
      bump: ${{ inputs.bump }}
      package: ${{ inputs.package }}
      tag-format: '{package}/{version}'
      cargo-set-version: true
      cargo-set-version-args: -p {package}
      assemble-command: >-
        uv run --project "$PACKAGE" python tasks/generate_readme.py "$PACKAGE" &&
        python3 tasks/assemble_release.py "$PACKAGE" "$VERSION"
      release-paths: |
        CHANGELOG.md
        Cargo.lock
        uv.lock
        {package}/Cargo.toml
        {package}/README.rst
        changelog.d/{package}/*
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

Simplint's single-package release uses unprefixed tags and no package scope:

```yaml
    with:
      bump: ${{ inputs.bump }}
      tag-format: '{version}'
      cargo-set-version: true
      assemble-command: python3 tasks/assemble_release.py "$VERSION"
      release-paths: |
        CHANGELOG.md
        Cargo.lock
        Cargo.toml
        changelog.d/*
```

- `bump`: `auto`, `major`, `minor`, or `patch`, passed to `release-creator tags --next`.
- `package`: scopes tags to `package/` and fragments to `changelog.d/<package>`. Empty for a single-package repository.
- `tag-format`: `{version}`, `v{version}`, `{package}/{version}`, or `{package}/v{version}`. A `{package}` format needs
  `package`, and a format without it rejects `package`.
- `changelog`: tracked Markdown changelog; default `CHANGELOG.md`.
- `assemble-command` **(required)**: shell command that writes the changelog section from the fragments. It runs with
  `PACKAGE`, `VERSION` (the bare number), and `TAG` set, and it may run the package's own build steps first.
- `release-paths` **(required)**: newline-separated glob patterns, the only paths the patch may change. `{package}`
  expands to `package`. Each matched path may be added, modified, or deleted as a regular file; other modes fail.
  `validate-release-patch` does not read the Towncrier configuration in this mode.
- `cargo-set-version`: run `cargo set-version` with the number before assembly; default `false`.
  `cargo-set-version-args` holds the arguments before the number, such as `-p {package}`. Cargo and cargo-edit install
  only when this is set.
- `annotated`, `release-auth-deployment`, `exclude-newer`, `exclude-newer-package`, and `dry-run` match
  `prepare-towncrier-release`.

The caller keeps the `release-auth` environment with `RELEASE_APP_PRIVATE_KEY` and the `RELEASE_APP_CLIENT_ID` variable.
Assembly installs `release-prepare`, which contains release-creator, Towncrier, and prek.

What stays in the caller:

- The changelog. `assemble-command` writes it, because release-creator does not build a `## <package>` section in a
  shared changelog. Simplint's `assemble_release.py` and toml-fmt's package sections both stay in the caller.
- Any Cargo or uv version change beyond `cargo-set-version`, such as `uv version --package` for a second Python package.
- The tag-triggered publisher, which stays in the caller repository.

The `push` job refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`, and `merge_group`
callers. Its first step fails with an error that names the event, before the patch is downloaded and before the App
token exists. Trigger the caller on `push`, `schedule`, `workflow_dispatch`, or `release`.

## Validate a Python release

`validate-python-release.yaml` runs one `build` job. It exports hashed build constraints from the caller lock, builds
the wheel and sdist, and uploads them. The workflow does not inspect the built files further; check package metadata and
wheel contents in the package's own `tox -e pkg_meta` run.

```yaml
build:
  uses: >-
    tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
  permissions:
    contents: read
```

The caller needs a `build` group for backend constraints. `source` defaults to `.`. Use `artifact-prefix` when one tag
produces more than one distribution path; each call then writes a distinct `python-package-distributions` artifact. A
caller pinned to a workflow commit runs that commit's local Actions. Pass the cutoff inputs as for
`refresh-release-lock`.

Publish only after the reusable workflow succeeds. Download the artifact with pinned `download-artifact`
[v8.0.2](https://github.com/actions/download-artifact/blob/9000827ccba6bdab643e8b6fd33ac0654aef8333/action.yml#L37-L45),
using `artifact-ids: ${{ needs.build.outputs.distributions-artifact-id }}`. The download checks the artifact digest and
selects the wheel and sdist from that build run. The caller keeps PyPI OIDC in its `release` environment job.

This reusable workflow does not render notes or create the GitHub Release.
[Render release notes and publish the GitHub Release](#render-release-notes-and-publish-the-github-release) shows the
notes and release jobs that run after the publish job.

## Render release notes and publish the GitHub Release

`release-notes.yaml` renders the GitHub Release body in a read-only job. `github-release.yaml` checks the PyPI files,
then creates the GitHub Release in a job that runs in the caller's `release` environment with `contents: write`. Both
are reusable workflows. The caller keeps the PyPI upload job, because PyPI trusted publishing cannot run in a reusable
workflow.

`release-notes.yaml` takes these inputs and returns one output:

- `tag` **(required)**: release tag, such as `1.2.3` or `pyproject-fmt/1.2.3`.
- `changelog`: tracked changelog path. Empty reads `filename` from the committed Towncrier configuration, so a
  repository without one, such as a multi-package workspace, must set it.
- `artifact-url` and `artifact-label`: passed to `render-release-notes`.
- `package`: package section of a shared Markdown changelog. The previous tag is then the one before the tag in the same
  package namespace.
- Output `artifact-id`: the upload ID of the `github-release-notes-<run attempt>` artifact.

`github-release.yaml` takes these inputs:

- `project` and `version` **(required)**: PyPI project and version that `reconcile-pypi-artifacts` compares with the
  build.
- `tag` **(required)**: Git tag the release targets. The release commit is the workflow's `github.sha`.
- `artifact-pattern` **(required)**: artifact name pattern of the distributions the PyPI publisher uploaded. The
  workflow downloads them into `dist`.
- `notes-artifact-id` **(required)**: the `artifact-id` output of `release-notes.yaml`.
- `title-prefix`: text before the tag in the title, such as `v`. Empty by default.
- `assets-directory`: directory of extra assets. The workflow's only downloaded directory is `dist`, so set `dist` to
  attach the distributions. Empty attaches nothing.

The caller's release-notes job needs `contents: read`. The release job needs `contents: write` and runs after the PyPI
job. The `release` environment must exist in the caller and allow the tag ref. The examples below pin `SHA` to the
commit of this repository.

The pytest-print release workflow:

```yaml
name: 🚀 Release to PyPI
on:
  push:
    tags: ["*"]
permissions:
  contents: read
concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false
jobs:
  build:
    name: 🏗️ Build
    uses: tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
    permissions:
      contents: read
  notes:
    name: 📝 Render GitHub Release notes
    uses: tox-dev/github-workflows/.github/workflows/release-notes.yaml@SHA
    permissions:
      contents: read
    with:
      tag: ${{ github.ref_name }}
      artifact-url: https://pypi.org/project/pytest-print/${{ github.ref_name }}/
  pypi:
    name: 🚀 Publish to PyPI
    needs: build
    runs-on: ubuntu-26.04
    environment:
      name: release
      url: https://pypi.org/project/pytest-print/${{ github.ref_name }}
    permissions:
      id-token: write
    steps:
      - name: 📩 Download distributions
        uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with:
          artifact-ids: ${{ needs.build.outputs.distributions-artifact-id }}
          path: dist/
      - name: 🚀 Publish to PyPI
        uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3
        with:
          packages-dir: dist
          attestations: true
  github-release:
    name: 🚀 Publish GitHub Release
    needs: [build, pypi, notes]
    uses: tox-dev/github-workflows/.github/workflows/github-release.yaml@SHA
    permissions:
      contents: write
    with:
      project: pytest-print
      version: ${{ github.ref_name }}
      tag: ${{ github.ref_name }}
      artifact-pattern: python-package-distributions
      notes-artifact-id: ${{ needs.notes.outputs.artifact-id }}
```

A repository with a shared changelog, such as toml-fmt, sets `package` per package. Its build job is a reusable workflow
of the repository itself, which exposes `version` as an output:

```yaml
name: 🚀 pyproject-fmt
on:
  push:
    tags: ["pyproject-fmt/*"]
permissions: {}
concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false
jobs:
  build:
    name: 🏗️ Build distributions
    uses: ./.github/workflows/pyproject_fmt_build.yaml
    permissions:
      contents: read
      pull-requests: read
  notes:
    name: 📝 Render GitHub Release notes
    uses: tox-dev/github-workflows/.github/workflows/release-notes.yaml@SHA
    permissions:
      contents: read
    with:
      tag: ${{ github.ref_name }}
      package: pyproject-fmt
      artifact-url: https://pypi.org/project/pyproject-fmt/${{ replace(github.ref_name, 'pyproject-fmt/', '') }}/
  pypi:
    name: 🚀 Publish to PyPI
    needs: build
    runs-on: ubuntu-26.04
    environment:
      name: release
      url: https://pypi.org/project/pyproject-fmt/${{ needs.build.outputs.version }}/
    permissions:
      id-token: write
    steps:
      - name: 📩 Download distributions
        uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with:
          pattern: pyproject-fmt-wheels-*
          path: dist
          merge-multiple: true
      - name: 🚀 Publish to PyPI
        uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3
        with:
          packages-dir: dist
  github-release:
    name: 🚀 Publish GitHub Release
    needs: [build, pypi, notes]
    uses: tox-dev/github-workflows/.github/workflows/github-release.yaml@SHA
    permissions:
      contents: write
    with:
      project: pyproject-fmt
      version: ${{ needs.build.outputs.version }}
      tag: ${{ github.ref_name }}
      artifact-pattern: pyproject-fmt-wheels-*
      notes-artifact-id: ${{ needs.notes.outputs.artifact-id }}
```

`release-notes.yaml` passes `package` to `render-release-notes`. The Action's `previous` input still defaults to `auto`,
so callers need no separate `select-previous-tag` step.

The `github-release` job refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`, and
`merge_group` callers. Its first step fails with an error that names the event, before any artifact is downloaded or the
release is written. Trigger the caller on `push`, `schedule`, `workflow_dispatch`, or `release`.

## Render GitHub Release notes

`render-release-notes` checks the tag and its changelog section, finds the previous tag, and renders an unwrapped GitHub
Release body with `release-creator`. Call it on the actual tag in a read-only job with the full history. The release job
creates the Release; this Action only writes a local Markdown file.

```yaml
  - uses: tox-dev/github-workflows/render-release-notes@SHA
    with:
      tag: ${{ github.ref_name }}
      changelog: CHANGELOG.md
      artifact-url: https://pypi.org/project/example/${{ github.ref_name }}/
```

- `tag` **(required)**: Release version, such as `1.2.3`. The checkout must contain its changelog section.
- `changelog` **(required)**: Tracked Markdown or reStructuredText changelog in the format that `release-creator notes`
  parses, with exactly one section for the tag.
- `artifact-url`: Ecosystem release URL, such as a PyPI version page. Omit it for a GitHub-only project. A project that
  publishes several packages puts one URL per line; the links share one line of the body, separated by commas.
- `artifact-label`: Link text for each `artifact-url` line, in the same order; default `PyPI release`. Use `Zipapp` or
  another product name for a different artifact. `release-creator` adds an emoji for the link's ecosystem.
- `previous`: Previous tag, or `auto` (default) to calculate it from Git history.
- `package`: Package section of a shared Markdown changelog, such as `pyproject-fmt`; empty for one package.

The Action reads `GITHUB_REPOSITORY` for PR and comparison links. A repository with a shared changelog, such as
toml-fmt, passes its package name in the `package` input.

**Output:** No named output. **Working-tree effect:** The Action writes only `$RUNNER_TEMP/release-notes.md`. Pass it to
`gh release create --notes-file` only after the ecosystem publisher succeeds. It rejects an invalid tag, a missing
heading, an empty body, or a missing comparison link when an earlier tag exists. It does not write a GitHub Release, so
it needs only read permissions.

## Select the previous release tag

`select-previous-tag` finds the preceding numeric tag using release-creator's version rules. The caller must check out
the tag history and install release-creator first. It reads Git tags and writes one step output; it does not change the
checkout or GitHub state.

```yaml
  - id: previous
    uses: tox-dev/github-workflows/select-previous-tag@SHA
    with:
      tag: ${{ github.ref_name }}
```

`tag` is required. Install `release-creator` on `PATH` before calling the Action. The `previous` output is empty when
this is the first matching release.

## Reconcile PyPI artifacts

`reconcile-pypi-artifacts` compares the complete validated distribution directory with PyPI's Simple JSON API and
verifies a trusted-publisher attestation for each file. Upload the complete validated directory with the pinned PyPI
publisher. If a run fails, use "Re-run failed jobs" so the upload repeats with the same built files. Run this Action
after the publisher. A different digest in an already published file, unexpected or yanked file, malformed response, or
invalid attestation fails. The GitHub Release writer must depend on this verification.

```yaml
  - uses: tox-dev/github-workflows/reconcile-pypi-artifacts@SHA
    with:
      project: example
      version: ${{ github.ref_name }}
      dist: dist
```

`project`, `version`, and `dist` are required. The Action installs `pypi-attestations` on Python 3.15 under the
`exclude-newer` cutoff and waits up to 120 seconds for PyPI's listing to propagate. It compares every file in `dist`
with that listing, then runs `pypi-attestations verify pypi` on each local file against the caller repository. It prints
no credentials.

## Publish a GitHub Release

`publish-github-release` writes a GitHub Release from the rendered notes. Pass the exact notes file and the tag's commit
SHA. A retry resumes the existing draft and updates its title, notes, and prerelease flag, or succeeds without a write
when the Release is already published.

Run it in a Contents-write job that downloads the notes and optional assets; it needs no checkout or tool installation.
[`github-release.yaml`](#render-release-notes-and-publish-the-github-release) runs this Action in `complete` mode after
the PyPI check. For a repository that must upload GitHub assets before PyPI, call the Action directly with
`mode: stage`, verify PyPI's exact artifact set, then call it with `mode: publish` and the same `assets-directory`. The
draft stays private until the second call succeeds.

Enable immutable releases in the repository before using this Action. The Action checks a draft's assets again before
upload and publication. A published release whose API record is immutable has its assets checked from the release
listing, with no write or second fetch. Older mutable releases retain the asset recheck.

```yaml
  - uses: tox-dev/github-workflows/publish-github-release@SHA
    env:
      GH_TOKEN: ${{ github.token }}
    with:
      tag: ${{ github.ref_name }}
      commit: ${{ github.sha }}
      title: ${{ github.ref_name }}
      notes-file: ${{ runner.temp }}/release-notes.md
```

- `tag`, `commit`, `title`, and `notes-file` are required. The Action uses the caller repository; `commit` is the tag's
  commit, used as the target when the Action creates the Release.
- Before it writes a draft, the Action asks GitHub to generate notes for the range from the previous tag in the notes'
  `Full Changelog` link to `tag`, and adds GitHub's first-time contributors, bots excluded, as a `New Contributors`
  section above the trailing links. The changelog file never carries this list. A published Release is left as it is.
- `assets-directory`: Optional directory of the assets to attach. The Action compares each filename and SHA256 digest
  with GitHub's Release asset metadata, uploads missing draft assets, and rejects extra or changed assets. After
  publication it verifies GitHub's release attestation for each local asset.
- `prerelease`: `true` or `false`; default `false`.
- `mode`: `complete` (default) creates or resumes a draft and publishes it in one call. `stage` creates or resumes a
  draft and uploads assets without publishing. `publish` publishes the draft, creating it first if it is missing, after
  checking its complete asset set again.

**Output:** No named output. **Remote effect:** Depending on `mode`, the Action creates or resumes a draft, uploads
missing assets, and publishes only after the complete asset set matches. A published Release causes no write. A draft
with a different title, body, or prerelease flag is updated; a Release with a different asset set fails. A failed upload
leaves the draft for a later retry. The Action removes incomplete `starter` assets before retrying. It retries reading
the release by ID for up to ten seconds after draft creation or asset upload; a mismatch still fails when that window
ends.

A GitHub API call that fails with a server error or a network error is retried up to three times, with backoff; a 4xx
fails at once. Draft creation is the exception: a request GitHub had already applied would be sent again and could leave
a second draft, so that call is not retried. If the publish call fails, the Action reads the release again and succeeds
when GitHub already published it with the expected assets and notes, which covers a response lost after GitHub applied
the change.

## Reconcile a post-release pull request

`publish-post-release-pr` consumes a candidate commit prepared without an App token. The preparation job records the
base commit, desired branch, and a tab-separated file of changed paths and Git blob SHA1 values, then creates a Git
bundle containing `refs/heads/release-candidate` and its full history. A thin bundle fails verification in the writer's
empty bare repository.

Upload the bundle, path file, and body as one artifact. Pass the upload step's artifact ID to the writer's download
step, so a rerun cannot select an older artifact with the same name. The writer runs without checkout under the caller's
`release-auth` environment and needs Contents, Pull requests, and Issues write access for its App token. Put
`publish-post-release-pr` last in the writer job because its Git credential helper remains available to later steps.

```yaml
  - uses: actions/download-artifact@DOWNLOAD_SHA
    with:
      artifact-ids: ${{ needs.prepare.outputs.artifact-id }}
      path: prepared/
  - uses: tox-dev/github-workflows/publish-post-release-pr@SHA
    env:
      GH_TOKEN: ${{ steps.app-token.outputs.token }}
    with:
      base-commit: ${{ needs.prepare.outputs.base-commit }}
      branch: post-release-${{ github.ref_name }}
      title: Bump version to 2.4.8-dev
      body-file: prepared/body.md
      paths-file: prepared/paths.tsv
      allowed-paths: gradle.properties
      bundle: prepared/candidate.bundle
      candidate-commit: ${{ needs.prepare.outputs.candidate-commit }}
```

The Action verifies that the candidate is a single-parent commit on `base-commit`, and checks its changed path set
against the writer's `allowed-paths`, its regular file modes, and its blob identities before any write.

Pass the keyless job's `base-commit`, the desired `branch` and `title`, and the exact PR body in `body-file`.
`paths-file` contains one tab-separated path and desired Git blob SHA1 per line. The Action targets `main` in
`GITHUB_REPOSITORY` and applies `skip news` to the PR.

A matching open branch and PR need no second push. If a matching branch has no PR, it creates one. A merged PR with a
deleted branch succeeds. A closed, unmerged PR fails before the Action creates a replacement branch or PR; reopen the PR
before retrying. When the prepared change has already merged and produced no new commit, pass empty `bundle` and
`candidate-commit` values with the same path manifest; the Action finds the merged PR. The Action has no named output.

## Check a JetBrains plugin

`jetbrains-plugin-check.yaml` builds the plugin ZIP, records its SHA256, runs `verifyPlugin` for each `verify-matrix`
entry, and runs the Xvfb UI tests. Its `gate` job runs `required-checks` over `build`, `verify`, and `ui-test`. Lint and
unit tests stay in the caller. The workflow needs no secret and holds `contents: read`.

```yaml
jobs:
  plugin:
    uses: tox-dev/github-workflows/.github/workflows/jetbrains-plugin-check.yaml@SHA
    permissions:
      contents: read
```

- `plugin-version`: written to `pluginVersion` before the build, with a leading `v` removed. Empty keeps the committed
  value. A release caller passes `${{ github.ref_name }}`.
- `verify-matrix`: JSON array of `{label, ide, version}` objects. The default verifies `PY` only. Add an entry with
  `version: 263-EAP-SNAPSHOT` to catch platform APIs the next release removes.
- `ui-test-timeout`: seconds to wait for the test IDE to answer on port 8082. Default `300`.

The workflow outputs `archive-sha256`, `archive-name`, and `artifact-id` from its `build` job for
`sign-jetbrains-plugin`. It selects exactly one ZIP that matches the version, and it keeps Gradle's cache off because
the ZIP feeds a signed release. The `unsigned-plugin` artifact is retained for 30 days. UI-test reports upload on
failure for 14 days.

## Sign a JetBrains plugin

`sign-jetbrains-plugin` signs an unsigned plugin ZIP after a keyless Gradle `buildPlugin` job. Run it in a fresh job on
`ubuntu-26.04` with the signing environment, no checkout, and no Gradle invocation. Download the unsigned artifact and
pass the SHA256 emitted before that artifact was uploaded.

The Action checks the file's digest, downloads JetBrains Marketplace ZIP Signer 0.1.43 from Maven Central, verifies its
pinned SHA256, and uses the runner's Java 17 installation. It accepts plain PEM or base64 credentials and an encrypted
private key with its password. The private key is mapped only into the sign step's environment. Its temporary file is
removed when that step ends.

```yaml
sign:
  needs: build-unsigned
  runs-on: ubuntu-26.04
  environment: release
  permissions: {}
  outputs:
    archive: ${{ steps.signed.outputs.archive }}
    sha256: ${{ steps.signed.outputs.sha256 }}
  steps:
    - uses: actions/download-artifact@DOWNLOAD_SHA
      with:
        name: unsigned-plugin
        path: dist/
    - id: signed
      uses: tox-dev/github-workflows/sign-jetbrains-plugin@SHA
      with:
        archive: dist/Plugin-1.2.3.zip
        sha256: ${{ needs.build-unsigned.outputs.archive_sha }}
        certificate-chain: ${{ secrets.CERTIFICATE_CHAIN }}
        private-key: ${{ secrets.PRIVATE_KEY }}
        private-key-password: ${{ secrets.PRIVATE_KEY_PASSWORD }}
    - uses: actions/upload-artifact@UPLOAD_SHA
      with:
        name: plugin-distribution
        path: ${{ steps.signed.outputs.archive }}
        if-no-files-found: error
```

`archive` and `sha256` identify the unsigned ZIP. `certificate-chain` and `private-key` supply the signing identity;
`private-key-password` is needed only for an encrypted key. The outputs are `archive`, the signed ZIP path, and
`sha256`, the digest to check after download in the publisher and GitHub Release jobs. **Remote effect:** downloads the
pinned signer JAR. It makes no GitHub or Marketplace write. The caller uploads the signed ZIP as a GitHub Actions
artifact after the Action succeeds. Keep the Marketplace token in a different no-checkout job.

## Stage and verify a JetBrains Marketplace release

`stage-jetbrains-marketplace` checks a signed ZIP with `release-creator marketplace`. In `mode: stage`, before upload,
it outputs `publish` (`true` when no public version matches) and `channel`. In `mode: verify`, after the version is
public, it compares the public member bytes and outputs nothing. Install `release-creator` from the caller's locked
release tools first.

The channel is the tag suffix before the first dot: `v1.2.3-beta.1` gives `beta`, and `v1.2.3` gives an empty Stable
channel. Pass `channel` to `publish-jetbrains-marketplace`.

```yaml
  marketplace-check:
    needs: sign
    runs-on: ubuntu-26.04
    permissions:
      contents: read
    outputs:
      publish: ${{ steps.stage.outputs.publish }}
      channel: ${{ steps.stage.outputs.channel }}
    steps:
      - uses: actions/download-artifact@DOWNLOAD_SHA
        with:
          artifact-ids: ${{ needs.sign.outputs.artifact-id }}
          path: dist
      - id: stage
        uses: tox-dev/github-workflows/stage-jetbrains-marketplace@SHA
        with:
          archive: dist/Plugin-1.2.3-signed.zip
          sha256: ${{ needs.sign.outputs.sha256 }}
          plugin-id: com.github.toxdev.fish
          version: ${{ github.ref_name }}
          mode: stage
```

## Publish a JetBrains plugin

`publish-jetbrains-marketplace` uploads one signed ZIP through the
[Marketplace upload API](https://plugins.jetbrains.com/docs/marketplace/plugin-upload.html). Run it in a fresh job
without checkout or Gradle. The release workflow must serialize runs for the same tag. Download the signed ZIP and
release notes by the artifact IDs from their producing jobs. The Action checks both before using the upload token.

```yaml
marketplace-publish:
  needs: [sign, notes]
  runs-on: ubuntu-26.04
  permissions:
    actions: read
  environment: release
  steps:
    - uses: actions/download-artifact@DOWNLOAD_SHA
      with:
        artifact-ids: ${{ needs.sign.outputs.artifact-id }}
        path: dist
    - uses: actions/download-artifact@DOWNLOAD_SHA
      with:
        artifact-ids: ${{ needs.notes.outputs.artifact-id }}
        path: ${{ runner.temp }}/notes
    - name: 🚀 Publish signed ZIP
      uses: tox-dev/github-workflows/publish-jetbrains-marketplace@SHA
      with:
        archive: dist/Plugin-1.2.3-signed.zip
        sha256: ${{ needs.sign.outputs.sha256 }}
        plugin-id: '29973'
        channel: ''
        tag: ${{ github.ref_name }}
        commit: ${{ github.sha }}
        signed-artifact-id: ${{ needs.sign.outputs.artifact-id }}
        notes-artifact-id: ${{ needs.notes.outputs.artifact-id }}
        notes-file: ${{ runner.temp }}/notes/release-notes.md
        github-token: ${{ github.token }}
        publish-token: ${{ secrets.PUBLISH_TOKEN }}
```

`channel` is empty for Stable; use a Marketplace channel name for a prerelease. Keep the publishing step named
`🚀 Publish signed ZIP`. The Action recognizes that name and three older upload step names in prior runs. Give the job
Actions read access and the workflow a concurrency group keyed by tag. Use the `release` environment on the upload job.

The Action searches earlier tag runs for a started upload step. An acceptance receipt must match the original artifact
IDs, signed ZIP digest, and release notes bytes before the Action skips upload. An earlier upload step without a receipt
stops for manual reconciliation. A renamed publishing step is not recognized in earlier runs until the Action knows its
name.

**Output:** A `marketplace-acceptance-<run>-<attempt>` Actions artifact after a new upload. It records the tag, commit,
plugin, channel, signed ZIP artifact and SHA256, and notes artifact and SHA256. **Remote effect:** One multipart upload
to JetBrains Marketplace when no earlier acceptance exists, plus a GitHub Actions receipt artifact. The Action treats an
HTTP 2xx response as acceptance; it does not depend on undocumented response fields. Run the keyless release-creator
`marketplace --mode stage` check before this job and `--mode verify` after the version is public.

If the Action stops without a receipt, inspect the exact plugin, version, and channel in the Marketplace dashboard. If
the update is pending review, wait until it is public and verify its member bytes against the original signed ZIP. Then
rerun the tag workflow: the keyless stage check must skip Marketplace upload before GitHub Release publication. If
Marketplace rejected the update, resolve the rejection and prepare a new release tag. A 404 alone does not authorize
another upload of the same tag.

## Prepare the JetBrains post-release version

`prepare-jetbrains-post-release` runs in a keyless job after a release. It requires a plain `X.Y.Z` tag, writes the next
`X.Y.(Z+1)-dev` version to the version file, and writes `paths.tsv`, `body.md`, and `candidate.bundle` to `output-dir`.
The writer job uploads those files with the App token from the `release-auth` environment, and passes them to
`publish-post-release-pr`. The Action does not touch the App token: it reads the App's public user ID with
`github-token` to author the commit.

```yaml
  post-release-prepare:
    runs-on: ubuntu-26.04
    permissions:
      contents: read
    outputs:
      base-commit: ${{ steps.change.outputs.base-commit }}
      candidate-commit: ${{ steps.change.outputs.candidate-commit }}
      branch: ${{ steps.change.outputs.branch }}
      next-version: ${{ steps.change.outputs.next-version }}
      artifact-id: ${{ steps.upload.outputs.artifact-id }}
    steps:
      - uses: actions/checkout@CHECKOUT_SHA
        with:
          ref: main
          fetch-depth: 0
          persist-credentials: false
      - id: change
        uses: tox-dev/github-workflows/prepare-jetbrains-post-release@SHA
        with:
          tag: ${{ github.ref_name }}
          app-slug: tox-dev-jetbrains-fish-release
          github-token: ${{ github.token }}
          output-dir: ${{ runner.temp }}/post-release
      - id: upload
        uses: actions/upload-artifact@UPLOAD_SHA
        with:
          name: post-release-${{ github.run_id }}-${{ github.run_attempt }}
          path: ${{ runner.temp }}/post-release/*
          if-no-files-found: error
```

## Publish a pre-commit mirror

`publish-pre-commit-mirror.yaml` generates a pre-commit mirror of a Python package's hook with pre-commit-mirror-maker
1.14.0, formats the result with prek 0.5.5, and commits each new version as `Mirror: <version>`. On `main`, one atomic
push updates the branch and creates a `v<version>` tag per new version, then a GitHub release is created for each tag. A
run with no new upstream version changes nothing.

- Formatting runs twice. The first run may rewrite files and exit 1; the second run must pass on the rewritten tree. Any
  other exit status fails the job.
- When one run mirrors several versions, only the newest commit gets the README update and the formatting. Older tags
  keep the tree pre-commit-mirror-maker generated.
- A version whose tag already exists on origin is a no-op when the regenerated tree matches the tag, so the daily run
  succeeds with a notice. A different tree fails the run and names both trees. A published tag is never moved, because a
  moved tag changes the rev users have pinned; bump the package version to publish new content.
- The job runs the repository's pre-commit hooks while it holds `contents: write`. Trigger it on pushes to `main`,
  schedules, and manual dispatches. It refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`,
  and `merge_group` callers before it checks out the repository, so no pull request's hook code runs with that token.

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

## Build a LaTeX document to GitHub Pages

`latex-to-pages.yaml` compiles `root-file` with latexmk, pins `SOURCE_DATE_EPOCH` to the checked-out commit time, and
uploads the PDF as the `latex-pdf` artifact. On `main` it deploys to `gh-pages` in the `release` environment, then polls
the Pages build for up to 20 minutes until the served PDF has the built SHA256. GitHub Pages must be enabled for
`gh-pages`. The PDF is served at `https://<owner>.github.io/<repo>/<name>.pdf`, where `<name>` is the root file's base
name.

```yaml
name: Build LaTeX document
on:
  workflow_dispatch:
  push:
    branches: ["main"]
  pull_request:
  schedule:
    - cron: "0 8 * * *"
permissions: {}
jobs:
  pdf:
    uses: tox-dev/github-workflows/.github/workflows/latex-to-pages.yaml@SHA
    permissions:
      contents: write
      pages: read
    with:
      root-file: main.tex
```

The `deploy` job refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`, and `merge_group`
callers before it checks out the repository. It also runs only when the ref is `main`, so a `pull_request` trigger in
the example builds the PDF without deploying it.

## Test a caller

The [Actions test suite](tests) executes each inline `run:` block in temporary Git repositories. Test a caller's
Towncrier template, release hooks, package build, and publisher against representative source data before changing its
live release workflow. Inspect the version, patch, changelog, notes, and built package.

This repository releases its own Actions with the same prepare and tag path. See [Contributing](CONTRIBUTING.md) for
local checks and news fragments, and [Changelog](CHANGELOG.md) for released changes.

# GitHub workflows

Composite Actions check PR news, prepare a Towncrier release, verify its patch, push an App-authored commit and tag, and
render GitHub Release notes. The reusable Python release workflow builds and checks wheels and sdists. Each repository
keeps its dispatch form, publisher, GitHub environment, and required check names.

## Install locked tools

`install-locked-tools` creates a virtual environment and installs selected groups from the caller's `pylock.toml` by
default. `lock-source: shared` selects this Action repository's `pylock.toml` for shared jobs such as hook maintenance
that do not need the caller's release tools. Nab's universal lock records the selected release groups for Linux, macOS,
and Windows. It resolves dependencies under the seven-day cutoff in `[tool.nab]`; test, type, and documentation
dependencies resolve fresh. The Action rejects missing groups and leaves tracked files unchanged. Source builds use
constraints generated from the lock's `build` group under the runner's temporary directory.

- `venv`: directory for the virtual environment when `groups` is set.
- `groups`: whitespace-separated release dependency groups. Leave empty to export build constraints without installing
  release tools.
- `lock-source`: `caller` (default) installs from the checkout's lock; `shared` installs from the pinned Action's lock.
  Both paths use the pinned Action's lock-tool bootstrap. The Action checks that every selected group exists in the
  selected lock and applies hashed build constraints.
- `local-tool-source`: set to `true` only when release-creator builds and installs its own wheel after this Action. The
  caller's lock then needs the selected groups but does not need a release-creator package entry.
- `constraints-lock`: lock used to export build constraints; defaults to the selected install lock. Use a secondary lock
  when the build matrix differs from the release-tool matrix.
- `verify-lock` and `verify-groups`: check another lock's selected packages against PyPI and the seven-day cutoff
  without installing them. Use this before bundling packages from a separate runtime lock, such as a zipapp.
- `target-platform` and `targets`: Nab platform ID and space-separated `full-version:implementation` pairs for build
  constraints. Pass both when exporting constraints for a specific build target; otherwise the runner selects the
  target.

The `build-constraints` output names the hashed constraints file. The Action adds installed command launchers to
`GITHUB_PATH` for later steps while leaving the runner's `python`, `pip`, and `uv` commands on their original paths. Run
`actions/checkout` and `astral-sh/setup-uv` with Python 3.15 before it. It bootstraps Nab from the shared, hash-checked
lock.

For a zipapp that bundles wheels from a separate runtime lock, check that lock in the same job before building it:

```yaml
  - uses: tox-dev/github-workflows/install-locked-tools@SHA
    with:
      groups: release-build
      venv: ${{ runner.temp }}/release-tools
      verify-lock: pylock.zipapp.toml
      verify-groups: project-runtime
```

`export-build-constraints` also accepts `verify-groups`. Pass it when its secondary lock supplies build tools outside
the `build` group, such as profile-guided optimization tools in a `pgo` group.

## Check pull request news

`validate-news` reads `tool.towncrier` from `pyproject.toml`. It checks every added or modified fragment in the
configured directory against the configured categories, filename format, and nonempty content. A valid fragment runs
`towncrier check` against the PR base. A human PR without a fragment needs `skip news`; a bot PR without a fragment does
not. A bot's supplied fragment is checked and included in the normal release flow. The Action reads repository files and
Git history; it does not add labels or write to GitHub.

Put the `changelog` job in a separate `news.yaml` workflow triggered by `opened`, `reopened`, `synchronize`, `labeled`,
and `unlabeled`. Require its status in the main-branch ruleset alongside the test aggregate. A label change then runs
only the news workflow. Install Towncrier from the caller's release lock before calling the Action:

```yaml
changelog:
  runs-on: ubuntu-26.04
  permissions:
    contents: read
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
`labeled` and `unlabeled` events, so a label added after opening the PR updates the required check.

## Refresh release tools and hooks

Call `upgrade-release-tools.yaml` from a scheduled or manual workflow. Its read-only jobs refresh the universal
`pylock.toml` and the frozen pre-commit hooks in parallel. Nab reads the seven-day package cutoff and any reviewed
package exceptions from `[tool.nab]`. The hook updater applies the same cooldown to hook revisions and their
`additional_dependencies`. Each job uploads a patch. The lock patch may change `pylock.toml`, an explicitly configured
secondary lock, and `pyproject.toml` for expired Nab cutoffs. The hook patch may change only `.pre-commit-config.yaml`.
The writer checks each patch before applying it and verifies cutoff removals before minting the App token. It then opens
or updates one dependency PR from `automation/update-release-tools` to `main`. A lock or hook update runs the normal PR
checks before merge.

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
    with:
      lock-groups: >-
        build release-notes release-news release-prepare
        release-validate release-check release-attestations release-shell
        release-hooks release-hook-check
```

The required `lock-groups` input lists the caller's release dependency groups, separated by spaces or newlines. Include
`build` and the release groups used by the caller. `lock-tools` and `lock-reader` come from this Action's lock; include
them only when the caller also uses them. Exclude test, type, and documentation groups. The project configures targets
in `[tool.nab]`. Tests install test, type, and documentation groups afresh so they detect upstream dependency changes.
The Action tests fetch immutable, hash-checked release-tool artifacts from the shared lock; their separate package
fixture resolves test-only tools afresh. The updater also refreshes a caller's secondary build-matrix lock when
`additional-lock` and its matrix inputs are set.

The optional `commit-message`, `pull-request-title`, and `pull-request-body` inputs retain existing PR wording. The
workflow does not update `uv.lock` or a checked-in constraints file. Build constraints are generated from the lock's
`build` group at runtime.

For a second lock such as `pylock.build.toml`, set `additional-lock`, `additional-matrix-python`,
`additional-matrix-platforms`, and `additional-matrix-implementations`. `additional-lock-groups` selects dependency
groups in that lock; with no groups, the updater selects build requirements. Set `additional-lock-selection: project`
for a lock that selects the project's runtime dependencies instead. The lock must already exist, and the updater writes
both locks in the same dependency PR. The writer accepts only those locks, `pyproject.toml`, and the hook configuration.
Pass the same `additional-lock` and matrix inputs to `validate-news` in the PR workflow. It checks changes to either
lock against the project, including a PR that changes only the secondary lock.

`refresh-release-lock` is the read-only half of the updater. In `refresh` mode, it upgrades the selected release groups
under Nab's configured cutoff and writes `$RUNNER_TEMP/lock.patch` if either lock or a reviewed expired Nab cutoff
changes. In `check` mode, it regenerates without upgrading and fails if the checked-in files differ. The resulting PR's
normal formatting job runs `prek`; the writer checks patch paths and modes. Its `changed` output is `true` only when the
refresh produces a patch. Neither mode pushes a branch or requests a write token. Check it on a PR in a job with
Contents read permission:

```yaml
release-tools-preview:
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-26.04
  permissions:
    contents: read
  steps:
    - uses: actions/checkout@CHECKOUT_SHA
      with:
        persist-credentials: false
    - uses: astral-sh/setup-uv@SETUP_UV_SHA
      with:
        version: latest-known
        python-version: '3.15'
    - uses: tox-dev/github-workflows/refresh-release-lock@SHA
      with:
        lock-groups: >-
          build lock-tools lock-reader release-notes release-news release-prepare
          release-validate release-check release-attestations release-shell
          release-hooks release-hook-check
        mode: check
```

The weekly updater freezes eligible hook revisions with `prek update --freeze --cooldown-days 7`. It then uses
`release-creator hooks` to pin Python hook dependencies under the same cutoff and writes a patch when
`.pre-commit-config.yaml` changes. The generation job has read-only repository permissions; the separate publish job
checks the patch paths and file modes before obtaining an App token.

`check-hook-update-cooldown` checks proposed hook revisions on bot PRs. Put it in the caller's `pull_request` workflow
with `actions: read`, `contents: read`, and `pull-requests: read`, then include it in the required aggregate. It reads
its PR number and head SHA from the event, compares them with the live PR, and requires each proposed revision to have
appeared in a GitHub PR workflow run at least `minimum-days` earlier. The default is seven days. A force push does not
reset an unchanged revision's age or give a new revision the old one's age. Human PRs pass without installing hook
tools. Other bot PRs may change hook revisions only. On `automation/update-release-tools`, the Action verifies the bot
against `RELEASE_APP_CLIENT_ID` and permits exact, cooled PyPI dependency pins generated by the release App. It keeps
the same seven-day revision observation rule, so current revisions may remain pending after the lock refresh.

```yaml
hook-cooldown:
  if: github.event_name == 'pull_request'
  runs-on: ubuntu-26.04
  permissions:
    actions: read
    contents: read
    pull-requests: read
  steps:
    - uses: tox-dev/github-workflows/check-hook-update-cooldown@SHA
      with:
        release-app-client-id: ${{ vars.RELEASE_APP_CLIENT_ID }}
```

Run the PR workflow on `opened`, `reopened`, and `synchronize`; the cooldown check must succeed on PRs and may skip on
push. The Action has no output or write side effect. Schedule `recheck-hook-update-cooldown` daily with
`actions: write`, `contents: read`, and `pull-requests: read`. It reruns eligible failed cooldown jobs at the current
head. GitHub accepts reruns for 30 days. A failed rerun is retried on the next schedule while eligible. The
[caller here](.github/workflows/recheck-hook-cooldown.yaml) shows the trigger and permissions. The Action reruns the
`hook-cooldown` job in `check.yaml`.

## Start with a caller

The [release preparation workflow](.github/workflows/prepare-release.yaml) in this repository calls the reusable
Towncrier workflow. Its `assemble` job uploads a patch; a separate keyless `validate` job downloads and checks that
artifact. The `push` job downloads the same artifact by ID and checks its paths and modes before minting a
repository-scoped App token. Set the tag style in the caller and the changelog path and fragment directory in committed
Towncrier configuration. Pin the reusable workflow to a release commit SHA; `SHA` in these examples means that commit.

Assembly needs release history to select a tag. The writer can check out the source commit with `fetch-depth: 1`. All
jobs use `persist-credentials: false`. Assembly installs the caller's locked release tools and needs `contents: read`
and `pull-requests: read` to resolve PR authors. It starts `prek install-hooks` while building the changelog, then waits
for the hooks before formatting and uploading the patch. The validation job runs `prek` on that uploaded patch. The
writer uses the `release-auth` environment with `RELEASE_APP_PRIVATE_KEY` and `RELEASE_APP_CLIENT_ID`. Restrict that
environment to `main`. Install the App on this repository only, with Contents write and Metadata read, and grant the
necessary branch and tag ruleset bypass.

```text
main + fragments
       │
       ▼
prepare-towncrier ──► upload patch ──► validate artifact
                            │                   │
                            └─────────┬─────────┘
                                      ▼
                          verify paths and modes
                                      │
                                      ▼
                           mint App token ──► commit-and-tag ──► main + tag
```

The tag starts the caller's publisher. Keep PyPI trusted publishing in that top-level workflow, in a separate job with
`id-token: write` because
[PyPI disallows reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/). Run `prek` in a separate
read-only job alongside the tagged-source build, and make publishing depend on both. Repositories with the standard `uv`
wheel and sdist build can call `validate-python-release.yaml` in the tag publisher. The
[self-release workflow](.github/workflows/release.yaml) shows the GitHub Release path; callers keep their ecosystem
uploads. The read-only build workflow checks the tagged source. The tag caller renders the Release body and has the only
Contents write job that creates the GitHub Release.

## Validate a Python release

`validate-python-release.yaml` checks the tagged source, exports hashed build constraints in a separate job, builds and
uploads the wheel and sdist, then checks the uploaded files with Twine and check-wheel-contents. The build job runs no
release tool. It requires the tag ref to resolve to the checked-out commit on `main`.

```yaml
build:
  uses: >-
    tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
  permissions:
    contents: read
```

The caller needs `release-check` for prek and a `build` group for backend constraints. `source` defaults to `.`. Use
`artifact-prefix` when one tag produces more than one distribution path; each call then writes a distinct
`python-package-distributions` artifact. A caller pinned to a workflow commit runs that commit's local Actions.

Publish only after the reusable workflow succeeds. Download the distribution with pinned `download-artifact`
[v8.0.2](https://github.com/actions/download-artifact/blob/9000827ccba6bdab643e8b6fd33ac0654aef8333/action.yml#L37-L45),
using `artifact-ids: ${{ needs.build.outputs.distributions-artifact-id }}`. The download checks the artifact digest and
selects the wheel and sdist from that build run. Render GitHub notes in the caller's tag workflow after fetching
GitHub's contributor metadata; this reusable workflow does not render notes. Keep PyPI OIDC in the caller's `release`
environment job.

## Build a distribution for a pull request

`build-python-distribution` remains available for existing keyless PR build jobs. It checks that `dist/` is empty,
exports hashed build constraints from the caller's lock, and writes a wheel and sdist to `dist/`. It does not upload or
publish them. Tagged release jobs use `validate-python-release.yaml` so lock and release tools run in a separate job
from the distribution build.

```yaml
  - uses: tox-dev/github-workflows/build-python-distribution@SHA
```

The Action builds the checkout root and has no named output; subsequent steps read `dist/`.

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

`targets` is a space-separated list of `full-version:implementation` pairs. All selected targets must resolve the same
build package versions; otherwise the Action fails instead of writing an ambiguous constraints file.

## Prepare and tag with one reusable workflow

`prepare-towncrier-release.yaml` runs three jobs. `assemble` selects a tag and uploads a Towncrier patch without the App
key. `validate` calculates the next tag again from the checked-out source, then applies the uploaded artifact and runs
`prek`. `push` downloads that artifact by ID, checks its paths and file modes, reads the caller's `release-auth`
environment, and uses a repository-scoped App token to push the release commit and tag together. Only a dispatch from
`main` can reach the writer.

```yaml
jobs:
  prepare:
    if: github.ref == 'refs/heads/main'
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
uses `release-auth` without creating a GitHub Deployment. `local-tool-source: true` builds release-creator's wheel from
the checkout and installs it with locked third-party dependencies in assembly; use it for release-creator itself. The
caller can place repository-specific checks in a preceding job and make this job depend on it. One dispatch prepares one
tag; run separate dispatches for separate packages. The tag-triggered ecosystem publisher stays in the caller
repository.

## Read Towncrier configuration

`read-towncrier-config` reads `towncrier.toml` or `pyproject.toml` from the checkout's committed `HEAD`. It requires
normalized changelog and fragment paths, a Markdown or RST changelog suffix, and explicit fragment categories. It reads
committed bytes so an untrusted release patch cannot change the allowed paths or categories.

```yaml
  - id: towncrier
    uses: tox-dev/github-workflows/read-towncrier-config@SHA
  - env:
      CHANGELOG: ${{ steps.towncrier.outputs.changelog }}
    run: printf '%s\n' "$CHANGELOG"
```

Outputs are `changelog`, `fragments`, and `format` (`markdown` or `rst`). The Action does not modify the checkout or
GitHub state.

## Prepare Towncrier release

`prepare-towncrier` chooses the next version, links fragments to their squash PRs, runs Towncrier and the selected
formatter hook through `prek`, then writes a binary Git patch at `$RUNNER_TEMP/release.patch`. It reads the changelog
path, fragment directory, categories, and Markdown or RST format from committed Towncrier configuration through
`read-towncrier-config`. It does not commit or push. Version selection, fragment linking, the Towncrier build, and
formatting must all succeed.

```yaml
  - id: prepare
    uses: tox-dev/github-workflows/prepare-towncrier@SHA
    with:
      bump: ${{ inputs.bump }}
```

- `bump`: `auto` (default), `major`, `minor`, `patch`, or `calver`. Passed to `release-creator tags --next`; `auto` uses
  the pending fragments. The caller's dispatch form decides which choices to expose.
- `tag-prefix`: Empty by default. Use `v` when release tags are spelled `v1.2.3`; version comparison still includes
  unprefixed numeric tags in the repository's history. This does not set the changelog heading prefix.
- `changelog-prefix`: Empty by default, so Towncrier writes `1.2.3` even if the tag is `v1.2.3`. Set `v` for a changelog
  whose release headings use `v1.2.3`.
- `version`: Explicit version for a caller with its own version selector. It takes precedence over `bump`; the Action
  still checks that it is newer than existing tags.
- `phase`: `all` (default) runs the complete Action. The reusable workflow uses `build` to select the version, link
  authors, and build the changelog while hooks install; it then uses `finalize` to format, render, and write the patch.
  Pass the version selected by `build` to `finalize`.

The committed `tool.towncrier` configuration must give a normalized `filename`, `directory`, and explicit fragment
categories. The filename must end in `.md` or `.rst`; `mdformat` or `docstrfmt` must be a configured `prek` hook for
that format. The Action writes the patch at `$RUNNER_TEMP/release.patch`; the reusable workflow uploads it by artifact
ID.

**Output:** `version` is the selected tag string. Use `steps.prepare.outputs.version` as a job output and pass it to
both later Actions. **Working-tree effect:** Towncrier changes the changelog and consumes fragments; the patch records
those changes.

## Validate release patch

`validate-release-patch` runs in the caller's fresh checkout of the original branch commit. It rejects a `main` branch
that moved, applies the uploaded patch, checks its changed paths and file modes, then asks `release-creator` to verify
that every deleted file is a configured Towncrier fragment. It renders the requested version and runs `prek`. It leaves
the patch staged for the commit Action. Run it in a keyless validation job. The App-key job repeats the branch, path,
and mode checks with `checks: "false"`, without installing release tools.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@SHA
    with:
      version: ${{ needs.assemble.outputs.version }}
      patch: ${{ runner.temp }}/release-patch/release.patch
```

- `version` **(required)**: Exact tag chosen by preparation. `release-creator notes` must find one valid section for it.
- `patch` **(required)**: Local path of the downloaded patch artifact, not an artifact name or URL.
- `checks`: `true` (default) runs `release-creator` and `prek`; `false` only applies and checks the validated patch.

**Output:** No named output. **Working-tree effect:** Applies and stages the patch. The Action reads the changelog path,
fragment directory, and categories from committed Towncrier configuration. Only the changelog and direct fragment
deletions may appear in the patch. A failed `prek` run or an unexpected path or mode fails the keyless job.

## Commit and tag release

`commit-and-tag` accepts only a staged release patch in a clean working tree. It commits with the GitHub App bot
identity, creates the tag, and atomically pushes the branch and tag to `origin`. A rejected push leaves neither remote
ref updated. Mint the token after validation with `actions/create-github-app-token`, narrowed to this repository and
Contents write. Put `commit-and-tag` last in the writer job: its Git credential helper remains available to later steps.

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

## Render GitHub Release notes

`render-release-notes` checks the tag and its changelog section, finds the previous tag, and renders an unwrapped GitHub
Release body with `release-creator`. Call it on the actual tag. The publisher still fetches GitHub's generated notes and
creates the Release; this Action only writes a local Markdown file.

```yaml
  - uses: tox-dev/github-workflows/render-release-notes@SHA
    with:
      tag: ${{ github.ref_name }}
      changelog: CHANGELOG.md
      artifact-url: https://pypi.org/project/example/${{ github.ref_name }}/
      generated-notes: ${{ runner.temp }}/generated-notes.md
      output: ${{ runner.temp }}/release-notes.md
```

- `tag` **(required)**: Release version, such as `1.2.3`. The checkout must contain its changelog section.
- `changelog` **(required)**: Tracked Markdown or reStructuredText changelog in the format that `release-creator notes`
  parses, with exactly one section for the tag.
- `artifact-url`: Ecosystem release URL, such as a PyPI version page. Omit it for a GitHub-only project.
- `artifact-label`: Link text for `artifact-url`; default `PyPI release`. Use `Zipapp` or another product name for a
  different artifact.
- `generated-notes`: Path to GitHub's generated-notes body. The tag publisher fetches it after PyPI publication. It
  preserves New Contributors and fills any missing `by @handle` credit. Omit it when the release has no GitHub-generated
  contributor metadata.
- `output` **(required)**: Writable path for the GitHub Release body. Pass it to `gh release create --notes-file` only
  after the ecosystem publisher succeeds.

The Action reads `GITHUB_REPOSITORY` for PR and comparison links. A repository with separate release namespaces, such as
toml-fmt, calls `release-creator notes --package` directly for its package changelog.

**Output:** No named output. **Working-tree effect:** The Action writes only `output`. It rejects an invalid tag, a
missing heading, an empty body, or a missing comparison link when an earlier tag exists. It neither fetches generated
notes nor writes a GitHub Release, so a PR job needs only read permissions. Fetching generated notes uses GitHub's
release endpoint and needs Contents write in the tag publisher.

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
this is the first matching release. Pass it as `previous_tag_name` to GitHub's generated-notes endpoint only when
nonempty.

## Reconcile PyPI artifacts

`reconcile-pypi-artifacts` compares the complete validated distribution directory with PyPI's Simple JSON API and
verifies a trusted-publisher attestation for each file. Upload the complete validated directory with the pinned PyPI
publisher and `skip-existing: true`. A rerun sends only files missing from PyPI. Run this Action in a read-only job
after the publisher. A different digest in an already published file, unexpected or yanked file, malformed response, or
invalid attestation fails. The GitHub Release writer must depend on this verification.

```yaml
  - uses: tox-dev/github-workflows/reconcile-pypi-artifacts@SHA
    with:
      project: example
      version: ${{ github.ref_name }}
      dist: dist
```

`project`, `version`, and `dist` are required. The Action installs the locked `release-attestations` group on Python
3.15 and waits up to 120 seconds for PyPI's listing to propagate. It checks the complete local file set, then runs
`pypi-attestations verify pypi` on each local file against the caller repository. It prints no credentials.

## Publish a GitHub Release

`publish-github-release` verifies the tag and its rendered notes before writing a GitHub Release. Pass the exact notes
file and the tag's commit SHA. A retry resumes a matching draft, or succeeds without a write when the published Release
already matches. Run it in a Contents-write job that downloads the notes and optional assets; it needs no checkout or
tool installation. For a repository that must upload GitHub assets before PyPI, call it with `mode: stage`, verify
PyPI's exact artifact set, then call it with `mode: publish` and the same `assets-directory`. The draft stays private
until the second call succeeds. Enable immutable releases in the repository before using this Action. Drafts can still
be edited, so the Action checks them again before upload and publication. A matching published release whose API record
is immutable needs no write or second metadata fetch. Older mutable releases retain the recheck.

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

- `tag`, `commit`, `title`, and `notes-file` are required. The Action uses the caller repository; `commit` is the commit
  the existing tag must resolve to. `title` and the file bytes must match an existing Release exactly.
- `assets-directory`: Optional directory containing only the assets to attach. The Action compares each filename and
  SHA256 digest with GitHub's Release asset metadata, uploads missing draft assets, and rejects extra or changed assets.
  After publication it verifies GitHub's release attestation for each local asset.
- `prerelease`: `true` or `false`; default `false`. It must match an existing Release.
- `mode`: `complete` (default) creates or resumes a draft and publishes it in one call. `stage` creates or resumes a
  draft and uploads assets without publishing. `publish` requires an existing draft and publishes it after checking the
  tag, notes, and complete asset set again.

**Output:** No named output. **Remote effect:** Depending on `mode`, the Action creates or resumes a draft, uploads
missing assets, and publishes only after the complete asset set matches. A matching published Release causes no write. A
different body, title, tag commit, prerelease flag, or asset set fails without changing the existing Release. A failed
upload leaves the draft for a later retry. The Action removes incomplete `starter` assets before retrying. It retries
reading the release by ID for up to ten seconds after draft creation or asset upload; a mismatch still fails when that
window ends.

## Reconcile a post-release pull request

`publish-post-release-pr` consumes a candidate commit prepared without an App token. The preparation job records the
base commit, desired branch, and a tab-separated file of changed paths and Git blob SHA1 values, then creates a Git
bundle containing `refs/heads/release-candidate` and its full history. A thin bundle fails verification in the writer's
empty bare repository. Upload the bundle, path file, and body as one artifact. Pass the upload step's artifact ID to the
writer's download step, so a rerun cannot select an older artifact with the same name. The writer runs without checkout
under the caller's `release-auth` environment and needs Contents, Pull requests, and Issues write access for its App
token. Put `publish-post-release-pr` last in the writer job because its Git credential helper remains available to later
steps.

```yaml
  - uses: actions/download-artifact@DOWNLOAD_SHA
    with:
      artifact-ids: ${{ needs.prepare.outputs.artifact-id }}
      path: prepared/
  - uses: tox-dev/github-workflows/publish-post-release-pr@SHA
    env:
      GH_TOKEN: ${{ steps.app-token.outputs.token }}
    with:
      app-slug: ${{ steps.app-token.outputs.app-slug }}
      base-commit: ${{ needs.prepare.outputs.base-commit }}
      branch: post-release-${{ github.ref_name }}
      title: Bump version to 2.4.8-dev
      commit-message: Bump version to 2.4.8-dev after 2.4.7
      body-file: prepared/body.md
      paths-file: prepared/paths.tsv
      allowed-paths: gradle.properties
      bundle: prepared/candidate.bundle
      candidate-commit: ${{ needs.prepare.outputs.candidate-commit }}
```

The Action derives the bot identity from the writer's App slug and verifies the commit author and committer, exact
commit message, single-parent commit, changed path set against the writer's `allowed-paths`, regular file modes, and
blob identities before any write.

Pass the keyless job's `base-commit`, the desired `branch` and `title`, its exact one-line `commit-message`, and the
exact PR body in `body-file`. `paths-file` contains one tab-separated path and desired Git blob SHA1 per line. The
Action targets `main` in `GITHUB_REPOSITORY` and applies `skip news` to the PR.

A matching open branch and PR need no second push. If a matching branch has no PR, it creates one. A merged PR with a
deleted branch succeeds only when the current base still has the expected file bytes. A closed, unmerged PR fails before
the Action creates a replacement branch or PR; reopen the PR before retrying. A different branch, PR title, body, base,
path set, or merged file state fails without a force-push. When the prepared change has already merged and produced no
new commit, pass empty `bundle` and `candidate-commit` values with the same path manifest; the Action still checks the
merged PR and current base. The Action has no named output.

## Sign a JetBrains plugin

`sign-jetbrains-plugin` signs an unsigned plugin ZIP after a keyless Gradle `buildPlugin` job. Run it in a fresh job on
`ubuntu-26.04` with the signing environment, no checkout, and no Gradle invocation. Download the unsigned artifact and
pass the SHA256 emitted before that artifact was uploaded. The Action checks the file and its digest, downloads
JetBrains Marketplace ZIP Signer 0.1.43 from Maven Central, verifies its pinned SHA256, and uses the runner's Java 17
installation. It accepts plain PEM or base64 credentials and an encrypted private key with its password. The private key
is mapped only into the sign step's environment. Its temporary file is removed when that step ends.

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

## Publish a JetBrains plugin

`publish-jetbrains-marketplace` uploads one signed ZIP through the
[Marketplace upload API](https://plugins.jetbrains.com/docs/marketplace/plugin-upload.html). Run it in a fresh job
without checkout or Gradle. Download the ZIP produced by the signing job and pass that job's SHA256 output; the Action
checks the downloaded bytes, ZIP integrity, and member names before the token-bearing upload step.

```yaml
  - uses: tox-dev/github-workflows/publish-jetbrains-marketplace@SHA
    env:
      PUBLISH_TOKEN: ${{ secrets.PUBLISH_TOKEN }}
    with:
      archive: dist/Fish Shell 2-0.1.11-signed.zip
      sha256: ${{ needs.sign.outputs.sha256 }}
      plugin-id: '29973'
      channel: ''
```

`archive`, `sha256`, and numeric `plugin-id` are required. `channel` is empty for Stable; use a Marketplace channel name
for a prerelease. **Output:** None. **Remote effect:** One multipart upload to JetBrains Marketplace. The Action does
not check whether this version was published already; use the keyless release-creator `marketplace --mode stage` check
before the upload, and `--mode verify` afterward. A retry must compare the published ZIP's member digests before
skipping an upload because Marketplace can repackage the outer ZIP.

## Test a caller

The [Actions test suite](tests) executes each inline `run:` block in temporary Git repositories. Test a caller's
Towncrier template, release hooks, package build, and publisher against representative source data before changing its
live release workflow. Inspect the version, patch, changelog, notes, and built package.

This repository releases its own Actions with the same prepare and tag path. See [Contributing](CONTRIBUTING.md) for
local checks and news fragments, and [Changelog](CHANGELOG.md) for released changes.

# GitHub workflows

Composite Actions check PR news, prepare a Towncrier release, verify its patch, push an App-authored commit and tag,
build a Python wheel and sdist, and render GitHub Release notes. They run as steps in the caller's workflow. Each
repository keeps its dispatch form, publisher, GitHub environment, and required check names.

## Install locked tools

`install-locked-tools` creates a virtual environment and installs selected groups from the caller's `pylock.toml` by
default. `lock-source: shared` selects this Action repository's `pylock.toml` for shared jobs such as hook maintenance
that do not need the caller's release tools. Nab's universal lock records the selected release groups for Linux, macOS,
and Windows. It resolves dependencies under the seven-day cutoff in `[tool.nab]`; test, type, and documentation
dependencies resolve fresh. The Action rejects missing groups and leaves tracked files unchanged. Source builds use
constraints generated from the lock's `build` group under the runner's temporary directory.

- `venv` (required): directory for the virtual environment.
- `groups` (required): whitespace-separated release dependency groups.
- `lock-source`: `caller` (default) installs from the checkout's lock; `shared` installs from the pinned Action's lock.
  Both paths use the pinned Action's lock-tool bootstrap. The Action checks that every selected group exists in the
  selected lock and applies hashed build constraints.

There is no named output. The installed commands are in `venv/bin` or Windows `venv/Scripts`; add that directory to
`GITHUB_PATH` when later steps call them by name. Run `actions/checkout` and `astral-sh/setup-uv` with Python 3.15
before this Action.

`install-lock-tools` is the shared bootstrap used by `install-locked-tools`, `export-build-constraints`, and
`refresh-release-lock`. It takes no inputs and has no outputs. It creates `$RUNNER_TEMP/lock-tools` and installs the
hash-checked `lock-tools` group from this repository's pinned `pylock.toml`; it does not install caller dependencies.

## Check pull request news

`validate-news` reads `tool.towncrier` from `pyproject.toml`. It checks every added or modified fragment in the
configured directory against the configured categories, filename format, and nonempty content. A valid fragment runs
`towncrier check` against the PR base. A human PR without a fragment needs `skip news`; a bot PR without a fragment does
not. A bot's supplied fragment is checked and included in the normal release flow. The Action reads repository files and
Git history; it does not add labels or write to GitHub.

Keep the caller's existing `changelog` job name and full checkout. Install Towncrier from the caller's release lock
before calling the Action:

```yaml
changelog:
  if: github.event_name == 'pull_request'
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
    - name: Expose release tools
      run: echo "$RUNNER_TEMP/release-tools/bin" >>"$GITHUB_PATH"
    - uses: tox-dev/github-workflows/validate-news@SHA
```

The Action expects a pull request base ref and a Markdown or reStructuredText changelog. The caller should also run on
`labeled` and `unlabeled` events, so a label added after opening the PR updates the required check.

`label-bot-news` adds `skip news` to a bot PR with no fragment and removes it when the bot adds one. It reads the PR
file list through GitHub's API and never checks out PR code. Keep it in a separate `workflow_run` caller so the
read-only PR workflow does not receive Issues write access. `resolve-pr-from-run` verifies that a completed run came
from that PR workflow, then looks up the current PR by its source owner, branch, repository, and exact head SHA. It
returns no PR when the branch has moved. This also handles fork PRs, whose workflow-run payload may omit the PR number.

The [caller in this repository](.github/workflows/label-bot-news.yaml) shows the event and permissions. It runs after
the read-only `Check` workflow finishes, even if its tests fail. Set `workflows` to that caller's PR workflow name and
`workflow-path` to its file. The label action accepts `fragments` and `extension` for an RST repository, and `fragments`
accepts comma-separated directories when the caller also recognizes a legacy fragment path:

```yaml
name: Label bot news
on:
  workflow_run:
    workflows: [Check]
    types: [completed]
permissions: {}
jobs:
  label:
    if: github.event.workflow_run.event == 'pull_request'
    runs-on: ubuntu-26.04
    permissions:
      actions: read
      issues: write
      pull-requests: read
    steps:
      - id: pr
        uses: tox-dev/github-workflows/resolve-pr-from-run@SHA
        with:
          run-id: ${{ github.event.workflow_run.id }}
          workflow-path: .github/workflows/check.yaml
      - if: steps.pr.outputs.bot-author == 'true'
        uses: tox-dev/github-workflows/label-bot-news@SHA
        with:
          pull-request: ${{ steps.pr.outputs.number }}
          bot-author: 'true'
          fragments: docs/changelog
          extension: rst
```

`resolve-pr-from-run` takes the source `run-id` and `workflow-path` in the caller repository. It outputs `number` and
`bot-author`; `number` is empty when the run's head is no longer the open PR head. It reads GitHub metadata and writes
no repository files. `label-bot-news` takes that verified number and bot flag. For `.changeset/<name>.md`, pass
`fragments: .changeset` and `fragment-style: changeset`. `fragment-style` defaults to `towncrier`, which expects
`<name>.<category>.md` or RST. It only changes the `skip news` label when the bot's fragment state and label disagree.
Label writes made with `GITHUB_TOKEN` do not trigger PR CI. The next contributor or bot update runs the news check
against the settled label state.

## Refresh release tools and hooks

Call `upgrade-release-tools.yaml` from a scheduled or manual workflow. Its read-only jobs refresh the universal
`pylock.toml` and the frozen pre-commit hooks in parallel. Nab reads the seven-day package cutoff and any reviewed
package exceptions from `[tool.nab]`. The hook updater applies the same cooldown to hook revisions and their
`additional_dependencies`. Each job uploads a patch. The writer accepts changes to `pylock.toml`, an explicitly named
secondary lock, and `.pre-commit-config.yaml`, plus removal of expired Nab cutoffs in `pyproject.toml`. It independently
checks those cutoff removals before minting the App token, then opens or updates one dependency PR from
`automation/update-release-tools` to `main`. A lock or hook update runs the normal PR checks before merge.

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
        build lock-tools release-notes release-news release-prepare
        release-validate release-check release-attestations release-shell
        release-hooks release-hook-check
```

The required `lock-groups` input lists the caller's release dependency groups, separated by spaces or newlines. Include
`build` and `lock-tools` where declared; exclude test, type, and documentation groups. This example lists this
repository's groups; a caller supplies its own. The project configures its Python and platform targets in `[tool.nab]`.
For a separately checked-in build matrix lock, also pass `additional-lock` with an existing `pylock.*.toml` basename,
`additional-matrix-python` with its Python range, and `additional-matrix-platforms` and
`additional-matrix-implementations` as space-separated Nab values. The secondary lock keeps its specified environment
matrix during refresh. `additional-lock-groups` selects dependency groups for it; when empty, Nab locks the project's
build requirements. These inputs have no effect when `additional-lock` is absent, and matrix inputs without that lock
fail. The writer accepts only the named secondary lock path.

For a repository that already commits `pylock.build.toml`, the complete caller is:

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
      lock-groups: build lock-tools release-news release-prepare release-check
      additional-lock: pylock.build.toml
      additional-matrix-python: '>=3.15,<3.16'
      additional-matrix-platforms: linux_x86_64 macos_arm64 windows_amd64
      additional-matrix-implementations: cpython
```

The optional `commit-message`, `pull-request-title`, and `pull-request-body` inputs retain existing PR wording. The
workflow does not update `uv.lock` or a checked-in constraints file. Build constraints are generated from the lock's
`build` group at runtime.

`refresh-release-lock` is the read-only half of the updater. It accepts the same secondary-lock inputs. In `refresh`
mode, it upgrades the selected release groups under Nab's configured cutoff, runs `prek`, and writes
`$RUNNER_TEMP/lock.patch` if either lock or an expired Nab cutoff changes. In `check` mode, it regenerates without
upgrading and fails if the checked-in files differ; the caller's normal formatting job runs `prek`. It rejects changes
outside the selected locks and expired cutoff policy. Its `changed` output is `true` only when the refresh produces a
patch. Neither mode pushes a branch or requests a write token. Check it on a PR in a job with Contents read permission:

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
          build lock-tools release-notes release-news release-prepare
          release-validate release-check release-attestations release-shell
          release-hooks release-hook-check
        mode: check
```

`refresh-hook-pins` is the matching read-only Action. It freezes eligible revisions with
`prek update --freeze --cooldown-days 7`. For selected Python hooks, it reads each hook repository's package metadata
and pins both the hook package dependencies and `additional_dependencies` under the seven-day cutoff. Non-Python hooks
keep their frozen revisions. It then runs the hooks. Its `changed` output is `true` only when `.pre-commit-config.yaml`
changes; the patch is `$RUNNER_TEMP/hooks.patch`. It fails when a hook changes another tracked file. The Action does not
write to GitHub.

`check-hook-update-cooldown` checks proposed hook revisions on bot PRs. Put it in the caller's `pull_request` workflow
with `actions: read`, `contents: read`, and `pull-requests: read`, then include it in the required aggregate. It reads
its PR number and head SHA from the event, compares them with the live PR, and requires each proposed revision to have
appeared in a GitHub PR workflow run at least `minimum-days` earlier. The default is seven days. A force push does not
reset an unchanged revision's age or give a new revision the old one's age. Human PRs pass without installing hook
tools.

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
```

Run the PR workflow on `opened`, `reopened`, and `synchronize`; the cooldown check must succeed on PRs and may skip on
push. The Action has no output or write side effect. Schedule `recheck-hook-update-cooldown` daily with
`actions: write`, `contents: read`, and `pull-requests: read`. It reruns eligible failed cooldown jobs at the current
head. GitHub accepts reruns for 30 days. A failed rerun is retried on the next schedule while eligible. The
[caller here](.github/workflows/recheck-hook-cooldown.yaml) shows the trigger and permissions. Set `workflow` or
`job-name` only when the caller uses different names.

Run the hook preview in its own PR job so its patch check sees only the hook configuration:

```yaml
hook-pins-preview:
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
    - uses: tox-dev/github-workflows/refresh-hook-pins@SHA
```

## Start with a caller

The [release preparation workflow](.github/workflows/prepare-release.yaml) in this repository calls the reusable
Towncrier workflow. Its `assemble` job creates a patch, validates it in a fresh worktree without the App key, and
records the patch digest. Its `push` job checks the patch and digest again before minting a repository-scoped App token.
Set the tag style in the caller and the changelog path and fragment directory in committed Towncrier configuration. Pin
the reusable workflow to a release commit SHA; `SHA` in these examples means that commit.

Assembly needs release history to select a tag. The writer can check out the source commit with `fetch-depth: 1`. Both
jobs use `persist-credentials: false`. Assembly installs the caller's locked release tools and needs `contents: read`
and `pull-requests: read` to resolve PR authors. It starts `prek install-hooks` while creating the validation worktree
and building the changelog, then waits for the hooks before formatting and validating the patch. The writer uses the
`release-auth` environment with `RELEASE_APP_PRIVATE_KEY` and `RELEASE_APP_CLIENT_ID`. Restrict that environment to
`main`. Install the App on this repository only, with Contents write and Metadata read, and grant the necessary branch
and tag ruleset bypass.

```text
main + fragments
       │
       ▼
prepare-towncrier ──► validate in fresh worktree ──► upload patch + digest
                                                       │
                                                       ▼
                                     verify patch ──► mint App token
                                                       │
                                                       ▼
                                              commit-and-tag ──► main + tag
```

The tag starts the caller's publisher. Keep PyPI trusted publishing in that top-level workflow, in a separate job with
`id-token: write` because
[PyPI disallows reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/). Run `prek` in a separate
read-only job alongside the tagged-source build, and make publishing depend on both. Repositories with the standard `uv`
wheel and sdist build can use `build-python-distribution` in the tag publisher. The
[self-release workflow](.github/workflows/release.yaml) shows the GitHub Release path; callers keep their ecosystem
uploads. The read-only build workflow checks the tagged source and renders the Release body. The tag caller alone has a
Contents write job that creates the GitHub Release.

## Validate a Python release

`validate-python-release.yaml` runs read-only source checks, notes rendering, a hash-constrained wheel and sdist build,
and distribution checks on a release tag. Before building, it requires the fully qualified tag ref to resolve to the
checked-out commit and that commit to be on `main`. The workflow uses `$/` for its own Actions, so a caller pinned to a
workflow commit runs those Actions from the same commit.

Call the pinned workflow from the tag publisher's build job:

```yaml
build:
  uses: >-
    tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
  permissions:
    contents: read
  with:
    changelog: CHANGELOG.md
    artifact-base-url: https://pypi.org/project/example/
```

`changelog` is the rendered changelog path. `artifact-base-url` ends just before the version; the workflow appends
`1.2.3/` for tag `1.2.3`. Set it to the package's actual PyPI project path. `artifact-label` changes the link text from
`PyPI release`. reStructuredText `:issue:` references link to issues; `:pr:` and `:pull:` link to pull requests.

The workflow uses Python 3.15 and `pylock.toml`. The caller declares `release-check` for `prek`, `release-notes` for
`release-creator`, `pkg-meta` for Twine and check-wheel-contents, and a `build` group for backend constraints. `source`
defaults to the repository root for `uv build`. `artifact-prefix` defaults to empty; set it when a tag builds more than
one distribution path so the jobs use distinct artifact names. Set `local-tool-source: true` for release-creator's own
release; the keyless job builds its tagged wheel and installs it with locked third-party dependencies. The installer
rejects an absent group before syncing.

The workflow uploads `python-package-distributions` with the wheel and sdist, and `release-validation-notes` with the
body rendered from the tagged source. Callers download the distribution with pinned `download-artifact`
[v8.0.2](https://github.com/actions/download-artifact/blob/9000827ccba6bdab643e8b6fd33ac0654aef8333/action.yml#L37-L45),
whose default fails on an artifact digest mismatch. Its notes lack GitHub contributor metadata. The tag-only GitHub
Release job must fetch generated notes with Contents write, rerender with `render-release-notes`, and create the Release
after the ecosystem upload. PyPI OIDC stays in the caller's separate `release` environment job.

The PyPI publisher downloads the complete validated distribution artifact. It can run alongside GitHub note rendering
once the build succeeds. Verify PyPI and its attestations before publishing the GitHub Release.

## Prepare and tag with one reusable workflow

`prepare-towncrier-release.yaml` runs two jobs. `assemble` selects a tag and writes a Towncrier patch without the App
key, applies it in a fresh worktree, runs `prek`, and records its digest. `push` checks the digest and patch paths,
reads the caller's `release-auth` environment, and uses a repository-scoped App token to push the release commit and tag
together. Only a dispatch from `main` can reach the writer.

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

`working-directory` defaults to `.`; pass a different checkout when validating a patch in a linked worktree. Outputs are
`changelog`, `fragments`, and `format` (`markdown` or `rst`). The Action does not modify the checkout or GitHub state.

## Prepare Towncrier release

`prepare-towncrier` reads a clean checkout, chooses the next version, links fragments to their squash PRs, runs
Towncrier and the selected formatter hook through `prek`, then writes a binary Git patch at
`$RUNNER_TEMP/release.patch`. It reads the changelog path, fragment directory, categories, and Markdown or RST format
from committed Towncrier configuration through `read-towncrier-config`. It does not commit or push. It fails if version
selection, notes rendering, formatting, or checks fail, or if preparation creates untracked files or no patch.

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
those changes. The checkout must be clean before this Action starts.

## Validate release patch

`validate-release-patch` runs in the caller's fresh checkout of the original branch commit. It rejects a `main` branch
that moved, applies the uploaded patch, checks its changed paths and file modes, then asks `release-creator` to verify
that every deleted file is a configured Towncrier fragment. It renders the requested version and runs `prek`. It leaves
the patch staged for the commit Action. Run it in a keyless validation job. The App-key job repeats the branch, digest,
path, and mode checks with `checks: "false"`, without installing release tools.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@SHA
    with:
      version: ${{ needs.assemble.outputs.version }}
      patch: ${{ runner.temp }}/release-patch/release.patch
```

- `version` **(required)**: Exact tag chosen by preparation. `release-creator notes` must find one valid section for it.
- `patch` **(required)**: Local path of the downloaded patch artifact, not an artifact name or URL.
- `working-directory`: Checkout where the patch is applied; default `.`. Assembly uses a fresh linked worktree here so
  validation cannot pass because of files left by preparation.
- `expected-patch-sha`: SHA-256 digest of the patch from a separate keyless validation job. The Action rejects a
  different downloaded patch before applying it.
- `checks`: `true` (default) runs `release-creator` and `prek`; `false` only applies and checks the validated patch.

**Output:** No named output. **Working-tree effect:** Applies and stages the patch. The Action reads the changelog path,
fragment directory, and categories from committed Towncrier configuration. Only the changelog and direct fragment
deletions may appear in the patch. A failed `prek` run, unexpected path or mode, or modification by `prek` fails the
keyless job. The key job accepts only the validated digest.

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

## Build Python distribution

`build-python-distribution` builds a wheel and sdist with `uv`. The build job checks out the tagged source and sets up
`uv` first. Run `prek` in a separate read-only job alongside the build, and require both before publishing. The caller
verifies the tag and changelog section before this Action.

```yaml
  - uses: tox-dev/github-workflows/build-python-distribution@SHA
    with:
      source: .
```

- `source`: Source directory passed to `uv build`; default `.`.

**Output:** No named output. **Working-tree effect:** Writes a wheel and sdist to `dist`. The checkout must be clean
before the Action starts. The Action exports hashed backend constraints from the lock's `build` group at runtime;
`uv build` rejects a missing hash. Use a separate build path for repositories whose build command differs from
`uv build --sdist --wheel`.

## Validate Python distribution

`validate-python-distribution` runs Twine and check-wheel-contents on the files the build job will upload. It installs
both tools from the caller's locked `pkg-meta` group. Run it after `build-python-distribution` and before
`upload-artifact`.

```yaml
  - uses: tox-dev/github-workflows/validate-python-distribution@SHA
```

The Action takes no inputs and checks `dist` on Python 3.15. **Output:** No named output. **Working-tree effect:** None.
An invalid sdist or wheel stops before the artifact upload.

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

**Output:** `previous` is the nearest earlier version tag, or empty for the first release. **Working-tree effect:** The
Action writes only `output`. It rejects an invalid tag, a missing heading, an empty body, or a missing comparison link
when an earlier tag exists. It neither fetches generated notes nor writes a GitHub Release, so a PR job needs only read
permissions. Fetching generated notes uses GitHub's release endpoint and needs Contents write in the tag publisher.

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

`tag` is required. Set `package` for a namespace such as `pyproject-fmt/2.30.3`; set `stable-only: "true"` when a stable
release must skip prerelease tags. `executable` defaults to `release-creator` on `PATH` and accepts a path to a locked
installation. The `previous` output is empty when this is the first release. Pass it as `previous_tag_name` to GitHub's
generated-notes endpoint only when nonempty.

## Reconcile PyPI artifacts

`reconcile-pypi-artifacts` compares the complete validated distribution directory with PyPI's Simple JSON API and
verifies a trusted-publisher attestation for each file. Upload the complete directory with the pinned PyPI publisher,
without `skip-existing`. Run this Action in a read-only job after the publisher. A different digest, unexpected or
yanked file, malformed response, or invalid attestation fails. The GitHub Release writer must depend on this
verification.

```yaml
  - uses: tox-dev/github-workflows/reconcile-pypi-artifacts@SHA
    with:
      project: example
      version: ${{ github.ref_name }}
      dist: dist
```

`project`, `version`, and `dist` are required. The Action installs locked `release-notes` and `release-attestations`
groups on Python 3.15 and waits up to 120 seconds for PyPI's listing to propagate. Set `local-tool-source: "true"` only
when releasing release-creator itself; it installs the wheel already built in `dist`. The Action prints no credentials;
it checks the complete local file set and each published file's attestation against the caller repository.

## Publish a GitHub Release

`publish-github-release` verifies the tag and its rendered notes before writing a GitHub Release. Pass the exact notes
file and the tag's commit SHA. A retry resumes a matching draft, or succeeds without a write when the published Release
already matches. Run it in a Contents-write job that downloads the notes and optional assets; it needs no checkout or
tool installation. For a repository that must upload GitHub assets before PyPI, call it with `mode: stage`, verify
PyPI's exact artifact set, then call it with `mode: publish` and the same `assets-directory`. The draft stays private
until the second call succeeds.

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
  After publication it verifies GitHub's release attestation for each local asset. Enable immutable releases in the
  repository before using this option.
- `prerelease`: `true` or `false`; default `false`. It must match an existing Release.
- `mode`: `complete` (default) creates or resumes a draft and publishes it in one call. `stage` creates or resumes a
  draft and uploads assets without publishing. `publish` requires an existing draft and publishes it after checking the
  tag, notes, and complete asset set again.

**Output:** No named output. **Remote effect:** Depending on `mode`, the Action creates or resumes a draft, uploads
missing assets, and publishes only after the complete asset set matches. A matching published Release causes no write. A
different body, title, tag commit, prerelease flag, or asset set fails without changing the existing Release. A failed
upload leaves the draft for a later retry. An asset in GitHub's incomplete `starter` state requires manual cleanup
before retrying. The Action retries reading the release by ID for up to ten seconds after creating the draft, uploading
assets, or publishing; a mismatch still fails when that window ends.

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

# GitHub workflows

Composite Actions check PR news, prepare a Towncrier release, verify its patch, push an App-authored commit and tag,
build a Python wheel and sdist, and render GitHub Release notes. They run as steps in the caller's workflow. Each
repository keeps its dispatch form, publisher, GitHub environment, and required check names.

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
    - name: Create release tool environment
      run: uv venv --python 3.15 "$RUNNER_TEMP/release-tools"
    - name: Install locked release tools
      run: >-
        uv pip sync --preview-features pylock --python "$RUNNER_TEMP/release-tools/bin/python"
        --group release pylock.toml
    - name: Expose release tools
      run: echo "$RUNNER_TEMP/release-tools/bin" >>"$GITHUB_PATH"
    - uses: tox-dev/github-workflows/validate-news@SHA
```

Set `config` if Towncrier is configured in another Python project file. The Action expects a pull request base ref and a
Markdown or reStructuredText changelog. The caller should also run on `labeled` and `unlabeled` events, so a label added
after opening the PR updates the required check.

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

`resolve-pr-from-run` needs the source run ID and PR workflow path. Its optional `repository` input defaults to the
caller repository and is useful for a read-only external rehearsal. It outputs `number` and `bot-author`; `number` is
empty when the run's head is no longer the open PR head. It reads GitHub metadata and writes no repository files.
`label-bot-news` takes that verified number and bot flag. For `.changeset/<name>.md`, pass `fragments: .changeset` and
`fragment-style: changeset`; the default `towncrier` style expects `<name>.<category>.md` or RST. It only changes the
`skip news` label when the bot's fragment state and label disagree. A label change retriggers PR CI; the next label run
sees the settled state and makes no further write.

`validate-bot-credits` is an internal rehearsal Action with no inputs or outputs. Both release validation workflows use
it to fetch a known bot PR, link a synthetic fragment, and confirm that its notes keep the PR link without crediting the
bot. It reads public GitHub metadata and writes only temporary fixture files.

## Refresh release tools and hooks

Call `upgrade-release-tools.yaml` from a scheduled or manual workflow. Two read-only jobs run in parallel: one refreshes
the full project `pylock.toml`; the other updates exact pre-commit `additional_dependencies` pins. Both exclude releases
newer than seven days. They run `prek` and upload separate patches. pre-commit.ci owns hook revision updates and keeps
their frozen SHA format. The write job runs on the configured base branch when either patch changes. It accepts only the
configured lock and hook paths, then opens or updates one `dependencies` and `skip news` pull request and dispatches the
caller's check workflow. The write job needs Contents, Pull requests, and Actions write access. It does not use a
release App key.

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
      contents: write
      pull-requests: write
      actions: write
    with:
      python-version: '3.15'
      check-workflow: check.yaml
```

The project must declare a `release` group containing `prek` and `release-creator`. The lock also includes every other
group and extra. `lock` defaults to `pylock.toml`; `hook-config` defaults to `.pre-commit-config.yaml`; `base` defaults
to `main`; `branch` defaults to `automation/update-release-tools`. `check-workflow` names the caller's workflow file to
dispatch after a PR update. The caller owns the schedule, so repositories can use different upgrade days without copying
the jobs. `commit-message`, `pull-request-title`, and `pull-request-body` let a caller retain its existing dependency PR
wording.

Set `keep-uv-lock: true` only when the repository commits `uv.lock` for its own build. The lock job then refreshes both
`uv.lock` and the selectable `pylock.toml` and includes both in one patch. The default rejects `uv.lock` changes. This
is the path for toml-fmt's workspace lock.

Set `exclude-newer-packages` to one reviewed `package=UTC cutoff` entry per line when a required version was published
within the past seven days. Set that cutoff just after the latest file of the reviewed version was uploaded. The Action
uses the later of that timestamp and the rolling seven-day cutoff. Once the rolling cutoff passes the reviewed
timestamp, the exception expires and that package resumes normal weekly updates. The same rule applies to both locks
when `keep-uv-lock` is true. The dependency PR lists the reviewed floors.

To check the same lock refresh on a PR, call `refresh-release-lock` in a job with Contents read permission. The reusable
updater calls this Action in its lock generator job. It excludes dependencies published in the last seven days, resolves
the project through uv, rewrites the local `pylock.toml`, installs its `release` group, and runs `prek`. It rejects
changes to any other file; `uv.lock` is allowed only with `keep-uv-lock: true`. Its `changed` output is `true` when a
selected lock differs from the checkout, and it writes `$RUNNER_TEMP/lock.patch`. The Action does not push a branch,
open a PR, or request a write token.

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
    - id: lock
      uses: tox-dev/github-workflows/refresh-release-lock@SHA
      with:
        python-version: '3.15'
```

The caller must check out the PR head and install uv before the Action. The preview checks lock compilation and runs the
repository's hooks; the scheduled updater still owns the PR write path. A reusable workflow containing a write job
cannot be called with read-only permissions even when that job would skip, so use the composite Action for PR checks.

`refresh-hook-pins` is the matching read-only Action for hook updates. It freezes eligible repository revisions with
`prek update --freeze --cooldown-days 7`, refreshes exact `additional_dependencies` under the same age cutoff, and runs
all hooks. Its `config` input selects the pre-commit file, and `python-version` selects the interpreter used to resolve
hook dependencies. Its `changed` output is `true` only when that file changes, and it writes `$RUNNER_TEMP/hooks.patch`.
It fails if a hook modifies another file. The Action does not write to GitHub. pre-commit.ci can open separate
autoupdate pull requests outside this seven-day path; apply a separate age check before merging those updates.

Run the hook preview in its own job so its path check sees only the hook configuration change:

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

The [release preparation workflow](.github/workflows/prepare-release.yaml) in this repository is a complete caller. Its
`assemble` job creates a patch, its `validate` job runs release checks without a key, and its `push` job verifies the
patch digest and file modes before minting a repository-scoped App token. Copy those jobs, then set the changelog path,
fragment directory, commit message, and tag style. Replace this repository's relative `uses: $/…` references with a full
release commit SHA. In the examples below, `SHA` means that release commit and `TOKEN_ACTION_SHA` means the pinned token
Action commit in the linked workflow.

All three jobs need a full checkout (`fetch-depth: 0`, `persist-credentials: false`). Only `assemble` and `validate`
install `release-creator`, Towncrier, and `prek` from the caller's checked-in `pylock.toml`. Preparation needs
`contents: read` and `pull-requests: read` to resolve PR authors. The `push` job uses the `release-auth` environment
with `RELEASE_APP_PRIVATE_KEY` and the repository variable `RELEASE_APP_CLIENT_ID`. Restrict `release-auth` to the
release branch. Install the App on that repository only, with Contents write and Metadata read. Give it the necessary
branch and tag ruleset bypass.

```text
main + fragments
       │
       ▼
prepare-towncrier ── version + patch ──► upload artifact
                                             │
                                       validate + hash (no key)
                                             │
                                       apply + verify hash
                                             │
                                       mint App token
                                             │
                                             ▼
                                      commit-and-tag ──► main + tag
```

The tag starts the caller's publisher. Keep PyPI trusted publishing in that top-level workflow, in a separate job with
`id-token: write`:
[PyPI does not support trusted publishing inside reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github).
Run `prek` in a separate read-only job before building the tagged source. Repositories with the standard `uv` wheel and
sdist build can use `build-python-distribution` in both the tag publisher and the PR rehearsal. The
[self-release workflow](.github/workflows/release.yaml) shows the GitHub Release path; callers keep their ecosystem
uploads. The [read-only validation workflow](.github/workflows/validate-release.yaml) is called from both this
repository's PR check and tag release. It builds a local candidate for PRs, checks the tagged source, and renders the
Release body. The tag caller alone has a Contents write job that creates the GitHub Release.

## Validate a Python release

`validate-python-release.yaml` runs the shared Towncrier, package build, and note-rendering path from an exact PR head
or an existing tag. A rehearsal squashes the proposed changes onto its base, adds named and numbered bug-fix fragments,
and creates a commit and tag in the runner. It prepares and checks the changelog patch, runs `prek` on the candidate,
builds the wheel and sdist, and checks both entries' links and author credits. It also checks rejection of unsupported
or missing fragments, a dirty checkout, an existing release tag, a stale release branch, a patch with an unrelated file,
an invalid tag, and a missing changelog. The local commit and tag never leave the runner. The same tagged-source
rendering step runs on the local PR tag and on a real tag; the PR also renders a separate copy with its contributor
fixture. The workflow uses `$/` for its own Actions, so a caller pinned to a workflow commit runs those Actions from the
same commit.

Call the pinned workflow from the tag publisher's build job:

```yaml
build:
  uses: >-
    tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
  permissions:
    contents: read
    pull-requests: read
  with:
    changelog: CHANGELOG.md
    fragments: changelog.d
    format: markdown
    artifact-base-url: https://pypi.org/project/example/
```

`changelog` and `fragments` are the paths in `tool.towncrier`; `format` is `markdown` for an `mdformat` hook, `rst` for
a `docstrfmt` hook, or `none` when no formatter hook applies. `artifact-base-url` ends just before the version; the
workflow appends `1.2.3/` for tag `1.2.3`. Set it to the package's actual PyPI project path. `artifact-label` changes
the link text from `PyPI release`; `issue-role` selects whether reStructuredText `:issue:` references link to issues or
pull requests. `lock` defaults to `pylock.toml` and must have a `release` group with `release-creator`, Towncrier, and
`prek`. `python-version` defaults to `3.15`; `source` defaults to the repository root for `uv build`. `artifact-prefix`
defaults to empty; set it while comparing this workflow with an existing PR rehearsal so the two jobs use distinct
artifact names. Set `local-tool-source: true` for release-creator's own release: the keyless jobs install the tagged
checkout from its locked release, fix, build, and runtime groups instead of using a published release-creator wheel.

For an RST changelog, use `format: rst` when the caller has a `docstrfmt` hook; otherwise use `format: none`. The
workflow creates `.rst` test fragments from the changelog suffix and checks RST PR references in the assembled section.
If the repository uses `:issue:` roles, set `fixture-issue` to an existing issue number. The PR rehearsal then checks
its GitHub issue link in the rendered notes. The input has no effect on an existing tag:

```yaml
with:
  changelog: docs/changelog.rst
  fragments: docs/changelog
  format: rst
  fixture-issue: '31'
  artifact-base-url: https://pypi.org/project/filelock/
```

The shared repository's [Check workflow](.github/workflows/check.yaml) dispatches the rehearsal for a consumer PR. No
rehearsal job is added to the consumer's PR workflow.

On a tag, it validates the changelog and notes before building, matching the existing caller order. The job uploads
`python-package-distributions` with the wheel and sdist, and `release-validation-notes` with the body rendered from the
tagged source. On a PR it also uploads `release-dry-run` with the patch, assembled changelog, notes, contributor
fixture, no-metadata tag preview, and distribution hashes. A tag run has no fixture, so its notes lack GitHub
contributor metadata. The tag-only GitHub Release job must fetch generated notes with Contents write, rerender with
`render-release-notes`, and create the Release after the ecosystem upload. PyPI OIDC stays in the caller's separate
`release` environment job:
[PyPI does not support trusted publishing inside reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github).

## Rehearse an exact PR head

Dispatch the shared `check.yaml` workflow against the ref that contains the rehearsal code. Use the shared PR branch
while reviewing it, then `main` after merge. The command below runs on GitHub's Ubuntu runner and checks the current
head of `tox-dev/python-discovery` PR #156. Replace the SHA after every PR push; the job fails if the PR has moved.
`artifact-base-url` ends before the version, and `format` matches the changelog's `prek` formatter.

```bash
gh workflow run check.yaml \
  --repo tox-dev/github-workflows \
  --ref SHARED_WORKFLOW_REF \
  -f repository=tox-dev/python-discovery \
  -f head-sha=PR_HEAD_SHA \
  -f pull-request=156 \
  -f changelog=docs/changelog.rst \
  -f fragments=docs/changelog \
  -f format=rst \
  -f artifact-base-url=https://pypi.org/project/python-discovery/
```

The dispatch accepts `fixture-issue` for an RST issue-link probe, `issue-role` (`issue` or `pull`), and `lock`
(`pylock.toml` by default). It checks out the requested public repository at the SHA, verifies that GitHub still reports
that exact PR head, then uses a local bare Git remote for the candidate commit and tag. The job receives Contents read
and Pull requests read; it has no App key, OIDC publish permission, GitHub Release write, or GitHub push step. It
uploads `release-dry-run`, `release-validation-notes`, and `python-package-distributions` under the shared repository's
run. The artifacts include the generated patch, changelog, notes, contributor fixture, hashes, wheel, and sdist.
Download them and compare their content with the caller's tag path before marking the no-publish gate complete.

## Prepare and tag with one reusable workflow

`prepare-towncrier-release.yaml` runs three jobs. The first selects a tag and writes a Towncrier patch in a checkout
without the App key. The second applies that patch in another keyless checkout, runs `prek`, and records its digest. The
last job checks the digest, reads the caller's `release-auth` environment, and uses a repository-scoped App token to
push the release commit and tag together. Only a dispatch from `main` can reach that job.

```text
jobs:
  prepare:
    if: github.ref == 'refs/heads/main'
    uses: tox-dev/github-workflows/.github/workflows/prepare-towncrier-release.yaml@SHA
    permissions:
      contents: read
      pull-requests: read
    with:
      bump: ${{ inputs.bump }}
      changelog: CHANGELOG.md
      fragments: changelog.d
      format: markdown
      tag-prefix: v
      annotated: true
    secrets:
      RELEASE_APP_PRIVATE_KEY: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
```

The caller supplies the `release-auth` environment secret by name; the App client ID comes from that environment's
`RELEASE_APP_CLIENT_ID` variable. The workflow requests Contents write only for the current repository. The caller
grants its GitHub token Contents and Pull requests read. The keyless jobs install the `release` group from the
checked-in `pylock.toml`; use `lock` and `python-version` when those paths or versions differ. No job output crosses
back to the caller. A successful run pushes a tag, which the caller's tag workflow handles.

`bump`, `tag-prefix`, `changelog`, `fragments`, `format`, `link-fragments`, `numbered-prs`, and `annotated` have the
same meanings as the `prepare-towncrier` inputs below. `release-auth-deployment` defaults to `true`; set it to `false`
if the current App-key job uses `release-auth` without creating a GitHub Deployment. `dry-run: true` runs the first two
jobs at a same-repository PR head and skips the App-key job. `local-tool-source: true` installs release-creator from the
tagged checkout with locked third-party dependencies in both keyless jobs; use it for release-creator itself. The caller
can place repository-specific checks in a preceding job and make this job depend on it. The tag-triggered ecosystem
publisher stays in the caller repository.

## Prepare Towncrier release

`prepare-towncrier` reads a clean checkout, chooses the next version, links fragments to their squash PRs, runs
Towncrier and `prek`, and writes a binary Git patch. It does not commit or push. It fails if version selection, notes
rendering, formatting, or checks fail, or if preparation creates untracked files or no patch.

```yaml
  - id: prepare
    uses: tox-dev/github-workflows/prepare-towncrier@SHA
    with:
      bump: ${{ inputs.bump }}
      changelog: docs/changelog.md
      fragments: docs/changelog.d
      format: markdown
      patch: ${{ runner.temp }}/release.patch
```

- `bump`: `auto` (default), `major`, `minor`, `patch`, or `calver`. Passed to `release-creator tags --next`; `auto` uses
  the pending fragments. The caller's dispatch form decides which choices to expose.
- `tag-prefix`: Empty by default. Use `v` when release tags are spelled `v1.2.3`; version comparison still includes
  unprefixed numeric tags in the repository's history. Towncrier writes the changelog heading without the `v`.
- `version`: Explicit version for a caller with its own version selector. It takes precedence over `bump`; the Action
  still checks that it is newer than existing tags.
- `changelog` **(required)**: Tracked file Towncrier writes, such as `CHANGELOG.md` or `docs/changelog.rst`. This must
  match `tool.towncrier.filename` in the caller's `pyproject.toml`.
- `fragments`: Fragment directory relative to the checkout root; default `changelog.d`. Set this to the caller's
  `tool.towncrier.directory`. Version selection and PR linking both read this directory.
- `format`: `none` (default), `markdown`, or `rst`. `markdown` runs the caller's `mdformat` hook and `rst` runs its
  `docstrfmt` hook through `prek` on the assembled changelog. Use `none` when no formatter hook applies. The full `prek`
  suite runs for every option.
- `link-fragments`: `true` (default) resolves named fragments and authors through GitHub; `false` skips that step for a
  caller whose fragments already contain release links and credits.
- `numbered-prs`: `false` (default) leaves Towncrier's numeric fragment behavior intact. Set `true` only when every
  numeric fragment stem is the original pull request number; the linked PR and its authors come from that number.
- `patch` **(required)**: Writable path to the Git patch, usually under `runner.temp`. Upload this exact file as an
  artifact for the validation job.
- `repository`: GitHub owner/repository used for fragment author links; defaults to the workflow caller. The external
  rehearsal sets this to the consumer repository.

**Output:** `version` is the selected tag string. Use `steps.prepare.outputs.version` as a job output and pass it to
both later Actions. **Working-tree effect:** Towncrier changes the changelog and consumes fragments; the patch records
those changes. The checkout must be clean before this Action starts.

## Validate release patch

`validate-release-patch` starts from a fresh checkout of the original branch commit. It rejects a branch that moved,
applies the uploaded patch, checks its changed paths and file modes, renders the requested version with
`release-creator`, and runs `prek`. It leaves the patch staged for the commit Action. Run it in a keyless validation
job. The App-key job repeats the branch, digest, path, and mode checks with `checks: "false"`, without installing
release tools.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@SHA
    with:
      version: ${{ needs.assemble.outputs.version }}
      patch: ${{ runner.temp }}/release-patch/release.patch
      changelog: docs/changelog.md
      fragments: docs/changelog.d
```

- `version` **(required)**: Exact tag chosen by preparation. `release-creator notes` must find one valid section for it.
- `patch` **(required)**: Local path of the downloaded patch artifact, not an artifact name or URL.
- `changelog` **(required)**: Same tracked path passed to preparation. Only this file and files below `fragments` may
  change in the patch.
- `fragments` **(required)**: Same directory passed to preparation. Towncrier may consume or rename its files.
- `branch`: Protected release branch; default `main`.
- `remote`: Git remote fetched for the freshness check; default `origin`.
- `expected-sha`: Commit that preparation checked out. By default the Action uses `GITHUB_SHA`; set this when
  preparation used another commit.
- `repository`: GitHub owner/repository used to check the changelog's links; defaults to the workflow caller. The
  external rehearsal sets this to the consumer repository.
- `expected-patch-sha`: SHA-256 digest of the patch from a separate keyless validation job. The Action rejects a
  different downloaded patch before applying it.
- `checks`: `true` (default) runs `release-creator` and `prek`; `false` only applies and checks the validated patch.

**Output:** No named output. **Working-tree effect:** Applies and stages the patch. A failed `prek` run, unexpected path
or mode, or modification by `prek` fails the keyless job. The key job accepts only the validated digest.

## Commit and tag release

`commit-and-tag` accepts only a staged release patch in a clean working tree. It commits with the GitHub App bot
identity, creates the tag, and atomically pushes the branch and tag to `origin`. A rejected push leaves neither remote
ref updated. Mint the token after validation with `actions/create-github-app-token`, narrowed to this repository and
Contents write.

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
- `branch`: Target branch; default `main`. The checkout must still be at its validated commit.
- `annotated`: `false` (default) creates a lightweight tag; `true` creates an annotated tag. Match the repository's
  existing release history.

**Output:** No named output. **Remote effect:** One new commit on `branch` and one tag at that commit. The App needs a
branch and tag ruleset bypass. A stale branch, invalid tag, or ruleset rejection fails the push.

## Build Python distribution

`build-python-distribution` builds a wheel and sdist with `uv`. Call it after a separate read-only `prek` job,
`actions/checkout`, and `astral-sh/setup-uv`. The caller verifies the tag and changelog section before this Action. Use
the same Action and inputs after the local tag in the PR rehearsal; this executes the build steps used by the tag
publisher without publishing the artifacts.

```yaml
  - uses: tox-dev/github-workflows/build-python-distribution@SHA
    with:
      python-version: '3.15'
      source: .
      out-dir: dist
```

- `python-version`: Managed Python used for the build; default `3.15`.
- `lock`: Full project lock containing the build backend; default `pylock.toml`.
- `source`: Source directory passed to `uv build`; default `.`.
- `local-tool-source`: `false` (default). Set `true` only when the tagged source is release-creator itself; the keyless
  planner installs it from that checkout after syncing locked backend and runtime dependencies.
- `out-dir`: Directory for the wheel and sdist; default `dist`. Validate files in this directory before upload.

**Output:** No named output. **Working-tree effect:** Writes a wheel and sdist to `out-dir`. The checkout must be clean
before the Action starts. The build backend comes from the lock's `build` selection with pinned versions and hashes;
`uv build` rejects a missing hash. Use a separate build path for repositories whose build command differs from
`uv build --sdist --wheel`.

## Validate Python distribution

`validate-python-distribution` runs Twine and check-wheel-contents on the files the build job will upload. It installs
both tools from the caller's full project lock. Run it after `build-python-distribution` and before `upload-artifact`,
using the same output directory. The standard Python release rehearsal calls it on its candidate files too.

```yaml
  - uses: tox-dev/github-workflows/validate-python-distribution@SHA
    with:
      lock: pylock.toml
      validation-group: pkg-meta
      out-dir: dist
```

- `lock`: Full project lock containing the validation group; default `pylock.toml`.
- `python-version`: Managed Python for the validators; default `3.15`.
- `validation-group`: Group containing Twine and check-wheel-contents; default `pkg-meta`. Use `release` for projects
  that lock these tools there.
- `out-dir`: Directory containing the wheel and sdist; default `dist`. The Action checks these exact paths and has no
  output artifact of its own.

**Output:** No named output. **Working-tree effect:** None. An invalid sdist or wheel stops before the artifact upload.

## Render GitHub Release notes

`render-release-notes` checks the tag and its changelog section, finds the previous tag, and renders an unwrapped GitHub
Release body with `release-creator`. Call it on the local tag in a PR rehearsal and again on the actual tag. The
publisher still fetches GitHub's generated notes and creates the Release; this Action only writes a local Markdown file.

```yaml
  - uses: tox-dev/github-workflows/render-release-notes@SHA
    with:
      tag: ${{ github.ref_name }}
      changelog: CHANGELOG.md
      repository: ${{ github.repository }}
      artifact-url: https://pypi.org/project/example/${{ github.ref_name }}/
      generated-notes: ${{ runner.temp }}/generated-notes.md
      output: ${{ runner.temp }}/release-notes.md
```

- `tag` **(required)**: Release version, such as `1.2.3`. The checkout must contain its changelog section. A local PR
  rehearsal creates this tag without pushing it to GitHub.
- `changelog` **(required)**: Tracked Markdown or reStructuredText changelog in the format that `release-creator notes`
  parses, with exactly one section for the tag.
- `repository` **(required)**: GitHub `owner/repository` used in PR and comparison links.
- `package`: Package name for a repository with separate histories, such as `pyproject-fmt` in `toml-fmt`. Use it with
  tags like `pyproject-fmt/2.30.3`; the Action selects that package's changelog section and previous tag only.
- `artifact-url`: Ecosystem release URL, such as a PyPI version page. Omit it for a GitHub-only project.
- `artifact-label`: Link text for `artifact-url`; default `PyPI release`. Use `Zipapp` or another product name for a
  different artifact.
- `issue-role`: For reStructuredText, whether `:issue:` links target GitHub issues (default) or pull requests.
- `generated-notes`: Path to GitHub's generated-notes body. The tag publisher fetches it after PyPI publication; a PR
  rehearsal supplies a small fixture with its actual PR author and URL. This preserves New Contributors and fills any
  missing `by @handle` credit. Omit it when the release has no GitHub-generated contributor metadata.
- `output` **(required)**: Writable path for the GitHub Release body. Pass it to `gh release create --notes-file` only
  after the ecosystem publisher succeeds.

**Output:** `previous` is the nearest earlier version tag, or empty for the first release. **Working-tree effect:** The
Action writes only `output`. It rejects an invalid tag, a missing heading, an empty body, or a missing comparison link
when an earlier tag exists. It neither fetches generated notes nor writes a GitHub Release, so a PR job needs only read
permissions. Fetching generated notes uses GitHub's release endpoint and needs Contents write in the tag publisher.

## Reconcile PyPI artifacts

`reconcile-pypi-artifacts` compares the complete local distribution directory with PyPI's filenames and SHA256 digests.
Run `stage` in a read-only job before trusted publishing. It returns `missing-count` and a `manifest` path listing files
PyPI lacks. Upload only that small manifest between jobs, along with the original distribution artifact. Do not upload
the stage job's copied files. The OIDC job downloads the original files and manifest, then calls `select-pypi-artifacts`
to copy only named original bytes into a fresh upload directory. It needs no checkout or release-tool installation. Call
the pinned PyPI publisher on that directory only when `selected-count` is nonzero.

After upload, run `reconcile-pypi-artifacts` with `mode: verify` in another read-only job against the original complete
distribution set. It waits up to 120 seconds for a complete PyPI JSON response. A different digest, unexpected or yanked
file, or API error other than a missing release fails immediately. The GitHub Release writer must depend on this
verification. A full workflow rerun restages missing files. For a failed-jobs rerun after a partial upload, set PyPI
publisher `skip-existing: true` only for this selected subset; the separate full-set verification still rejects changed
or extra files before GitHub publication.

```yaml
  - id: pypi
    uses: tox-dev/github-workflows/reconcile-pypi-artifacts@SHA
    with:
      project: example
      version: ${{ github.ref_name }}
      dist: dist
      mode: stage
      missing-dir: missing
```

`project`, `version`, `dist`, and `mode` are required. `mode` is `stage` or `verify`. `missing-dir` defaults to
`missing` and must be a fresh directory outside `dist`. `wait-seconds` defaults to 120 for verify. `lock` defaults to
`pylock.toml`, whose `release` group supplies the command; `python-version` defaults to 3.15. Set
`local-tool-source: "true"` only when releasing release-creator itself: it installs the tagged checkout without
resolving dependencies after installing its locked release, build, and runtime groups. This Action writes only the
missing directory, manifest, and `missing-count`; it never uploads to PyPI. Use `mode: verify` after the OIDC job,
including when `missing-count` was zero.

`select-pypi-artifacts` takes `dist`, `manifest`, `output-dir`, and `expected-count` from stage's `missing-count`. The
output directory must be fresh and outside `dist`. It rejects unknown, duplicate, unsafe, or symlinked filenames and
copies bytes only from `dist`. Its `selected-count` output controls the PyPI upload step. The manifest supplies names
only; it is not a source of publishable bytes.

For a build matrix whose jobs each hold one distribution artifact, set `partitioned: "true"` and omit `expected-count`.
Each cell selects names present in its original artifact and uploads its `selected-manifest` as a separate artifact.
Before public release, download all cell manifests into one directory and run `verify-pypi-partitions` with the global
stage `manifest`, `partitions-dir`, and `expected-partitions`. It rejects duplicate, missing, and extra names. The
keyless full-set PyPI verification still checks the published bytes.

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
      repository: ${{ github.repository }}
      tag: ${{ github.ref_name }}
      commit: ${{ github.sha }}
      title: ${{ github.ref_name }}
      notes-file: ${{ runner.temp }}/release-notes.md
```

- `repository`, `tag`, `commit`, `title`, and `notes-file` are required. `commit` is the commit the existing tag must
  resolve to. `title` and the file bytes must match an existing Release exactly.
- `assets-directory`: Optional directory containing only the assets to attach. The Action compares each filename and
  SHA256 digest with GitHub's Release asset metadata, uploads missing draft assets, and rejects extra or changed assets.
- `prerelease`: `true` or `false`; default `false`. It must match an existing Release.
- `mode`: `complete` (default) creates or resumes a draft and publishes it in one call. `stage` creates or resumes a
  draft and uploads assets without publishing. `publish` requires an existing draft and publishes it after checking the
  tag, notes, and complete asset set again.

**Output:** No named output. **Remote effect:** Depending on `mode`, the Action creates or resumes a draft, uploads
missing assets, and publishes only after the complete asset set matches. A matching published Release causes no write. A
different body, title, tag commit, prerelease flag, or asset set fails without changing the existing Release. A failed
upload leaves the draft for a later retry. An asset in GitHub's incomplete `starter` state requires manual cleanup
before retrying.

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
      sha256: ${{ needs.build-signed.outputs.archive_sha }}
      plugin-id: '29973'
      channel: ''
```

`archive`, `sha256`, and numeric `plugin-id` are required. `channel` is empty for Stable; use a Marketplace channel name
for a prerelease. **Output:** None. **Remote effect:** One multipart upload to JetBrains Marketplace. The Action does
not check whether this version was published already; use the keyless release-creator `marketplace --mode stage` check
before the upload, and `--mode verify` afterward. A retry must compare the published ZIP's member digests before
skipping an upload because Marketplace can repackage the outer ZIP.

## Check a caller before switching

The [Actions test suite](tests) executes each inline `run:` block in temporary Git repositories. The
[`release-dry-run` job](.github/workflows/check.yaml) invokes the composite Actions on a GitHub runner against a local
bare remote. It cannot prove that another repository's Towncrier template, release hooks, package build, or publisher
works. Run that caller's prepare and validation path at its PR head without pushing a GitHub ref or publishing an
artifact. Inspect the version, patch, changelog, notes, and built package before changing its live release workflow.

This repository releases its own Actions with the same prepare and tag path. See [Contributing](CONTRIBUTING.md) for
local checks and news fragments, and [Changelog](CHANGELOG.md) for released changes.

# Changelog

<!-- towncrier release notes start -->

<a name="release-3-1-1"></a>

## 3.1.1 (2026-10-24)

<a name="release-3-1-1-fixed"></a>

### Fixed

- Require both Linux mise release archives to age seven days before refreshing the pinned binary
  ([#17](https://github.com/tox-dev/github-workflows/pull/17)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-3-1-0"></a>

## 3.1.0 (2026-10-24)

<a name="release-3-1-0-added"></a>

### Added

- Add a keyless Action to refresh the signed mise binary pin after its GitHub Release has aged seven days
  ([#16](https://github.com/tox-dev/github-workflows/pull/16)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-3-0-1"></a>

## 3.0.1 (2026-10-24)

<a name="release-3-0-1-fixed"></a>

### Fixed

- Count a fork PR's hook revision after seven days when GitHub omits the PR link from its workflow run. The run must
  match the fork repository, branch, commit, and workflow, and occur after the PR opened
  ([#15](https://github.com/tox-dev/github-workflows/pull/15)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-3-0-1-breaking-changes"></a>

### Breaking changes

- The tagged `source-check` job of `validate-python-release` requests `actions: read` and `pull-requests: read` and
  checks out full history for the hook age check. A caller whose `build` job grants only `contents: read` fails at
  startup; grant all three. This entry was added after the release, which shipped without it.

<a name="release-3-0-1-security"></a>

### Security

- Use uv 0.13.5 or newer to avoid the compromised certificate root in earlier releases. Install the exact, hash-checked
  resolver from the shared lock for lock checks and weekly refresh, and update setup-uv to a release that boots patched
  uv ([#15](https://github.com/tox-dev/github-workflows/pull/15)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-3-0-0"></a>

## 3.0.0 (2026-10-24)

<a name="release-3-0-0-added"></a>

### Added

- Refresh and check a selectable project lock containing runtime dependencies, every extra, and every dependency group.
  Release jobs still install only their selected, cooled groups
  ([#14](https://github.com/tox-dev/github-workflows/pull/14)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-3-0-0-fixed"></a>

### Fixed

- Check the cooldown, immutable hook revisions, and complete Python hook dependency pins on every pull request that
  changes the hook configuration, including human and fork pull requests. Check the hook pins again before running hooks
  from a release tag. Allow the first complete set of managed pins in a human PR while keeping later pin changes limited
  to the release App. Run hook installs from PyPI with the seven-day cutoff, ignoring repository uv configuration
  ([#14](https://github.com/tox-dev/github-workflows/pull/14)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-3-0-0-breaking-changes"></a>

### Breaking changes

- Require a release tag, source commit, signed ZIP artifact, and release notes artifact when publishing a JetBrains
  plugin. The Action now records an acceptance receipt and blocks an ambiguous retry until a maintainer reconciles the
  Marketplace update. Publishing now requires Deployments read access and a `release` environment so retries can detect
  prior attempts after Actions runs or receipt artifacts expire
  ([#14](https://github.com/tox-dev/github-workflows/pull/14)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-1"></a>

## 2.0.1 (2026-10-24)

<a name="release-2-0-1-fixed"></a>

### Fixed

- Allow human fork pull requests to pass the hook update check while keeping bot updates limited to the repository
  ([#13](https://github.com/tox-dev/github-workflows/pull/13)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-0"></a>

## 2.0.0 (2026-10-24)

<a name="release-2-0-0-added"></a>

### Added

- `install-locked-tools` and `export-build-constraints` can verify selected groups from a separate lock against PyPI and
  the seven-day cutoff before its packages enter a release artifact
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-0-changes"></a>

### Changes

- Download tagged release build artifacts by the IDs produced by their upload jobs
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Lock the released release-creator 1.0.0 CLI used by the weekly hook updater and allow its reviewed artifacts during
  the seven-day cooldown ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Refresh the package index when checking or updating a lock so a cached listing cannot hide a newly published version
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-0-fixed"></a>

### Fixed

- Keep the lock reader's certificate package installed when a job switches between Nab tools and other release groups
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Report malformed PyPI Simple API listings as lock verification errors instead of Python tracebacks
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Retry a PyPI artifact listing or transient 404 that lags a new release before rejecting a matching release lock
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Retry transient PyPI metadata connection errors before rejecting a release lock
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Return the selected version from the Towncrier finalization phase and reject a finalization without one
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-0-breaking-changes"></a>

### Breaking changes

- Remove `recheck-hook-update-cooldown.minimum-days` and the unused `validate-python-release` inputs `changelog`,
  `artifact-base-url`, `artifact-label`, and `local-tool-source`. Recheck uses a fixed seven-day minimum; release notes
  are rendered by the caller's notes job ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the unused `build-python-distribution.source` input. The build Action uses the repository root
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the unused `working-directory` input from the release patch and Towncrier configuration Actions. They operate
  on the current checkout ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-0-security"></a>

### Security

- Apply separate path allowlists to lock and hook update patches before the App writes the dependency branch
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Apply the seven-day package cutoff when release and CI jobs install prek hook environments
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Check changed release locks against project requirements in pull requests, including every declared release group
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Check packages selected from a lock without dependency groups under the same marker selection used to export build
  constraints ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Check release lock artifacts against PyPI metadata before installing release tools, including their hashes, upload
  times, and index origin. Use a pinned CA bundle for the metadata request
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Check release lock markers for the exact dependency groups each job installs, so a condition that excludes the build
  group cannot bypass cooling ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Check secondary release locks during pull request news validation when callers pass their secondary lock and matrix
  inputs ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Recalculate the release version in the keyless validation job before the App-token writer accepts an assembled patch
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Reject bot hook updates that change configuration beyond revisions
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Require the generated release-tool update PR to pass the same seven-day hook revision check as other bot PRs
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Use a pinned CA bundle when comparing published PyPI files with local release artifacts
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Validate the lock when a pull request changes `nab.toml`, including callers that use `validate-news` directly
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Validate the uploaded release patch in a separate keyless job before the App-key writer pushes it
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).
- Verify the configured release App before accepting its dependency update PR, and check changed hook pins against
  cooled PyPI files while retaining hook revision cooldowns ([#12](https://github.com/tox-dev/github-workflows/pull/12))
  by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-2-0-0-performance"></a>

### Performance

- Install only the lock reader during release jobs; keep Nab in lock refresh jobs
  ([#12](https://github.com/tox-dev/github-workflows/pull/12)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-5"></a>

## 1.0.5 (2026-10-23)

<a name="release-1-0-5-fixed"></a>

### Fixed

- Expose the locally built release-creator command before it prepares its own changelog
  ([#11](https://github.com/tox-dev/github-workflows/pull/11)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-4"></a>

## 1.0.4 (2026-10-23)

<a name="release-1-0-4-fixed"></a>

### Fixed

- Ignore legacy PyPI files from post and development releases when verifying an earlier release
  ([#10](https://github.com/tox-dev/github-workflows/pull/10)) by [@gaborbernat](https://github.com/gaborbernat).
- Retry transient TLS and truncated JSON responses while verifying PyPI files
  ([#10](https://github.com/tox-dev/github-workflows/pull/10)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-3"></a>

## 1.0.3 (2026-10-23)

<a name="release-1-0-3-fixed"></a>

### Fixed

- Expose locked release commands without replacing the runner's Python, pip, or uv executables in later workflow steps
  ([#9](https://github.com/tox-dev/github-workflows/pull/9)) by [@gaborbernat](https://github.com/gaborbernat).
- Reject a yanked PyPI file even when its yank reason is empty
  ([#9](https://github.com/tox-dev/github-workflows/pull/9)) by [@gaborbernat](https://github.com/gaborbernat).
- Retry incomplete PyPI listing responses while waiting for published files, then report a concise error if the wait
  expires ([#9](https://github.com/tox-dev/github-workflows/pull/9)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-3-documentation"></a>

### Documentation

- Document the build-constraint inputs of `install-locked-tools` and correct the 1.0.0 migration notes for removed
  inputs and PATH behavior ([#9](https://github.com/tox-dev/github-workflows/pull/9)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-2"></a>

## 1.0.2 (2026-10-23)

<a name="release-1-0-2-changes"></a>

### Changes

- Accept release-creator 0.6.6 in caller locks under its reviewed PyPI upload cutoff
  ([#8](https://github.com/tox-dev/github-workflows/pull/8)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-2-documentation"></a>

### Documentation

- Correct the documented release validation and previous-tag Action interfaces
  ([#8](https://github.com/tox-dev/github-workflows/pull/8)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-1"></a>

## 1.0.1 (2026-10-23)

<a name="release-1-0-1-fixed"></a>

### Fixed

- Allow release jobs to use release-creator 0.6.5 under its reviewed upload cutoff
  ([#7](https://github.com/tox-dev/github-workflows/pull/7)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-0"></a>

## 1.0.0 (2026-10-23)

<a name="release-1-0-0-changes"></a>

### Changes

- Run changelog checks in a separate workflow so label changes do not restart the test matrix
  ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by [@gaborbernat](https://github.com/gaborbernat).
- Run release-tool checks and build-constraint export outside the job that builds distribution files
  ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by [@gaborbernat](https://github.com/gaborbernat).
- Add `constraints-lock`, `target-platform`, and `targets` inputs and the `build-constraints` output to
  `install-locked-tools` ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-0-fixed"></a>

### Fixed

- Compare the complete local distribution set with PyPI, reject yanked or changed files, and verify each published
  file's attestation ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Reject future-dated locks and release dependencies that were uploaded too recently. Keep deliberate package holds
  during weekly lock refreshes ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Select the previous release tag from the same package when a repository uses package-prefixed tags
  ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-1-0-0-breaking-changes"></a>

### Breaking changes

- Remove the `install-nab`, `label-bot-news`, `refresh-hook-pins`, `resolve-pr-from-run`, and
  `validate-python-distribution` Actions. `select-previous-tag` no longer accepts `package`, `executable`, or
  `stable-only`; `reconcile-pypi-artifacts` no longer accepts `local-tool-source`; `validate-release-patch` no longer
  accepts `expected-patch-sha`; and `render-release-notes` no longer emits `previous`. The release validation workflow
  no longer uploads the `release-validation-notes` artifact ([#6](https://github.com/tox-dev/github-workflows/pull/6))
  by [@gaborbernat](https://github.com/gaborbernat).
- `install-locked-tools` now adds its selected virtual environment to `GITHUB_PATH`, so later bare `python` commands
  resolve to that environment ([#6](https://github.com/tox-dev/github-workflows/pull/6)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-4-1"></a>

## 0.4.1 (2026-10-23)

<a name="release-0-4-1-fixed"></a>

### Fixed

- Install locked release tools on macOS Intel and Windows ARM runners
  ([#5](https://github.com/tox-dev/github-workflows/pull/5)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-4-0"></a>

## 0.4.0 (2026-10-23)

<a name="release-0-4-0-added"></a>

### Added

- Refresh a secondary pylock for project runtime dependencies, including a separate Python and platform matrix
  ([#4](https://github.com/tox-dev/github-workflows/pull/4)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-4-0-fixed"></a>

### Fixed

- Allow repeated lock-tool setup on Windows and check caller release-creator versions against the selected groups
  ([#4](https://github.com/tox-dev/github-workflows/pull/4)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove partial GitHub Release assets before retrying an upload in the same run
  ([#4](https://github.com/tox-dev/github-workflows/pull/4)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-4-0-security"></a>

### Security

- Enforce the seven-day Nab cutoff for global and package rules, including disabled or shortened cutoffs
  ([#4](https://github.com/tox-dev/github-workflows/pull/4)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-3-0"></a>

## 0.3.0 (2026-10-23)

<a name="release-0-3-0-added"></a>

### Added

- Add a credential-only JetBrains Marketplace upload Action for a verified signed ZIP
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Build a Python wheel and sdist after a separate tagged-source check, using hashed build backend pins from the full
  project lock. Check the exact wheel and sdist with Twine and check-wheel-contents before uploading them
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Check the age of the current `pre-commit.ci` pull request head before a required CI gate permits a hook update
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Create or resume an App-authored post-release pull request, verifying the branch and changed files before a retry
  succeeds ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Label bot pull requests after read-only CI, including forks and failed checks
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Label bot pull requests without news fragments from a no-checkout workflow, and remove the label when a bot adds news
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Let release callers calculate `v`-prefixed tags without typing a version
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Offer a read-only tagged-source workflow for notes, wheel and sdist builds, and distribution checks before publishing
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Refresh exact pre-commit hook dependency pins in the weekly release-tool PR, with an opt-in to retain a project's
  checked-in `uv.lock` alongside its selectable `pylock.toml`. Allow explicit package exceptions to the seven-day cutoff
  when a declared minimum is newer than that cutoff ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Render GitHub Release notes for independently tagged packages in one repository
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Render GitHub Release notes from a tagged changelog in tag publishers
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Share the release-tool lock updater across repositories while keeping each caller's schedule and checks, and expose
  its read-only generator for PR validation ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Sign a JetBrains plugin ZIP in an isolated job after verifying the unsigned build artifact and pinned signing tool
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Stage and resume a draft GitHub Release, then publish it after ecosystem verification. Tag reruns verify the exact
  notes and assets before succeeding ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Stage only PyPI files absent from an identical release, then verify the complete published artifact set before writing
  the GitHub Release ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Validate pull request changelog fragments in a shared Action, with bot author handling that does not depend on label
  timing ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-3-0-fixed"></a>

### Fixed

- Check shell commands from workflows in `.github` with ShellCheck and shfmt
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Combine shared build pins with a caller's build group so source dependencies can install on Python 3.15
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Download the release patch by its uploaded artifact ID, so a same-named artifact cannot replace it in a later job
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Fail release patch validation when Git cannot list the changed paths, modes, or RST lines
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Fetch the PR base branch for changelog checks, which compare the PR head with `origin/main`
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Keep the required check from reporting a failure after its run is cancelled
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Let Towncrier callers preserve `v`-prefixed changelog headings independently of their release tag prefix
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Read every label before changing the skip news label on a bot pull request
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Recheck mature bot hook updates each day and continue after a failed GitHub job rerun
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Reject fragment filenames that would publish without a pull request link or author credit
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Report an empty dependency group selection before trying to install release tools
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Resolve Action inputs and step outputs by their declared names in the local test runner
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Retry failed GitHub Release reads without repeating asset uploads or publication
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Run the type-check tox environment with current test dependencies without installing them twice
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Show the JetBrains Marketplace response when an upload fails
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Upload signed JetBrains plugins when the runner temporary path contains commas or semicolons
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Use the tagged commit time when building Python distributions so a retry produces the same bytes
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Validate linked reStructuredText release headings when applying a release patch
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-3-0-documentation"></a>

### Documentation

- Correct the release job order, checkout requirements, retry behavior, and hook rerun window in the Action guide
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-3-0-security"></a>

### Security

- Apply the seven-day hook revision check to App-authored dependency pull requests
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Check the prepared commit's committer and message before opening a post-release pull request
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Reject an existing signed ZIP and mask decoded JetBrains signing key material
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Require a release tag to point to a commit on main before publishing
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Validate release patches without the App key, then recheck their digest, paths, and file modes before minting a token
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-3-0-performance"></a>

### Performance

- Cache pre-commit hooks and use shallow checkouts where release checks need no history
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Limit hook cooldown history requests to workflow runs older than the required waiting period
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).
- Run formatting, inline shell checks, tests, and type checks in parallel
  ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-3-0-packaging"></a>

### Packaging

- Declare the MIT license and its file in project metadata ([#3](https://github.com/tox-dev/github-workflows/pull/3)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-2-0"></a>

## 0.2.0 (2026-10-19)

<a name="release-0-2-0-added"></a>

### Added

- Support Towncrier fragment directories outside the repository root during version selection and PR linking.
  ([#2](https://github.com/tox-dev/github-workflows/pull/2)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-2-0-documentation"></a>

### Documentation

- Put the Action setup and input reference in the repository README, with examples for each step
  ([#2](https://github.com/tox-dev/github-workflows/pull/2)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-1-0"></a>

## 0.1.0 (2026-10-19)

<a name="release-0-1-0-added"></a>

### Added

- Commit and atomically push a release tag with a repository-scoped GitHub App token
  ([#1](https://github.com/tox-dev/github-workflows/pull/1)) by [@gaborbernat](https://github.com/gaborbernat).
- Prepare a Towncrier release with version selection, fragment linking, formatting, and `prek` checks
  ([#1](https://github.com/tox-dev/github-workflows/pull/1)) by [@gaborbernat](https://github.com/gaborbernat).
- Validate a release patch against the exact source commit before granting write access
  ([#1](https://github.com/tox-dev/github-workflows/pull/1)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-1-0-changes"></a>

### Changes

- Run release commands directly in named GitHub Actions steps ([#1](https://github.com/tox-dev/github-workflows/pull/1))
  by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-0-1-0-documentation"></a>

### Documentation

- Document each Action's inputs, outputs, side effects, and release rehearsal
  ([#1](https://github.com/tox-dev/github-workflows/pull/1)) by [@gaborbernat](https://github.com/gaborbernat).

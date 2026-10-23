# Changelog

<!-- towncrier release notes start -->

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

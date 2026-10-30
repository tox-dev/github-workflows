# Changelog

<!-- towncrier release notes start -->

<a name="release-6-2-2"></a>

## 6.2.2 (2026-10-30)

<a name="release-6-2-1"></a>

## 6.2.1 (2026-10-27)

<a name="release-6-2-1-changes"></a>

### Changes

- `validate-news` reads the pull request's current labels from the API, so re-running an older Changelog run after
  adding `skip news` passes instead of failing on the labels the original event carried. Callers grant
  `pull-requests: read` to the job ([#35](https://github.com/tox-dev/github-workflows/pull/35)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-2-0"></a>

## 6.2.0 (2026-10-27)

<a name="release-6-2-0-changes"></a>

### Changes

- `publish-github-release` credits first-time contributors on the GitHub Release, taking the list from GitHub's
  generated notes for the range since the previous tag and placing it above the package and comparison links.
  `prepare-towncrier` no longer adds a New Contributors subsection to the changelog
  ([#34](https://github.com/tox-dev/github-workflows/pull/34)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-1-0"></a>

## 6.1.0 (2026-10-27)

<a name="release-6-1-0-added"></a>

### Added

- `render-release-notes` takes one `artifact-url` per line, with matching `artifact-label` lines, so a project that
  publishes several packages lists them all on one row of the GitHub Release. Release bodies now come from
  `release-creator` 4.3.0, which marks each link with its ecosystem emoji
  ([#32](https://github.com/tox-dev/github-workflows/pull/32)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-0-3"></a>

## 6.0.3 (2026-10-27)

<a name="release-6-0-3-fixed"></a>

### Fixed

- Match release assets by the name GitHub stores, which replaces characters such as spaces with periods. A file named
  `PyVenv Manage 2-2.4.7-signed.zip` uploaded, but its draft stayed unpublished because the check expected the local
  name ([#29](https://github.com/tox-dev/github-workflows/pull/29)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-0-2"></a>

## 6.0.2 (2026-10-27)

<a name="release-6-0-2-changes"></a>

### Changes

- Admit the `[tool.nab]` per-package `uploaded-prior-to` exceptions in `cooled-prek` hook environments, so a hook
  dependency pinned past the seven-day cutoff installs the same way as the release lock. Before, prepare failed on such
  a pin ([#28](https://github.com/tox-dev/github-workflows/pull/28)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-0-1"></a>

## 6.0.1 (2026-10-26)

<a name="release-6-0-1-fixed"></a>

### Fixed

- Check out the full history in the `validate-python-release` build job again, so version tools such as hatch-vcs and
  setuptools-scm see the release tag. 6.0.0 built `0.1.dev1+g<sha>` instead of the tagged version
  ([#25](https://github.com/tox-dev/github-workflows/pull/25)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-0-0"></a>

## 6.0.0 (2026-10-26)

<a name="release-6-0-0-added"></a>

### Added

- Every Action and reusable workflow now logs the choices it makes and why, and no longer hides tool output
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Run each `validate-news` check only when the pull request touches what it validates: fragment validation when the
  fragment directory changes, the Towncrier configuration check when `towncrier.toml` or the `tool.towncrier` table
  changes, the lock check when a `pyproject.toml`, `pylock.toml`, root `pylock.*.toml`, or `nab.toml` changes, and the
  lock-removal guard when `pylock.toml` is deleted. Workflow changes no longer trigger the lock check, and every root
  `pylock.*.toml` does, whether or not it is the configured `additional-lock`. The fragment requirement for human pull
  requests still runs on every pull request ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-0-0-changes"></a>

### Changes

- Drop the `main` branch condition from the writer job of `upgrade-release-tools.yaml`. The deployment branch rule of
  the `release-auth` environment still applies ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Drop the `source` job of the github-workflows release workflow, which re-checked the tag that started it
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Give every job and step in the shared workflows and Actions a name that starts with an emoji. Jobs of the reusable
  workflows show up in callers as `<caller job> / <job name>`, so required status checks that name them must be updated.
  `publish-jetbrains-marketplace` also recognizes a prior upload step named `🚀 Publish signed ZIP`, the README's new
  name for the caller's publishing step ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Make `publish-github-release` update an existing draft's title, notes, and prerelease flag on a rerun instead of
  failing, use the first Release when several share the tag, and create the draft in `publish` mode when none exists. It
  no longer compares the title, notes, and prerelease flag of an existing Release; the read-after-write retry and the
  asset name and digest checks stay ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Stop `commit-and-tag` from requiring a clean working tree with only a staged patch; it commits whatever is staged
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Stop `publish-jetbrains-marketplace` from inspecting earlier `release` environment deployments for the tag before an
  upload; the job no longer needs Deployments read access. Stop `publish-post-release-pr` from failing when an open pull
  request's title, body, or base changed, when several pull requests match, or when a merged pull request lost its
  `skip news` label; it re-applies the label instead ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Stop `refresh-release-lock` from failing in `refresh` mode when the regenerated lock targets different environments.
  `check` mode still compares the whole lock ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Stop checking the shape of built artifacts that the release jobs produce themselves. `validate-python-release.yaml` no
  longer requires an empty `dist` directory or exactly one wheel and one sdist at the tag's version, and
  `build-python-distribution` no longer requires an empty `dist` directory. `reconcile-pypi-artifacts` no longer rejects
  an empty `dist`, an invalid project name, or local files that are hidden, symbolic links, directories, or belong to
  another release; it compares every file in `dist` with PyPI
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Stop re-checking files the release jobs produce themselves in the JetBrains Actions. `sign-jetbrains-plugin` no longer
  runs `unzip -t` on the unsigned or signed ZIP, checks for Java 17 or an existing signed ZIP, runs the signer's
  `verify`, or checks the signed ZIP's type and members. `publish-jetbrains-marketplace` no longer runs `unzip -t`,
  re-hashes the upload copy, or checks the file types of a downloaded receipt and earlier artifacts
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Stop re-checking the release tag before publishing. `publish-github-release` no longer requires the remote tag to
  resolve to `commit`, which now only sets the target of a new Release. `publish-jetbrains-marketplace` no longer
  requires the remote tag to target `commit` or fails on an earlier upload of the tag from another commit. Drop the step
  that re-checks the tag before `publish-github-release` from callers that copied the README example
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Stop validating caller input in the prepare and tag Actions. `prepare-towncrier` no longer rejects an unknown `phase`,
  a `finalize` run without `version`, a `changelog-prefix` other than empty or `v`, an explicit `version` that is not
  newer than existing tags, other hook configuration files, or an unknown changelog format; any changelog not ending in
  `.rst` is formatted with `mdformat`. `read-towncrier-config` no longer checks that the paths are normalized and inside
  the repository, that the changelog ends in `.md` or `.rst`, or that fragment categories are configured.
  `select-previous-tag` no longer requires the tag to exist locally or limits it to one namespace separator, and
  `commit-and-tag` no longer rejects an empty `token` or `app-slug` or an `annotated` value other than `true` or
  `false`; any value other than `true` creates a lightweight tag
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Stop validating caller input in the publishing Actions. `publish-github-release` no longer rejects an empty tag,
  title, or notes file, a `prerelease` other than `true` or `false`, an unknown `mode`, or asset directories with
  hidden, non-regular, or unusually named entries. `publish-jetbrains-marketplace` no longer checks the archive name and
  type, the plugin ID, the channel, the tag ref, the notes file type, the artifact IDs, or that `publish-token` is set.
  `sign-jetbrains-plugin` no longer checks the archive name and type, and `publish-post-release-pr` no longer checks the
  format of its inputs or the `allowed-paths` entries ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-6-0-0-breaking-changes"></a>

### Breaking changes

- Reduce `validate-release-patch` to applying the patch and checking its paths and file modes, and remove its `version`
  and `checks` inputs; remove them from callers. It no longer rejects a `main` branch that moved, a patch that leaves
  the changelog unchanged, or RST conflict markers, and it no longer runs `release-creator validate-fragment-deletions`,
  `release-creator notes`, the hook configuration check, or `prek`
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `app-slug` and `commit-message` inputs from `publish-post-release-pr`; remove them from callers. The Action
  no longer compares the candidate's author, committer, and message with the App bot and the expected message, re-reads
  the branch, pull request head, or base after writing, or checks the files of an already merged pull request against
  the current base ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `check-tagged-source` Action, and stop checking the tag in `validate-python-release.yaml`: the workflow no
  longer requires the tag to resolve to `GITHUB_SHA` or to sit on `main`, and checks out the tag with the default fetch
  depth. Remove `check-tagged-source` steps from callers ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `lock` job from `validate-python-release.yaml` and `prepare-towncrier-release.yaml`, and the lock check
  from `check-tagged-source`. `validate-news` still checks the lock on the pull request that changes it. Both workflows
  drop the `additional-lock`, `additional-lock-groups`, `additional-lock-selection`, `additional-matrix-python`,
  `additional-matrix-platforms`, and `additional-matrix-implementations` inputs, and `check-tagged-source` drops them
  along with `exclude-newer` and `exclude-newer-package`; remove them from callers. Without the `lock` job,
  `prepare-towncrier-release.yaml` no longer skips a dispatch from a branch other than `main`
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `validate` job from `prepare-towncrier-release.yaml`, which recalculated the version and ran
  `release-creator` and `prek` on the patch that `assemble` had just produced; `push` now depends on `assemble` alone.
  The workflow no longer installs the `release-validate` group
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `verify-lock` and `verify-groups` inputs from `install-locked-tools` and `verify-groups` from
  `export-build-constraints`, together with the `check_lock_groups.py` check behind them; remove them from callers.
  `install-locked-tools` no longer checks that the requested groups exist in the lock or requires `venv` with `groups`,
  `export-build-constraints` no longer rejects an unknown platform, a malformed or empty target list, or targets that
  select different build package versions, and `refresh-release-lock` and `upgrade-release-tools.yaml` no longer
  validate `mode`, `additional-lock`, and the secondary matrix inputs
  ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the temporary `nab-git-commit` input from `refresh-release-lock`, `validate-news`,
  `prepare-towncrier-release.yaml`, `upgrade-release-tools.yaml`, and `validate-python-release.yaml`. The Actions always
  install Nab from PyPI; remove the input from callers ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Rename the jobs of `validate-python-release.yaml` to `🏗️ Build distributions` and of `prepare-towncrier-release.yaml`
  to `🏷️ Assemble release` and `⬆️ Push release commit and tag`. Required status checks and rulesets that reference the
  old job names must use the new ones ([#23](https://github.com/tox-dev/github-workflows/pull/23)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-2"></a>

## 5.0.2 (2026-10-26)

<a name="release-5-0-2-fixed"></a>

### Fixed

- Make `refresh-release-lock` in `check` mode install the Nab version that the committed `pylock.toml` records in
  `[tool.nab] nab-version`, and fail if the lock records none. A Nab release newer than that version rewrites the field,
  so every committed lock failed the check until the weekly refresh. `refresh` mode still installs the newest Nab under
  the cutoff, and `nab-git-commit` still installs from that commit in both modes
  ([#22](https://github.com/tox-dev/github-workflows/pull/22)) by [@gaborbernat](https://github.com/gaborbernat).
- Make `validate-news` reject a pull request that removes `pylock.toml` when the project has a `nab.toml`, as it already
  did for a `[tool.nab]` table in `pyproject.toml` ([#22](https://github.com/tox-dev/github-workflows/pull/22)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-2-documentation"></a>

### Documentation

- Say that `check-tagged-source` reads the tag of a non-tag run from the `tag` input of the `workflow_dispatch` event,
  `github.event.inputs.tag`, rather than from an input of the Action
  ([#22](https://github.com/tox-dev/github-workflows/pull/22)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-2-security"></a>

### Security

- Make the Actions install their own tools, such as Nab, `packaging`, `certifi`, and `pypi-attestations`, from PyPI even
  when the caller's repository or environment configures another index. The installer now ignores `uv.toml`, `[tool.uv]`
  in `pyproject.toml`, and the `UV_INDEX`, `UV_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_EXTRA_INDEX_URL`, `UV_FIND_LINKS`,
  `UV_CONFIG_FILE`, `UV_INSECURE_HOST`, `UV_SYSTEM_CERTS`, `SSL_CERT_FILE`, and `SSL_CERT_DIR` variables, as
  `cooled-prek` already does ([#22](https://github.com/tox-dev/github-workflows/pull/22)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-1"></a>

## 5.0.1 (2026-10-25)

<a name="release-5-0-1-fixed"></a>

### Fixed

- Install the whole Nab workspace from the `nab-git-commit` commit: `nab` and its `nab-index`, `nab-markersets`,
  `nab-project`, `nab-provider`, and `nab-resolver` sub-packages, which the root pins to an unreleased version
  ([#21](https://github.com/tox-dev/github-workflows/pull/21)) by [@gaborbernat](https://github.com/gaborbernat).
- Let `check-tagged-source` accept a `workflow_dispatch` or other non-tag run, such as one from `main` with a `tag`
  input, when the checkout is the commit that tag names and that commit is on `main`. Tag runs still require the tag,
  `GITHUB_SHA`, and the checkout to match ([#21](https://github.com/tox-dev/github-workflows/pull/21)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-0"></a>

## 5.0.0 (2026-10-25)

<a name="release-5-0-0-added"></a>

### Added

- Add `exclude-newer` and `exclude-newer-package` inputs to every Action and reusable workflow that installs its own
  tools. `exclude-newer` defaults to `7 days`; `exclude-newer-package` takes newline-separated `name=date` overrides for
  an emergency ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Add a temporary `nab-git-commit` input to `refresh-release-lock` and to the Actions and reusable workflows that call
  it. A full commit SHA installs Nab from `notatallshaw/nab` at that commit, with no cooldown, until a Nab release
  carries the fix ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Add the `cooled-prek` Action, which runs prek with the root configuration and hook environments built under the
  seven-day cutoff. The prepare workflow now installs its hooks through it
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Run `release-creator contributors` after the Towncrier build in `prepare-towncrier`, so the changelog section gets a
  "New Contributors" subsection. It needs release-creator 3.1.0
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-0-changes"></a>

### Changes

- Drop the hook pin mention from the default `pull-request-body` of `upgrade-release-tools.yaml`, which now reads
  "Refresh the project lock." ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Let `validate-news` accept a pull request that removes `pylock.toml` when the project has no `[tool.nab]` table and no
  `additional-lock` is configured, so nothing would produce a lock
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Make `check-tagged-source` require that the tag resolves to `GITHUB_SHA`, as the Python release build job does
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Make the github-workflows release job check that the tag still resolves to the tagged commit before it creates the
  GitHub Release, and check the tag inline instead of through `check-tagged-source`
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Reject a primary lock refresh that changes the lock's target environments, as the secondary lock refresh already does
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-0-breaking-changes"></a>

### Breaking changes

- Accept only `pylock.toml` and the configured secondary lock in the `upgrade-release-tools.yaml` patch.
  `pyproject.toml` and `uv.lock` changes are rejected ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Generate the primary `pylock.toml` with `nab lock --all-groups --all-extras --no-cache`, adding `--upgrade` in
  `refresh` mode, and compare a regenerated lock in `check` mode. The `release-creator locks` path and the uv resolver
  steps are gone, so relock a `release-creator locks` lock with Nab before re-pinning. Nab runs without `SSL_CERT_FILE`
  and `SSL_CERT_DIR` ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove GitHub's generated notes from the release path: the `generated-notes` input of `render-release-notes` is gone,
  and the github-workflows release no longer has a Contents-write job that fetches contributor metadata. The read-only
  notes job now runs in parallel with the tag check and renders the notes from the full history alone
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the Actions' shared `pylock.toml`, its weekly refresh, and the `lock-source` input of `install-locked-tools`.
  The Actions now install the newest release of each of their own tools, above a minimum version, that is older than a
  seven-day cutoff, and `install-locked-tools` installs only from the caller's `pylock.toml`. Build constraints come
  from the caller lock's `build` group alone, without the shared Cython and setuptools pins
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `--shared-policy` option and two-lock merging from `tools/build_constraints.py`; it now exports the build
  constraints of one lock ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `check-hook-update-cooldown` and `recheck-hook-update-cooldown` Actions and the
  `recheck-hook-cooldown.yaml` workflow. Pull requests that change `.pre-commit-config.yaml` are no longer checked for
  hook revision age or dependency closure cooling; drop the `hook-cooldown` job and its scheduled rerun from callers
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `install-local-release-creator` Action and the `local-tool-source` input of `install-locked-tools` and
  `prepare-towncrier-release.yaml`. A lock may no longer list release-creator as a local directory package
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `keep-uv-lock` input of `refresh-release-lock`, `validate-news`, `check-tagged-source`,
  `prepare-towncrier-release.yaml`, `upgrade-release-tools.yaml`, and `validate-python-release.yaml`. A committed
  `uv.lock` is no longer refreshed or checked ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `refresh-mise-pin` Action. Callers that pinned a mise binary with it keep `jdx/mise-action`'s default
  release age instead ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `verify-frozen-hooks` Action with its frozen revision, tagged hook provenance, and hook dependency closure
  checks. The shared prepare workflow and `check-tagged-source` no longer run it; drop it from custom tag jobs.
  `prepare-towncrier` and `validate-release-patch` now reject a `prek.toml` or a nested hook configuration before they
  run `prek` ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the hook refresh from `upgrade-release-tools.yaml`. The weekly updater no longer runs
  `prek update --freeze --cooldown-days 7` or `release-creator hooks`, and its writer accepts only the lock patch; let
  Dependabot's `pre-commit` ecosystem update hook revisions instead
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the reviewed cutoff table, the recent cutoff check, the cutoff expiry, and the `verify-cutoff-patch` Action.
  Callers own their per-package `uploaded-prior-to` exceptions in `[tool.nab]`, and gw neither checks nor expires them
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Restructure `validate-python-release.yaml`. A keyless `lock` job checks the locks in parallel with `build`, which now
  checks the tag inline, including that it resolves to `GITHUB_SHA`, and exports its own build constraints; the
  `source-check` and `constraints` jobs and the `build-constraints` artifact are gone. The `validate` job, which ran
  `twine check` and `check-wheel-contents`, is removed; packages check their distributions with their own
  `tox -e pkg_meta`. The workflow no longer needs `actions: read` or `pull-requests: read`
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).
- Stop checking caller locks against PyPI metadata and upload times in `install-locked-tools`. `check_lock_groups.py`
  now only checks that the selected groups exist, and Nab's regenerate-and-compare check in `refresh-release-lock`
  guards the lock on pull requests, on tags, and in a new keyless `lock` job of `prepare-towncrier-release.yaml` that
  runs before assembly ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Stop running `prek` on the tagged source. `check-tagged-source` now checks only the tag and the locks and no longer
  installs the caller's `release-check` group; the release patch is still checked with `prek` before it is pushed
  ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-5-0-0-packaging"></a>

### Packaging

- Lock github-workflows' own `release-prepare` and `release-validate` tools, with the `build` backends PyYAML needs, in
  a small `pylock.toml` made by Nab under the seven-day cutoff, so its release preparation installs them hash-checked
  from its own lock like every caller ([#20](https://github.com/tox-dev/github-workflows/pull/20)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-4-0-1"></a>

## 4.0.1 (2026-10-25)

<a name="release-4-0-1-changes"></a>

### Changes

- Lock release-creator 2.0.0 for the shared release tools during its seven-day review window. Caller locks must be
  regenerated with `release-creator locks` 2.0.0, because its `--check` compares the recorded uv version and no longer
  writes the `[tool.nab]` stamp. The `calver` bump is gone from release-creator, so it is no longer documented here
  ([#19](https://github.com/tox-dev/github-workflows/pull/19)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-4-0-0"></a>

## 4.0.0 (2026-10-25)

<a name="release-4-0-0-added"></a>

### Added

- Add `check-tagged-source`, which runs the tag, lock, frozen hook, and cooled `prek` checks of a tagged checkout. The
  Python release workflow uses it, and custom tag release jobs can call it before publishing
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-4-0-0-fixed"></a>

### Fixed

- Check the release lock in pull requests that change a workflow, since re-pinning github-workflows can change the
  pinned resolver and the rendered lock ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Keep CRLF line endings when refreshing a mise pin, and report a release asset without a digest as an error instead of
  a traceback ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Let a JetBrains Marketplace retry follow an attempt that reconciled an earlier upload. That attempt now keeps a copy
  of the receipt it verified, and the check reads the artifacts of the run named in the receipt. Fork pull request runs
  on a branch named like the tag no longer block the upload ([#18](https://github.com/tox-dev/github-workflows/pull/18))
  by [@gaborbernat](https://github.com/gaborbernat).
- Let a human pull request add or change managed hook dependency pins when each new pin is an exact, cooled PyPI release
  and the complete closure check passes. Adding a Python hook with dependencies no longer needs the release App
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Let the weekly github-workflows update publish a new uv resolver. The writer now accepts a change of the exact
  `release-resolver` uv pin when the refreshed lock selects that version
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Report a lock whose `tool.release-creator` or `tool.nab` value is not a table as an error instead of a traceback
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Rerun a waiting hook cooldown check once any head of the pull request branch was observed seven days ago. The check
  accepts revisions seen on earlier heads, so a later push no longer delays the rerun
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Select the new uv resolver only from the `release-resolver` group, so a different uv in the test group no longer stops
  the upgrade, and widen the pin from its current version ([#18](https://github.com/tox-dev/github-workflows/pull/18))
  by [@gaborbernat](https://github.com/gaborbernat).

<a name="release-4-0-0-breaking-changes"></a>

### Breaking changes

- Remove the Nab primary lock path and the `lock-groups` input of `refresh-release-lock` and `upgrade-release-tools`.
  `pylock.toml` must now come from `release-creator locks`; relock a Nab primary lock before re-pinning. Nab remains for
  secondary `additional-lock` matrices ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `render-release-notes` `output` input. Every caller passed `${{ runner.temp }}/release-notes.md`, which is
  now where the Action writes the body ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Remove the `upgrade-resolver` input of `refresh-release-lock` and `upgrade-release-tools`. The shared uv resolver pin
  is upgraded only in github-workflows, which the Action now detects from the repository name
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Remove the `validate-release-patch` `patch` input. The Action reads the patch from
  `${{ runner.temp }}/release-patch/release.patch`, where every caller downloaded it
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Rename the `verify-nab-cutoff-patch` Action to `verify-cutoff-patch`, since it checks release-creator cutoffs and the
  shared resolver pin as well as Nab cutoffs ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-4-0-0-security"></a>

### Security

- Check that the release tag points at the checkout and is on `main` before the tagged source check runs hooks
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Check the downloaded mise executable against the seven-day-old release digest before mise-action runs it, and run its
  version listing outside the caller's checkout ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Prove the age of tagged hook revisions before `release-creator hooks --check` builds hook repositories, so build
  backends from an unproven revision do not run first ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).
- Reject `additional_dependencies` on hooks whose configured `language` is not Python. Only Python hook dependencies get
  exact, cooled pins, so a node or other hook would install them unpinned
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Reject dependency group names that are not normalized, in the lock and in the selected groups. A name such as
  `project_runtime` matched no lock marker, so its packages skipped the cooling and PyPI checks
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Run every prek command with `--config .pre-commit-config.yaml`, and reject a `prek.toml`, a `.pre-commit-config.yml`,
  or a nested `.pre-commit-config.yaml` in the hook cooldown and frozen hook checks. prek used to run those files
  without any revision, cooldown, or dependency check ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by
  [@gaborbernat](https://github.com/gaborbernat).

<a name="release-4-0-0-performance"></a>

### Performance

- Install the Nab lock tools in `refresh-release-lock` only for a refresh or a secondary lock. Lock checks in pull
  requests, release preparation, and tagged releases skip that install
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).
- Skip the cooling check of github-workflows' own lock when installing shared tools, and the second PyPI check of a
  secondary lock's build selection when `export-build-constraints` already verified that lock
  ([#18](https://github.com/tox-dev/github-workflows/pull/18)) by [@gaborbernat](https://github.com/gaborbernat).

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

# Troubleshooting

Errors the shared workflows and Actions report, keyed by the text in the job log. Search this page for a phrase from the
`Error:` annotation.

## Any writer job

**A dispatched check workflow prepared a real release.** The dry-run input was derived from `github.event_name`. A
called workflow sees its caller's event, so derive nothing: pass `dry-run: true` from the gate workflow.

## Pull request checks

**`add a changelog fragment or apply the skip news label`**

A human pull request has no valid fragment. Add one to the configured fragment directory, or add the `skip news` label;
the `labeled` event reruns the news check.

**The news check still fails after adding `skip news`.** Rerunning an old run is fine, since the Action reads the labels
from the API. Check that the news workflow triggers on `labeled` and `unlabeled`, and that no `concurrency` group
cancels its runs.

**`allow-skipped names a job that is not in needs`**

An `allow-skipped` entry of `required-checks` is not a job ID in the gate's `needs`. Fix the typo; the message names it.

## Locks and cutoffs

**`... uploaded-prior-to exception expired on <date>; remove it or extend its expiry`**

**`... uploaded-prior-to exception needs a '# expires YYYY-MM-DD' comment directly above it`**

A `[tool.nab]` cutoff exception has passed its date or has none. Delete the exception once the package is a week old, or
add or extend the `# expires` comment. See [Expire cutoff exceptions](locked-tools.md#expire-cutoff-exceptions).
Scheduled `upgrade-release-tools` runs fail on this even when nothing else changed.

**`check mode needs the Nab version in pylock.toml [tool.nab] nab-version`**

The committed lock was not written by Nab, or by a Nab old enough to omit the field. Regenerate it with
`nab lock --all-groups --all-extras`.

**`regenerated locks differ from the checkout`** or **`regenerated Nab lock differs from the committed lock`**

The committed `pylock.toml` no longer matches the project: a dependency changed in `pyproject.toml` without a relock.
Run `nab lock --all-groups --all-extras` with the Nab version the lock records, and commit the result.

**`committed Nab lock has no valid creation time or was created in the future`**

The lock's `[tool.nab] created-at` is missing, has no time zone, or lies ahead of the runner's clock. Regenerate the
lock.

**A hook fails to install during a release or maintenance run, with uv finding no matching version.** A package the hook
resolves to a release younger than seven days is not exactly pinned, and
[`cooled-prek`](locked-tools.md#run-prek-under-the-cutoff-cooled-prek) builds hook environments under that cutoff. An
exact pin (`name==version` in `additional_dependencies` or the hook repository's install requirements) admits its
release while that release is younger than the cutoff, so this is a range, a transitive dependency, or a release newer
than the pin. Wait for the release to age, or add a dated `[tool.nab.packages.<name>]` exception in `pyproject.toml`;
hook environments ignore exceptions in `nab.toml`.

## Release preparation

**`unexpected release path: <path>`**

The release patch touches a path the writer does not accept. With Towncrier configuration, only the changelog and
deletions under the fragment directory may change; anything else, such as a hook rewriting another file, fails. With
`prepare-release-creator`, add the path to `release-paths`.

**`unexpected release file mode in <path>`** or **`unexpected previous release file mode in <path>`**

The patch makes a file executable, adds a symlink, or changes a non-regular file. Release patches may only add, modify,
or delete regular non-executable files.

**`tag-format ... needs a package input`**, **`tag-format ... names no package, but package is ...`**, or
**`unsupported tag-format`**

`prepare-release-creator` accepts `{version}`, `v{version}`, `{package}/{version}`, and `{package}/v{version}`. Set
`package` exactly when the format contains `{package}`.

**The atomic push of `main` and the tag is rejected.** `main` moved after assembly started, the tag is invalid, or a
branch or tag ruleset rejected the App. Grant the App bypass on both rulesets, or dispatch the prepare workflow again. A
rejected push updates neither ref.

## Publishing

**`GitHub Release <tag> is not published with the expected assets and notes`**

A publish call failed, and reading the Release back did not show the expected state. Rerun the failed job: the Action
resumes the draft. A published Release with a different asset set needs manual inspection, because published releases
are not rewritten.

**`release asset attestation could not be verified`**

GitHub has no release attestation for a local asset. Check that immutable releases are enabled for the repository.

**PyPI reconciliation fails on a digest or an unexpected file.** A different build reached PyPI, or a file was yanked.
Use "Re-run failed jobs" rather than a full rerun, so the upload repeats with the same built files.

## Maintenance pull requests

**`None of the provided artifact IDs were found`**

Two maintenance workflows in one run uploaded patch artifacts under the same name. Give each upload a unique name.

**`maintenance patch changes no paths`** or **`unexpected maintenance path: <path>`**

The uploaded `maintenance.patch` is empty, or touches a path outside `allowed-paths`. For `update-python-dependencies`,
list files a hook regenerates in `allowed-paths`.

**`repository hooks failed without changing a file`**

A prek hook failed during `update-python-dependencies` and rewrote nothing, so the failure is real. Reproduce it with
`prek run --all-files` on the dependency branch.

**`kind must be app or library`**, **`cooldown must be N days`**, **`files entry ... is not a plain relative path`**

`update-python-dependencies` validates its inputs before it installs anything. Fix the input the message names.

## Other workflows

**`README.md has no rev: line to update to v<version>`**

The pre-commit mirror's README needs a `rev:` line, which the mirror updates to each new tag.

**`<tag> is published with a different mirror tree`**

The regenerated mirror for an existing tag differs from the published one. Published tags never move; bump the package
version to publish new content.

**`did not serve the freshly built PDF within 20 minutes; is GitHub Pages enabled for gh-pages?`**

Enable GitHub Pages for the `gh-pages` branch, or check the Pages build log.

**`IDE did not answer on port 8082 within <n> seconds`**

The JetBrains UI-test IDE did not start its robot server in time. Raise `ui-test-timeout`, or check `runIdeForUiTests`.

**`Marketplace upload may already be accepted`**

An earlier run started an upload without leaving a receipt. Follow the manual reconciliation steps in
[Publish](jetbrains.md#publish-publish-jetbrains-marketplace).

**Scorecard results do not update.** The Scorecard API rejected the results; the step logs a warning. The caller
workflow must keep [Scorecard's workflow restrictions](security-scanning.md#openssf-scorecard-scorecardyaml).

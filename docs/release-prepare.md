# Prepare and tag a release

Two reusable workflows turn the pending news fragments into a release commit and a tag. Pick one:

- [`prepare-towncrier-release.yaml`](#prepare-towncrier-releaseyaml): one package, changelog built by Towncrier from
  committed configuration. Most repositories use this.
- [`prepare-release-creator.yaml`](#prepare-release-creatoryaml): a workspace with several packages, a Rust crate, or a
  changelog your own script assembles.

Both run the same two jobs. `assemble` holds only read tokens: it selects the version, links each fragment to its
squash-merged pull request and authors, builds and formats the changelog, and uploads the result as a binary patch.
`push` runs in the `release-auth` environment: it downloads that patch by artifact ID, checks its paths and file modes,
mints an App token for this repository with Contents write, and pushes the release commit (`release <tag>`) and the tag
together. The tag starts the caller's [publish workflow](release-publish.md). No job output returns to the caller.

Behaviour shared by both workflows:

- Real releases of one repository are serialized and never cancelled. A [dry run](#dry-run-on-pull-requests) uses its
  own concurrency group per ref, so it never queues behind a real release or holds one up.
- `assemble` checks out the full history at `github.sha`, installs the caller's locked `release-prepare` group
  (release-creator, Towncrier, and prek). It does not install the repository's hooks up front: when it formats the
  changelog, prek installs only that formatter's hook, under the seven-day cutoff, so a hook the release never runs
  cannot fail it. It needs `contents: read` and `pull-requests: read` to resolve pull request authors.
- `push` checks out with `fetch-depth: 1`. Every job uses `persist-credentials: false`.
- One dispatch prepares one tag; run separate dispatches for separate packages. Put repository-specific checks in a
  preceding caller job and make the prepare job depend on it.
- The caller passes `RELEASE_APP_PRIVATE_KEY` by name; the client ID comes from the `release-auth` environment's
  `RELEASE_APP_CLIENT_ID` variable. A dry run needs neither.

See [Release flow](release.md#one-time-repository-setup) for the App, environment, and ruleset setup.

## `prepare-towncrier-release.yaml`

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

| Input                            | Default  | Purpose                                                                                          |
| -------------------------------- | -------- | ------------------------------------------------------------------------------------------------ |
| `bump`                           | `auto`   | `auto`, `major`, `minor`, or `patch`, as for [`prepare-towncrier`](#prepare-towncrier).          |
| `tag-prefix`                     | empty    | `v` when tags are spelled `v1.2.3`.                                                              |
| `changelog-prefix`               | empty    | `v` when changelog headings are spelled `v1.2.3`.                                                |
| `annotated`                      | `false`  | Create an annotated tag. Match the repository's existing tags.                                   |
| `release-auth-deployment`        | `true`   | Set `false` if the current App-key job uses `release-auth` without creating a GitHub Deployment. |
| `exclude-newer`                  | `7 days` | Cutoff for the tools the Actions install from PyPI, see [cutoffs](locked-tools.md#cutoffs).      |
| `exclude-newer-package`          | empty    | Newline-separated `name=date` overrides of that cutoff.                                          |
| `dry-run`                        | `false`  | Run `assemble` only and skip `push`; see [below](#dry-run-on-pull-requests).                     |
| secret `RELEASE_APP_PRIVATE_KEY` |          | Required for a real release, unused in a dry run.                                                |

The committed Towncrier configuration names the changelog and the fragment directory; the caller sets only the tag
style. The `push` job applies the patch with [`validate-release-patch`](#validate-release-patch), which accepts only the
changelog and fragment deletions.

## Dry run on pull requests

A release assembles under rules that a pull request's own checks do not cover: the changelog formatter's hook installs
with packages from the last seven days held back, fragments link to their pull requests, and the changelog builds and
formats. A pull request that breaks any of these merges green and fails the next release. `dry-run: true` runs
`assemble` alone and skips `push`, so the pull request fails instead.

Make the caller's prepare workflow callable, as in [Release flow](release.md#caller-files), and call it from the
workflow that holds the required gate, so the dry run uses the same inputs as the release:

```yaml
# .github/workflows/check.yaml
jobs:
  release:
    uses: ./.github/workflows/prepare-release.yaml # zizmor: ignore[self-repository] actionlint rejects the $/ form
    permissions:
      contents: read
      pull-requests: read
    with:
      dry-run: true
  gate:
    needs: [release, test]
```

The caller can reference its own workflow two ways. `$/.github/workflows/prepare-release.yaml` is what this repository
and some callers use, but actionlint (v1.7.12 and its current main branch) rejects the `$/` form.
`./.github/workflows/...` passes actionlint, and zizmor's `self-repository` audit flags it, hence the inline ignore in
the example. A repository that runs actionlint uses the `./` form with that comment, as tox-dev/tox-gh does; one that
runs only zizmor may use `$/`.

Pitfall: pass `dry-run` explicitly rather than deriving it from `github.event_name`. A called workflow sees its caller's
event, so a manually dispatched check workflow would otherwise prepare a real release. `prepare-release-creator.yaml`
takes the same `dry-run` input.

## `prepare-release-creator.yaml`

`assemble` selects the tag from existing tags and pending fragments, links fragments to their pull requests, optionally
runs `cargo set-version`, runs the caller's `assemble-command`, adds a New Contributors list with
`release-creator contributors`, formats the changelog with the `mdformat` prek hook, and uploads the patch. `push`
applies it with [`validate-release-patch`](#validate-release-patch) using `release-paths` as `allowed-paths`, mints the
App token, and runs [`commit-and-tag`](#commit-and-tag).

A multi-package workspace, such as toml-fmt:

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

| Input                                                                                       | Default        | Purpose                                                                                                                                                                                                                 |
| ------------------------------------------------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `assemble-command` **(required)**                                                           |                | Shell command, run under `bash -c`, that writes the changelog section from the fragments. It runs with `PACKAGE`, `VERSION` (the bare number), and `TAG` set, and may run the package's own build steps first.          |
| `release-paths` **(required)**                                                              |                | Newline-separated glob patterns, the only paths the patch may change. `{package}` expands to `package`. Each match may be added, modified, or deleted as a regular file; other modes fail.                              |
| `bump`                                                                                      | `auto`         | `auto`, `major`, `minor`, or `patch`, passed to `release-creator tags --next`.                                                                                                                                          |
| `package`                                                                                   | empty          | Scopes tags to `package/` and fragments to `changelog.d/<package>`. Empty for a single-package repository.                                                                                                              |
| `tag-format`                                                                                | `{version}`    | `{version}`, `v{version}`, `{package}/{version}`, or `{package}/v{version}`. A `{package}` format needs `package`; a format without it rejects `package`. Fragments live in `changelog.d` (or `changelog.d/<package>`). |
| `changelog`                                                                                 | `CHANGELOG.md` | Markdown changelog. A new, untracked file is added to the patch.                                                                                                                                                        |
| `cargo-set-version`                                                                         | `false`        | Run `cargo set-version` with the number before assembly. Rust and cargo-edit install only when this is set.                                                                                                             |
| `cargo-set-version-args`                                                                    | empty          | Arguments before the number, such as `-p {package}`.                                                                                                                                                                    |
| `annotated`, `release-auth-deployment`, `exclude-newer`, `exclude-newer-package`, `dry-run` |                | As for [`prepare-towncrier-release`](#prepare-towncrier-releaseyaml).                                                                                                                                                   |
| secret `RELEASE_APP_PRIVATE_KEY`                                                            |                | Required for a real release, unused in a dry run.                                                                                                                                                                       |

What stays in the caller:

- The changelog section. `assemble-command` writes it, because release-creator does not build a `## <package>` section
  in a shared changelog. Simplint's `assemble_release.py` and toml-fmt's package sections both stay in the caller.
- Any Cargo or uv version change beyond `cargo-set-version`, such as `uv version --package` for a second Python package.
- The tag-triggered publisher.

## Building-block Actions

The workflows above are built from these Actions. Call them directly only when a release needs a step the workflows do
not offer; keep the same split between a keyless job and an App-token job.

### `read-towncrier-config`

Reads the Towncrier configuration from the checkout's committed `HEAD`, so an untrusted release patch cannot change the
allowed paths. A committed `towncrier.toml` wins; otherwise `[tool.towncrier]` in `pyproject.toml`. It changes nothing
in the checkout or on GitHub.

```yaml
  - id: towncrier
    uses: tox-dev/github-workflows/read-towncrier-config@SHA
  - env:
      CHANGELOG: ${{ steps.towncrier.outputs.changelog }}
    run: printf '%s\n' "$CHANGELOG"
```

Outputs: `changelog` (the `filename`), `fragments` (the `directory`), and `format`: `rst` for a `.rst` changelog,
otherwise `markdown`.

### `prepare-towncrier`

Chooses the next version, links fragments to their squash pull requests, runs `towncrier build`, formats the changelog
through prek, and writes a binary patch of the working tree against `HEAD` to `$RUNNER_TEMP/release.patch`. It does not
commit or push. Version selection, fragment linking, the build, and formatting must all succeed. It needs
release-creator, Towncrier, and prek on `PATH`, and uses `github.token` to look up pull requests.

```yaml
  - id: prepare
    uses: tox-dev/github-workflows/prepare-towncrier@SHA
    with:
      bump: ${{ inputs.bump }}
```

| Input              | Default | Purpose                                                                                                                                                                                                |
| ------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `bump`             | `auto`  | `auto`, `major`, `minor`, or `patch`, passed to `release-creator tags --next`. `auto` decides from the pending fragments. The caller's dispatch form decides which choices to expose.                  |
| `tag-prefix`       | empty   | `v` when tags are spelled `v1.2.3`. Version comparison still includes unprefixed numeric tags in history. It does not set the changelog heading prefix.                                                |
| `changelog-prefix` | empty   | Towncrier writes `1.2.3` even when the tag is `v1.2.3`; set `v` for headings spelled `v1.2.3`.                                                                                                         |
| `version`          | empty   | Explicit version for a caller with its own selector; takes precedence over `bump`.                                                                                                                     |
| `phase`            | `all`   | `all` runs everything. The reusable workflow runs `build` (select the version, link authors, build the changelog), then `finalize` (format, write the patch) with the `version` that `build` selected. |

Output: `version`, the selected tag string; expose it as a job output so the writer job can pass it to `commit-and-tag`.
Working-tree effect: Towncrier rewrites the changelog and consumes the fragments; the patch records those changes.

`docstrfmt` formats a `.rst` changelog and `mdformat` any other; the formatter must be a configured prek hook. A first
formatter run may rewrite the file; the second must pass.

### `validate-release-patch`

Applies `$RUNNER_TEMP/release-patch/release.patch` in the writer's checkout, checks its changed paths and file modes,
and leaves it staged for `commit-and-tag`. Download the patch artifact to `${{ runner.temp }}/release-patch` first. It
needs no release tools.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@SHA
```

By default it reads the changelog and fragment directory from committed Towncrier configuration and accepts only an
added or modified changelog and deletions under the fragment directory. Set `allowed-paths` to newline-separated glob
patterns to replace that rule: the patch may then add, modify, or delete only matching paths, and the Towncrier
configuration is not read; [`prepare-release-creator`](#prepare-release-creatoryaml) sets it from `release-paths`.
Either way each change must be a regular non-executable file or a deletion; an unexpected path or mode fails the job. No
named output.

### `commit-and-tag`

Commits the staged release patch as the GitHub App's bot, creates the tag, and pushes `HEAD` to `main` and the tag in
one atomic push: a rejected push updates neither ref. Mint the token after validation with
`actions/create-github-app-token`, narrowed to this repository and Contents write. Put `commit-and-tag` last in the
writer job, because its Git credential helper stays configured for later steps.

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

| Input                     | Default | Purpose                                                                        |
| ------------------------- | ------- | ------------------------------------------------------------------------------ |
| `version` **(required)**  |         | Tag to create, such as `1.2.3`.                                                |
| `token` **(required)**    |         | Short-lived installation token from the repository-only App; never the key.    |
| `app-slug` **(required)** |         | `app-slug` output of the token Action, used to resolve the bot's Git identity. |
| `message` **(required)**  |         | Commit message, and the tag message when `annotated` is `true`.                |
| `annotated`               | `false` | `true` creates an annotated tag; match the repository's release history.       |

Remote effect: one new commit on `main` and one tag at it. The target branch is always `main`. The App needs branch and
tag ruleset bypass; a stale branch, an invalid tag, a ruleset rejection, or nothing staged fails the job.

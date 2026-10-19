# GitHub workflows

Three composite Actions prepare a Towncrier release, verify its patch, and push an App-authored commit and tag. They run
as steps in the caller's workflow. Each repository keeps its dispatch form, build, publisher, GitHub environment, and
required check names.

## Start with a caller

The [release preparation workflow](.github/workflows/prepare-release.yaml) in this repository is a complete caller. Its
`assemble` job creates a patch without a write credential. Its `push` job applies and checks that patch before minting a
repository-scoped App token. Copy those jobs, then set the changelog path, fragment directory, commit message, and tag
style. Replace this repository's relative `uses: $/…` references with a full release commit SHA. In the examples below,
`SHA` means that release commit and `TOKEN_ACTION_SHA` means the pinned token Action commit in the linked workflow.

Both jobs need a full checkout (`fetch-depth: 0`, `persist-credentials: false`) and `release-creator`, Towncrier, and
`prek` installed from the caller's checked-in `pylock.toml`. Preparation needs `contents: read` and
`pull-requests: read` to resolve PR authors. The `push` job uses the `release-auth` environment with
`RELEASE_APP_PRIVATE_KEY` and the repository variable `RELEASE_APP_CLIENT_ID`. Install the App on that repository only,
with Contents write and Metadata read. Give it the necessary branch and tag ruleset bypass.

```text
main + fragments
       │
       ▼
prepare-towncrier ── version + patch ──► upload artifact
                                             │
                                       download artifact
                                             │
                                             ▼
                                   validate-release-patch
                                             │
                                       mint App token
                                             │
                                             ▼
                                      commit-and-tag ──► main + tag
```

The tag starts the caller's publisher. Keep PyPI trusted publishing in that top-level workflow, in a separate job with
`id-token: write`:
[PyPI does not support trusted publishing inside reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github).
Run `prek` on the tagged source before publication. The [self-release workflow](.github/workflows/release.yaml) shows
the GitHub Release path; callers keep their ecosystem builds and uploads.

## Prepare Towncrier release

`prepare-towncrier` reads a clean checkout, chooses the next version, links named fragments to their squash PRs, runs
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
- `version`: Explicit version for a caller with its own version selector. It takes precedence over `bump`; the Action
  still checks that it is newer than existing tags.
- `changelog` **(required)**: Tracked file Towncrier writes, such as `CHANGELOG.md` or `docs/changelog.rst`. This must
  match `tool.towncrier.filename` in the caller's `pyproject.toml`.
- `fragments`: Fragment directory relative to the checkout root; default `changelog.d`. Set this to the caller's
  `tool.towncrier.directory`. Version selection and PR linking both read this directory.
- `format`: `none` (default) or `markdown`. `markdown` runs the caller's `mdformat` prek hook on the assembled
  changelog. Use `none` for RST or when that hook does not exist. The full `prek` suite runs in either case.
- `link-fragments`: `true` (default) resolves named fragments and authors through GitHub; `false` skips that step for a
  caller whose fragments already contain release links and credits.
- `patch` **(required)**: Writable path to the Git patch, usually under `runner.temp`. Upload this exact file as an
  artifact for the validation job.

**Output:** `version` is the selected tag string. Use `steps.prepare.outputs.version` as a job output and pass it to
both later Actions. **Working-tree effect:** Towncrier changes the changelog and consumes fragments; the patch records
those changes. The checkout must be clean before this Action starts.

## Validate release patch

`validate-release-patch` starts from a fresh checkout of the original branch commit. It rejects a branch that moved,
applies the uploaded patch, checks its changed paths and version heading, and runs `prek`. It leaves the patch staged
for the commit Action. It does not need a write token.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@SHA
    with:
      version: ${{ needs.assemble.outputs.version }}
      patch: ${{ runner.temp }}/release-patch/release.patch
      changelog: docs/changelog.md
      fragments: docs/changelog.d
```

- `version` **(required)**: Exact tag chosen by preparation. The changelog must contain a heading for it.
- `patch` **(required)**: Local path of the downloaded patch artifact, not an artifact name or URL.
- `changelog` **(required)**: Same tracked path passed to preparation. Only this file and files below `fragments` may
  change in the patch.
- `fragments` **(required)**: Same directory passed to preparation. Towncrier may consume or rename its files.
- `heading-prefix`: Text before the version in its heading; default `## `. For `Version 1.2.3 (date)`, use `Version `.
  The Action expects the version to be followed by ` (`.
- `branch`: Protected release branch; default `main`.
- `remote`: Git remote fetched for the freshness check; default `origin`.
- `expected-sha`: Commit that preparation checked out. By default the Action uses `GITHUB_SHA`; set this when
  preparation used another commit.

**Output:** No named output. **Working-tree effect:** Applies and stages the patch. A failed `prek` run, unexpected
path, or modification by `prek` fails the job before a write credential is minted.

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

## Check a caller before switching

The [Actions test suite](tests) executes each inline `run:` block in temporary Git repositories. The
[`release-dry-run` job](.github/workflows/check.yaml) invokes the composite Actions on a GitHub runner against a local
bare remote. It cannot prove that another repository's Towncrier template, release hooks, package build, or publisher
works. Run that caller's prepare and validation path at its PR head without pushing a GitHub ref or publishing an
artifact. Inspect the version, patch, changelog, notes, and built package before changing its live release workflow.

This repository releases its own Actions with the same prepare and tag path. See [Contributing](CONTRIBUTING.md) for
local checks and news fragments, and [Changelog](CHANGELOG.md) for released changes.

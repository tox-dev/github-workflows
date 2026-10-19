# Use the release Actions

These Actions run as steps in a repository's own workflow. They share release preparation and Git writes. The caller
still owns its dispatch form, build, ecosystem upload, GitHub Release, environments, and required check names. The
checked-in [prepare workflow](../.github/workflows/prepare-release.yaml) is a working caller; this repository uses the
Actions from its own checkout until its first release.

Install `release-creator`, Towncrier, and `prek` from the caller's checked-in `pylock.toml` before preparation or
validation. Check out full Git history and tags with `fetch-depth: 0` and set `persist-credentials: false`. Run the
prepare and validate steps before minting a write token.

## Prepare Towncrier release

`tox-dev/github-workflows/prepare-towncrier@<full-commit-sha>` takes a clean checkout and writes a patch. Towncrier
reads its fragment directory and changelog path from the caller's `pyproject.toml`.

- **Required inputs:** `changelog` is the changelog file; `patch` is a writable path for the generated Git patch.
- **Optional inputs:** `bump` is `auto` by default and also accepts `major`, `minor`, or `patch`. `version` supplies an
  explicit version for a custom selector and takes precedence over `bump`. `format` is `none` by default or `markdown`
  when the caller has an `mdformat` hook. `link-fragments` defaults to `true`.
- **Output:** `version` is the selected release version.
- **Side effects:** Links named fragments to their merged PRs, builds the changelog, consumes release fragments, runs
  `prek`, changes the working tree, and writes `patch`. It does not commit, tag, push, or publish.
- **Failure:** Rejects a dirty checkout, an invalid or older version, a failed formatter or `prek` run, untracked
  output, a release without user-facing notes, or an empty patch.

```yaml
  - id: prepare
    uses: tox-dev/github-workflows/prepare-towncrier@<full-commit-sha>
    with:
      bump: ${{ inputs.bump }}
      changelog: CHANGELOG.md
      format: markdown
      patch: ${{ runner.temp }}/release.patch
```

Pass `steps.prepare.outputs.version` to the next job and upload the patch as an artifact. An RST changelog uses
`format: none`; its own `prek` hooks still run. The Action uses the workflow's read token to resolve PR authors.

## Validate release patch

`tox-dev/github-workflows/validate-release-patch@<full-commit-sha>` runs in a fresh checkout of the original release
branch commit. It must receive the patch written by preparation.

- **Required inputs:** `version`, `patch`, `changelog`, and `fragments` (the fragment directory).
- **Optional inputs:** `branch` defaults to `main`, `remote` to `origin`, and `heading-prefix` to `## `. `expected-sha`
  defaults to the workflow's `GITHUB_SHA`; set it explicitly if preparation used another commit.
- **Output:** No Action output. The validated release changes are staged in the checkout.
- **Side effects:** Fetches the release branch, applies the patch to the index and working tree, and runs `prek`. It
  does not commit, tag, push, or publish.
- **Failure:** Rejects a dirty checkout, a branch that moved since preparation, a patch that does not apply, changes
  outside the changelog and fragment directory, a missing version heading, or a patch changed by `prek`.

```yaml
  - uses: tox-dev/github-workflows/validate-release-patch@<full-commit-sha>
    with:
      version: ${{ needs.assemble.outputs.version }}
      patch: ${{ runner.temp }}/release-patch/release.patch
      changelog: CHANGELOG.md
      fragments: changelog.d
```

The output is staged so a following caller step can add project-specific checks before it grants write access.

## Commit and tag release

`tox-dev/github-workflows/commit-and-tag@<full-commit-sha>` takes a validated, staged patch and a repository-scoped
GitHub App installation token.

- **Required inputs:** `version` is the tag, `token` is the App installation token, `app-slug` identifies that App, and
  `message` is the release commit message.
- **Optional inputs:** `branch` defaults to `main`; `annotated` defaults to `false` and also accepts `true`.
- **Output:** No Action output. The release commit and tag are pushed to the remote branch and tag refs.
- **Side effects:** Looks up the App bot ID, sets Git author identity in the checkout, commits the staged patch, creates
  a tag, configures Git authentication with the supplied token, and atomically pushes branch and tag. A failed atomic
  push leaves neither ref updated on the remote.
- **Failure:** Rejects unstaged or untracked changes, an empty staged patch, an invalid tag, or an invalid `annotated`
  value. The remote can reject a stale branch or a ruleset violation.

```yaml
  - id: token
    uses: actions/create-github-app-token@<full-commit-sha>
    with:
      client-id: ${{ vars.RELEASE_APP_CLIENT_ID }}
      private-key: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
      owner: ${{ github.repository_owner }}
      repositories: ${{ github.event.repository.name }}
      permission-contents: write
  - uses: tox-dev/github-workflows/commit-and-tag@<full-commit-sha>
    with:
      version: ${{ needs.assemble.outputs.version }}
      token: ${{ steps.token.outputs.token }}
      app-slug: ${{ steps.token.outputs.app-slug }}
      message: release ${{ needs.assemble.outputs.version }}
```

Install the App on only the caller repository. Store its private key as `RELEASE_APP_PRIVATE_KEY` in the caller's
`release-auth` environment, and its client ID as `RELEASE_APP_CLIENT_ID`. Give the App Contents write and Metadata read;
the token request above narrows it to one repository and Contents write. The App must bypass the caller's branch and tag
rulesets for release refs. Replace each `<full-commit-sha>` with the SHA of the named Action's repository; the
[checked-in workflow](../.github/workflows/prepare-release.yaml) contains the current token Action pin. Never pass the
private key to the composite Action.

## Follow the patch across jobs

The [prepare workflow](../.github/workflows/prepare-release.yaml) shows the complete handoff: checkout, install the
locked tools, prepare, upload the patch, download it in a fresh job, validate the original branch commit, mint the App
token, and commit and tag. Copy that workflow and replace each `uses: $/...` with a full commit SHA for this repository.
Keep repository-specific version writing, build, artifact checks, and publishing in the caller's jobs. PyPI trusted
publishing must stay in the caller's top-level workflow because
[PyPI guidance](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github).

The tag workflow should run `prek` on the tagged source before publishing. The
[self-release workflow](../.github/workflows/release.yaml) does this before it renders the GitHub Release body and
creates that release. An ecosystem publisher also verifies its package artifacts there.

## Test before a live release

The local tests run the Bash scripts with real Git, Towncrier, `release-creator`, and `prek` in temporary repositories.
They exercise failures and a push to a temporary bare remote. They do not run GitHub Actions.

The PR's [`release-dry-run` job](../.github/workflows/check.yaml) runs all three composite Actions on a GitHub runner.
It makes a synthetic squash commit and a local bare remote, prepares and validates a patch, commits and tags that local
remote, then renders GitHub notes. It uploads the patch and notes for review. It does not write a release ref to GitHub
or publish a package.

Before a consumer switches to these Actions, rehearse that consumer's own release path at its PR head. Check its
selected version, changelog, patch paths, tagged tree, package artifacts, and notes. Keep the existing workflow until
that rehearsal passes; a passing run in this repository does not validate a consumer's custom build or publisher.

# Contributing

Changes to a shared Action can affect every caller pinned to its next release. Describe the behavior you are changing
and exercise it through the script tests and the PR release rehearsal.

## Set up

Use Python 3.15 and the checked-in release-tool lock:

```bash
uv venv --python 3.15 .venv
uv pip sync --preview-features pylock --python .venv/bin/python pylock.toml
export PATH="$PWD/.venv/bin:$PATH"
```

Run the checks before pushing:

```bash
ruff format --check .
ruff check . --output-format=concise
ty check tests
pytest -q
prek run --all-files
```

`prek` formats shell with `shfmt` and YAML with `yamlfmt`; it also runs ShellCheck and zizmor. Run `prek` again after
accepting formatter changes. CI instruments all three Bash scripts with `kcov` and requires 100% line coverage. It also
tests the composite Actions on a GitHub runner.

## Change an Action

Keep its `action.yml` inputs and the script contract in sync with the [usage guide](docs/using-actions.md). Add a test
for each changed behavior, including a failure case when the Action rejects input. The script tests use temporary Git
repositories and a local bare remote. The PR `release-dry-run` job invokes all three composite Actions and uploads the
patch and rendered GitHub notes; inspect those artifacts when changing input mapping or release output.

The release preparation steps must work without a write token. Keep repository-specific build and publisher steps in the
caller. Do not add a secret to an Action input when a short-lived, repository-scoped token is sufficient.

## Open a pull request

For a user-visible change, add a fragment such as `changelog.d/+explain-inputs.doc.md`. Use the category directories
listed in `pyproject.toml`; the filename needs no issue or PR number. A squash merge lets `release-creator` link the
fragment to the PR and credit its authors. Put each distinct change in its own fragment. Write the effect on users,
without contributor credits or bot-generated changes that have no user-facing effect.

For internal-only work, apply the `skip news` label. It may be applied after the PR opens. Bot PRs need no fragment
unless they supply one; any supplied fragment is checked. PRs are squash-merged after the required checks pass. The
maintainer reviews each PR before merging it.

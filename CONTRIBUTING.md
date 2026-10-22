# Contributing

Changes to a shared Action can affect every caller pinned to its next release. Describe the behavior you are changing
and test its inputs and outputs before opening a pull request.

## Set up

Use Python 3.15 and the checked-in release-tool lock:

```bash
uv venv --python 3.15 .venv
uv pip sync --preview-features pylock --python .venv/bin/python --group release --group test pylock.toml
export PATH="$PWD/.venv/bin:$PATH"
```

Run the checks before pushing:

```bash
prek run --all-files
tox run -e type
pytest -q
```

`prek` formats YAML with `yamlfmt` and runs zizmor. Run it again after accepting formatter changes. CI extracts inline
shell from the workflows and Actions, then runs ShellCheck and `shfmt` on each block. The tests extract the exact `run:`
blocks from each composite Action and execute them in temporary Git repositories.

## Change an Action

Keep its `action.yml` inputs and step behavior in sync with the [README](README.md). Test rejected inputs and inspect
the patch and rendered notes when changing release output. Add a failure case when changing input validation.

The release preparation and Python build steps must work without a write token. Keep custom build and publisher steps in
the caller. Do not add a secret to an Action input when a short-lived, repository-scoped token is sufficient.

## Open a pull request

For a user-visible change, add a fragment such as `changelog.d/+explain-inputs.doc.md`. Use the category suffixes listed
in `pyproject.toml`; the filename needs no issue or PR number. A squash merge lets `release-creator` link the fragment
to the PR and credit its authors. Put each distinct change in its own fragment. Write the effect on users, without
contributor credits or bot-generated changes that have no user-facing effect.

For internal-only work, apply the `skip news` label. It may be applied after the PR opens. Bot PRs need no fragment
unless they supply one; any supplied fragment is checked. PRs are squash-merged after the required checks pass. The
maintainer reviews each PR before merging it.

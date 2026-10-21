# Contributing

Changes to a shared Action can affect every caller pinned to its next release. Describe the behavior you are changing
and exercise it through the PR release rehearsal on a GitHub runner.

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
blocks from each composite Action and execute them in temporary Git repositories. CI uses `kcov` to require 100% line
coverage of those blocks. The PR rehearsal also executes the composite Actions on a GitHub runner to check their wiring.

## Change an Action

Keep its `action.yml` inputs and step behavior in sync with the [README](README.md). The PR `release-dry-run` job
invokes the release Actions, checks rejected inputs, and uploads the patch and rendered GitHub notes. Inspect its steps
and artifacts when changing input mapping or release output. Add a runner failure case when changing input validation.

The release preparation and Python build steps must work without a write token. Keep custom build and publisher steps in
the caller. Do not add a secret to an Action input when a short-lived, repository-scoped token is sufficient.

## Open a pull request

For a user-visible change, add a fragment such as `changelog.d/+explain-inputs.doc.md`. Use the category directories
listed in `pyproject.toml`; the filename needs no issue or PR number. A squash merge lets `release-creator` link the
fragment to the PR and credit its authors. Put each distinct change in its own fragment. Write the effect on users,
without contributor credits or bot-generated changes that have no user-facing effect.

For internal-only work, apply the `skip news` label. It may be applied after the PR opens. Bot PRs need no fragment
unless they supply one; any supplied fragment is checked. PRs are squash-merged after the required checks pass. The
maintainer reviews each PR before merging it.

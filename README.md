# GitHub workflows

Three composite Actions share the Git operations used by tox-dev release workflows. A caller keeps its own dispatch
inputs, runner, build and publish jobs, GitHub environment, and required check names. The Actions run inside those jobs,
so repositories can place their own steps before and after them.

| Action                                                        | Job      | Result                                                                                                                    |
| ------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| [`prepare-towncrier`](prepare-towncrier/action.yml)           | Assemble | Selects a version, links fragments, builds Towncrier, formats Markdown when requested, runs `prek`, and writes a patch.   |
| [`validate-release-patch`](validate-release-patch/action.yml) | Push     | Requires the original branch commit, applies the patch, checks changed paths and the version heading, then reruns `prek`. |
| [`commit-and-tag`](commit-and-tag/action.yml)                 | Push     | Uses a repo-scoped App token to commit and atomically push the release tag.                                               |

Callers install `release-creator`, Towncrier, and `prek` from a checked-in `pylock.toml` before using these Actions.
They pass the patch between jobs with `actions/upload-artifact` and `actions/download-artifact`. The App token must be
minted after validation and limited to the caller repository with Contents write. The action itself takes the
short-lived token; it never reads a private key.

Pin each Action to a full release commit SHA. Dependabot can update GitHub Action pins weekly. Use the caller's existing
commit message and annotated-tag setting to preserve its release history. Keep PyPI's OIDC upload in the caller's
top-level workflow:
[PyPI does not support trusted publishing from reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github).

## Test and release

`check.yaml` runs ShellCheck and actionlint, then tests the scripts with a temporary bare Git remote and real Towncrier,
`release-creator`, and `prek`. The tests cover preparation, stale branches, patch paths, and atomic tagging without
publishing a release. Each caller must also rehearse its own release generation and patch validation from an exact
default-branch commit before switching to the shared Actions.

This repository prepares its own release with the local Actions. On a release tag, `release.yaml` checks the tagged
source, renders the GitHub description from `docs/changelog.md`, and publishes a GitHub Release. Consumers use immutable
version tags or the full commit SHA; the rollout pins SHAs. There is no PyPI distribution because the shipped product is
the Actions in this repository.

The first live tag requires a repository-limited release App and its key in the `release-auth` environment. See
[`prepare-release.yaml`](.github/workflows/prepare-release.yaml) for the client ID variable and key secret names.

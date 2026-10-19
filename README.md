# GitHub workflows

Three composite Actions share the Git operations used by tox-dev release workflows. A caller keeps its own dispatch
inputs, runner, build and publish jobs, GitHub environment, and required check names. The Actions run inside those jobs,
so repositories can place their own steps before and after them.

The [usage guide](docs/using-actions.md) gives the inputs, outputs, and side effects of each Action, with a complete
release preparation workflow. The Actions are [`prepare-towncrier`](prepare-towncrier/action.yml),
[`validate-release-patch`](validate-release-patch/action.yml), and [`commit-and-tag`](commit-and-tag/action.yml). See
[Contributing](CONTRIBUTING.md) to run checks and add a changelog fragment.

Callers install `release-creator`, Towncrier, and `prek` from a checked-in `pylock.toml` before using these Actions.
They pass the patch between jobs with `actions/upload-artifact` and `actions/download-artifact`. The App token must be
minted after validation and limited to the caller repository with Contents write. The action itself takes the
short-lived token; it never reads a private key.

Pin each Action to a full release commit SHA. Dependabot can update GitHub Action pins weekly. Use the caller's existing
commit message and annotated-tag setting to preserve its release history. Keep PyPI's OIDC upload in the caller's
top-level workflow:
[PyPI guidance](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github).

## Test and release

`check.yaml` runs the format, shell, and security checks. Its release rehearsal invokes the Actions on a GitHub runner
against a temporary bare Git remote. It checks preparation, stale branch rejection, patch validation, and atomic tagging
without publishing a release. Each caller must also rehearse its own release generation and patch validation from an
exact default-branch commit before switching to the shared Actions.

This repository prepares its own release with the local Actions. On a release tag, `release.yaml` checks the tagged
source, renders the GitHub description from `CHANGELOG.md`, and publishes a GitHub Release. A tag ruleset protects
release tags; the rollout pins each Action to a full commit SHA. There is no PyPI distribution because the shipped
product is the Actions in this repository.

The first live tag requires a repository-limited release App and its key in the `release-auth` environment. See
[`prepare-release.yaml`](.github/workflows/prepare-release.yaml) for the client ID variable and key secret names.

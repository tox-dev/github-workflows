# Publish a release

The tag that [preparation](release-prepare.md) pushes starts the caller's tag workflow. That workflow keeps the PyPI
upload job itself, in a separate job with `id-token: write`, because
[PyPI disallows trusted publishing from reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/).
Everything around it is shared:

| Step                            | Reusable workflow / Action                                     | Token                        |
| ------------------------------- | -------------------------------------------------------------- | ---------------------------- |
| Build wheel and sdist           | [`validate-python-release.yaml`](#validate-python-releaseyaml) | `contents: read`             |
| Build a maturin extension       | [`build-maturin-wheels.yaml`](#build-maturin-wheelsyaml)       | `contents: read`             |
| Render the GitHub Release body  | [`release-notes.yaml`](#release-notesyaml)                     | `contents: read`             |
| Upload to PyPI                  | caller job with `pypa/gh-action-pypi-publish`                  | `id-token: write`, `release` |
| Verify PyPI, create the Release | [`github-release.yaml`](#github-releaseyaml)                   | `contents: write`, `release` |

The GitHub Release job depends on the PyPI job and checks PyPI's files first, so a Release does not announce files PyPI
lacks.

## A complete tag workflow

The pytest-print release workflow, for one package built with the standard `uv` wheel and sdist build:

```yaml
name: 🚀 Release to PyPI
on:
  push:
    tags: ["*"]
permissions:
  contents: read
concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false
jobs:
  build:
    name: 🏗️ Build
    uses: tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
    permissions:
      contents: read
  notes:
    name: 📝 Render GitHub Release notes
    uses: tox-dev/github-workflows/.github/workflows/release-notes.yaml@SHA
    permissions:
      contents: read
    with:
      tag: ${{ github.ref_name }}
      artifact-url: https://pypi.org/project/pytest-print/${{ github.ref_name }}/
  pypi:
    name: 🚀 Publish to PyPI
    needs: build
    runs-on: ubuntu-26.04
    environment:
      name: release
      url: https://pypi.org/project/pytest-print/${{ github.ref_name }}
    permissions:
      id-token: write
    steps:
      - name: 📩 Download distributions
        uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with:
          artifact-ids: ${{ needs.build.outputs.distributions-artifact-id }}
          path: dist/
      - name: 🚀 Publish to PyPI
        uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3
        with:
          packages-dir: dist
          attestations: true
  github-release:
    name: 🚀 Publish GitHub Release
    needs: [build, pypi, notes]
    uses: tox-dev/github-workflows/.github/workflows/github-release.yaml@SHA
    permissions:
      contents: write
    with:
      project: pytest-print
      version: ${{ github.ref_name }}
      tag: ${{ github.ref_name }}
      artifact-pattern: python-package-distributions
      notes-artifact-id: ${{ needs.notes.outputs.artifact-id }}
```

A repository with a shared changelog, such as toml-fmt, sets `package` per package. Its build job is a reusable workflow
of the repository itself, which exposes `version` as an output:

```yaml
name: 🚀 pyproject-fmt
on:
  push:
    tags: ["pyproject-fmt/*"]
permissions: {}
concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false
jobs:
  build:
    name: 🏗️ Build distributions
    uses: ./.github/workflows/pyproject_fmt_build.yaml
    permissions:
      contents: read
      pull-requests: read
  notes:
    name: 📝 Render GitHub Release notes
    uses: tox-dev/github-workflows/.github/workflows/release-notes.yaml@SHA
    permissions:
      contents: read
    with:
      tag: ${{ github.ref_name }}
      package: pyproject-fmt
      artifact-url: https://pypi.org/project/pyproject-fmt/${{ replace(github.ref_name, 'pyproject-fmt/', '') }}/
  pypi:
    name: 🚀 Publish to PyPI
    needs: build
    runs-on: ubuntu-26.04
    environment:
      name: release
      url: https://pypi.org/project/pyproject-fmt/${{ needs.build.outputs.version }}/
    permissions:
      id-token: write
    steps:
      - name: 📩 Download distributions
        uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333 # v8.0.2
        with:
          pattern: pyproject-fmt-wheels-*
          path: dist
          merge-multiple: true
      - name: 🚀 Publish to PyPI
        uses: pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3
        with:
          packages-dir: dist
  github-release:
    name: 🚀 Publish GitHub Release
    needs: [build, pypi, notes]
    uses: tox-dev/github-workflows/.github/workflows/github-release.yaml@SHA
    permissions:
      contents: write
    with:
      project: pyproject-fmt
      version: ${{ needs.build.outputs.version }}
      tag: ${{ github.ref_name }}
      artifact-pattern: pyproject-fmt-wheels-*
      notes-artifact-id: ${{ needs.notes.outputs.artifact-id }}
```

This repository's own [release.yaml](../.github/workflows/release.yaml) shows the GitHub-only path: render notes, then
[`publish-github-release`](#publish-github-release) with no ecosystem upload.

## `validate-python-release.yaml`

One `build` job (check name `🏗️ Build distributions`) checks out `github.sha` with full history, exports hashed build
constraints from the caller lock's `build` group, builds the wheel and sdist with uv on Python 3.15 with
`--require-build-hashes` and `SOURCE_DATE_EPOCH` set to the last commit time, and uploads them as
`<artifact-prefix>python-package-distributions`. It does not inspect the built files; check package metadata and wheel
contents in the package's own `tox -e pkg_meta` run. It neither renders notes nor creates the GitHub Release.

```yaml
build:
  uses: >-
    tox-dev/github-workflows/.github/workflows/validate-python-release.yaml@SHA
  permissions:
    contents: read
```

| Input                   | Default  | Purpose                                                                                             |
| ----------------------- | -------- | --------------------------------------------------------------------------------------------------- |
| `source`                | `.`      | Directory to build.                                                                                 |
| `artifact-prefix`       | empty    | Prefix for the artifact name; set it when one tag builds several distribution paths, one call each. |
| `exclude-newer`         | `7 days` | Cutoff for the tools the Actions install, see [cutoffs](locked-tools.md#cutoffs).                   |
| `exclude-newer-package` | empty    | Newline-separated `name=date` overrides.                                                            |

Output: `distributions-artifact-id`. Publish only after the workflow succeeds: download with pinned `download-artifact`
[v8.0.2](https://github.com/actions/download-artifact/blob/9000827ccba6bdab643e8b6fd33ac0654aef8333/action.yml#L37-L45)
and `artifact-ids: ${{ needs.build.outputs.distributions-artifact-id }}`. The download checks the artifact digest and
selects exactly the wheel and sdist from that build run. The caller keeps PyPI OIDC in its `release` environment job.

Pitfall: the `build` group must hold every build requirement, since a missing hash fails the build. A caller pinned to a
workflow commit runs that commit's local Actions.

## `build-maturin-wheels.yaml`

Builds a maturin extension for a JSON build matrix and uploads the wheels and sdist under artifact names the caller's
publisher reads. Jobs hold `contents: read` at most.

- `source` (`🏷️ Prepare source`) checks out the commit, installs the caller lock's `release-build` group to read the
  maturin version, runs `pre-build-command` once, and uploads `<package-name>-source` (kept one day), so every wheel job
  builds the same tree.
- `build` (`🏗️ <artifact>`) runs once per matrix entry with `--locked --release`, then `post-build-command`, and uploads
  `<package-name>-wheels-<artifact>`.
- `sdist` (`🏗️ sdist`) builds the sdist from `package-path` with constraints from the `build` group and uploads
  `<package-name>-wheels-sdist`, so the pattern `<package-name>-wheels-*` selects every file.
- `gate` (`🚦 Build distributions pass`) runs `required-checks` over the three; `sdist` may end skipped.

```yaml
jobs:
  build:
    uses: >-
      tox-dev/github-workflows/.github/workflows/build-maturin-wheels.yaml@SHA
    with:
      package-name: pyproject-fmt
      package-path: pyproject-fmt
      matrix: >-
        [
          {"os": "ubuntu-24.04", "target": "x86_64", "artifact": "linux-x86_64", "manylinux": "2_28",
           "python": "3.15 3.14t pypy3.11"},
          {"os": "ubuntu-24.04", "target": "aarch64", "artifact": "linux-aarch64", "args": "--zig"},
          {"os": "ubuntu-24.04", "target": "x86_64", "artifact": "linux-x86_64-315t",
           "python": "3.15t", "args": "--no-default-features --features extension-module"},
          {"os": "windows-2025", "target": "x64", "artifact": "windows-x64", "python": "3.15 3.14t"},
          {"os": "macos-15", "target": "aarch64", "artifact": "macos-aarch64", "python": "3.15 3.14t pypy3.11"}
        ]
      post-build-command: uv run --no-project pyproject-fmt/build_backend.py dist
    permissions:
      contents: read
```

| Input                         | Default  | Purpose                                                                                                                                                                          |
| ----------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `package-name` **(required)** |          | Prefix of every artifact name.                                                                                                                                                   |
| `matrix` **(required)**       |          | JSON array of build entries, keys below.                                                                                                                                         |
| `package-path`                | `.`      | Directory holding the package's `Cargo.toml`; the sdist is built from it. `Cargo.lock` must exist, since builds use `--locked`.                                                  |
| `sdist`                       | `true`   | `false` skips the sdist job.                                                                                                                                                     |
| `release-build`               | `false`  | Build without sccache. Any tag ref also runs in release mode, so a tag caller can omit it.                                                                                       |
| `pre-build-command`           | empty    | Runs once in the source job from the checkout root. Use it for a version bump, which must happen before the source artifact is written.                                          |
| `post-build-command`          | empty    | Runs in each wheel job after maturin, from the checkout root, with the wheels in `dist`. Vendoring belongs here, because maturin skips the PEP 517 hook that would vendor files. |
| `exclude-newer`               | `7 days` | Cutoff for the locked-group installs, see [cutoffs](locked-tools.md#cutoffs).                                                                                                    |
| `exclude-newer-package`       | empty    | Newline-separated `name=date` overrides.                                                                                                                                         |

Matrix entry keys:

- `os`: runner label, used as `runs-on`.
- `target`: Rust target triple passed to maturin.
- `artifact`: suffix of the uploaded `<package-name>-wheels-<artifact>` artifact.
- `python`: space-separated interpreters for `--interpreter`. Leave it out for cross targets, where maturin finds no
  host interpreter; a native entry without it builds for the job's Python 3.15.
- `manylinux`: manylinux or musllinux policy; default `auto`.
- `args`: extra maturin arguments, such as `--zig`.

Both commands run under `bash -c`; the caller installs whatever they need, such as cargo-edit for `cargo set-version`.
Release mode and Windows entries build without sccache, which breaks MSVC builds of C dependencies. `workflow_call`
defaults cannot be expressions, so the workflow combines `release-build` and the tag check inside. The `release-build`
and `build` groups come from the root `pylock.toml`, the lock
[`export-build-constraints`](locked-tools.md#export-build-constraints-export-build-constraints) reads. The workflow has
no outputs; download artifacts by name.

What stays in the caller:

- Profile-guided optimization. A PGO leg needs an instrumented build, a training run, and a profile check inside the
  same job. Simplint keeps its four PGO legs in a local job and passes the remaining matrix entries to this workflow.
- Version selection, README generation, and any other change to the source beyond `pre-build-command`.
- Package checks on the built files, such as an sdist that must carry vendored code. The workflow inspects nothing
  inside them; check them in the package's own `tox -e pkg_meta` run.
- Publishing. Keep PyPI trusted publishing in the caller's tag workflow.

## `release-notes.yaml`

Renders the GitHub Release body in a read-only job with full history and uploads it as
`github-release-notes-<run attempt>`. It installs the caller lock's `release-notes` group, which must hold
release-creator, and runs [`render-release-notes`](#render-release-notes) with `previous: auto`, so callers need no
separate [`select-previous-tag`](#select-previous-tag) step.

| Input                   | Default  | Purpose                                                                                                                                                             |
| ----------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tag` **(required)**    |          | Release tag, such as `1.2.3` or `pyproject-fmt/1.2.3`.                                                                                                              |
| `changelog`             | empty    | Tracked changelog path. Empty reads `filename` from committed Towncrier configuration, so a repository without one, such as a multi-package workspace, must set it. |
| `artifact-url`          | empty    | Passed to `render-release-notes`.                                                                                                                                   |
| `artifact-label`        | empty    | Passed to `render-release-notes`.                                                                                                                                   |
| `package`               | empty    | Package section of a shared Markdown changelog. The previous tag is then the one before `tag` in the same package namespace.                                        |
| `exclude-newer`         | `7 days` | Cutoff for the tools the Actions install.                                                                                                                           |
| `exclude-newer-package` | empty    | Newline-separated `name=date` overrides.                                                                                                                            |

Output: `artifact-id` of the notes artifact. The caller job needs `contents: read`.

## `github-release.yaml`

One job in the caller's `release` environment with `contents: write`. It downloads the distributions matching
`artifact-pattern` into `dist` and the notes by ID, runs [`reconcile-pypi-artifacts`](#reconcile-pypi-artifacts) on
`dist`, then runs [`publish-github-release`](#publish-github-release) in `complete` mode on the workflow's `github.sha`
with title `<title-prefix><tag>`. Run it after the PyPI job. The `release` environment must exist and allow the tag ref.

| Input                              | Default  | Purpose                                                                                                                                    |
| ---------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `project` **(required)**           |          | PyPI project that `reconcile-pypi-artifacts` compares with the build.                                                                      |
| `version` **(required)**           |          | PyPI version to compare.                                                                                                                   |
| `tag` **(required)**               |          | Git tag the Release targets.                                                                                                               |
| `artifact-pattern` **(required)**  |          | Artifact name pattern of the distributions the PyPI job uploaded.                                                                          |
| `notes-artifact-id` **(required)** |          | `artifact-id` output of `release-notes.yaml`.                                                                                              |
| `title-prefix`                     | empty    | Text before the tag in the title, such as `v`.                                                                                             |
| `assets-directory`                 | empty    | Directory of assets to attach. `dist` is the only downloaded directory, so set `dist` to attach the distributions; empty attaches nothing. |
| `exclude-newer`                    | `7 days` | Cutoff for `pypi-attestations`.                                                                                                            |
| `exclude-newer-package`            | empty    | Newline-separated `name=date` overrides.                                                                                                   |

The job refuses `pull_request`, `pull_request_target`, `workflow_run`, `issue_comment`, and `merge_group` callers: its
first step fails with an error naming the event, before any artifact is downloaded or the Release is written. Trigger
the caller on `push`, `schedule`, `workflow_dispatch`, or `release`.

## Building-block Actions

### `render-release-notes`

Checks the tag and its changelog section, finds the previous tag, and renders an unwrapped Release body with
release-creator (which must be on `PATH`) to `$RUNNER_TEMP/release-notes.md`. Call it on the actual tag in a read-only
job with full history. It writes no GitHub Release; pass the file to `gh release create --notes-file` or
`publish-github-release` only after the ecosystem publisher succeeds.

```yaml
  - uses: tox-dev/github-workflows/render-release-notes@SHA
    with:
      tag: ${{ github.ref_name }}
      changelog: CHANGELOG.md
      artifact-url: https://pypi.org/project/example/${{ github.ref_name }}/
```

| Input                      | Default | Purpose                                                                                                                                                                              |
| -------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `tag` **(required)**       |         | Release version, such as `1.2.3`. The checkout must contain its changelog section.                                                                                                   |
| `changelog` **(required)** |         | Tracked Markdown or reStructuredText changelog that `release-creator notes` parses, with exactly one section for the tag.                                                            |
| `artifact-url`             | empty   | Ecosystem release URL, such as a PyPI version page; omit it for a GitHub-only project. One URL per line for several packages; the links share one line of the body, comma separated. |
| `artifact-label`           | empty   | Link text per `artifact-url` line, same order. Empty uses release-creator's `PyPI release`; use `Zipapp` or another product name for other artifacts. The line count must match.     |
| `previous`                 | `auto`  | Previous tag, or `auto` to calculate it from Git history.                                                                                                                            |
| `package`                  | empty   | Package section of a shared Markdown changelog, such as `pyproject-fmt`.                                                                                                             |

release-creator adds an emoji for each link's ecosystem. The Action reads `GITHUB_REPOSITORY` for pull request and
comparison links. It rejects an invalid tag, a missing heading, an empty body, or a missing comparison link when an
earlier tag exists. No named output.

### `select-previous-tag`

Finds the preceding numeric tag with release-creator's version rules; a `package/1.2.3` tag looks only in that package's
namespace. Check out the tag history and put release-creator on `PATH` first. It reads Git tags and writes one output.

```yaml
  - id: previous
    uses: tox-dev/github-workflows/select-previous-tag@SHA
    with:
      tag: ${{ github.ref_name }}
```

Input `tag` **(required)**. Output `previous`, empty for the first matching release.

### `reconcile-pypi-artifacts`

Compares the complete validated distribution directory with PyPI's Simple JSON API and verifies a trusted-publisher
attestation for each file. Run it after the publisher; the GitHub Release writer must depend on it.

```yaml
  - uses: tox-dev/github-workflows/reconcile-pypi-artifacts@SHA
    with:
      project: example
      version: ${{ github.ref_name }}
      dist: dist
```

Inputs `project`, `version`, and `dist` are required; `exclude-newer` (`7 days`) and `exclude-newer-package` set the
cutoff for `pypi-attestations`, which it installs on Python 3.15. It waits up to 120 seconds for PyPI's listing to
propagate, compares every file in `dist` with it, then runs `pypi-attestations verify pypi` on each local file against
the caller repository. A different digest in an already published file, an unexpected or yanked file, a malformed
response, or an invalid attestation fails. It prints no credentials.

Upload the complete validated directory with the pinned PyPI publisher. If a run fails, use "Re-run failed jobs" so the
upload repeats with the same built files.

### `publish-github-release`

Writes a GitHub Release from the rendered notes. Run it in a Contents-write job with `GH_TOKEN` in its environment; it
needs no checkout or tool installation. Enable immutable releases in the repository first.

```yaml
  - uses: tox-dev/github-workflows/publish-github-release@SHA
    env:
      GH_TOKEN: ${{ github.token }}
    with:
      tag: ${{ github.ref_name }}
      commit: ${{ github.sha }}
      title: ${{ github.ref_name }}
      notes-file: ${{ runner.temp }}/release-notes.md
```

| Input                       | Default    | Purpose                                                                                                                                                                                                                               |
| --------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tag` **(required)**        |            | Tag of the Release, in the caller repository.                                                                                                                                                                                         |
| `commit` **(required)**     |            | The tag's commit, used as target when the Action creates the Release.                                                                                                                                                                 |
| `title` **(required)**      |            | Release title.                                                                                                                                                                                                                        |
| `notes-file` **(required)** |            | The exact rendered notes file.                                                                                                                                                                                                        |
| `assets-directory`          | empty      | Assets to attach. Each filename and SHA256 is compared with GitHub's asset metadata; missing draft assets are uploaded, extra or changed ones rejected. After publication it verifies GitHub's release attestation for each.          |
| `prerelease`                | `false`    | Literal `true` or `false`.                                                                                                                                                                                                            |
| `mode`                      | `complete` | `complete` creates or resumes a draft and publishes it. `stage` creates or resumes a draft and uploads assets without publishing. `publish` publishes the draft, creating it if missing, after checking its complete asset set again. |

Before it writes a draft, the Action asks GitHub to generate notes for the range from the previous tag in the notes'
`Full Changelog` link to `tag`, and adds GitHub's first-time contributors, bots excluded, as a `New Contributors`
section above the trailing links. The changelog file never carries this list.

Use `mode: stage` for a repository that must upload GitHub assets before PyPI: stage, verify PyPI's exact artifact set,
then call again with `mode: publish` and the same `assets-directory`. The draft stays private until the second call
succeeds.

How reruns behave:

- A retry resumes the existing draft and updates its title, notes, and prerelease flag. A published Release causes no
  write and is left as it is; a Release with a different asset set fails.
- A draft's assets are checked again before upload and publication. A published Release whose API record is immutable
  has its assets checked from the release listing, with no write or second fetch; older mutable releases keep the
  recheck.
- A failed upload leaves the draft for a later retry. Incomplete `starter` assets are removed before retrying. After
  draft creation or an asset upload, reading the Release by ID is retried for up to ten seconds; a mismatch still fails
  when that window ends.
- A GitHub API call that fails with a server or network error is attempted up to three times in total, with backoff; a
  4xx fails at once. Draft creation is not retried, since a request GitHub had already applied would leave a second
  draft. If the publish call fails, the Action reads the Release again and succeeds when GitHub already published it
  with the expected assets and notes, which covers a response lost after GitHub applied the change.
- Asset names are compared after GitHub's renaming: characters outside `A-Z a-z 0-9 . _ + -` become `.`.

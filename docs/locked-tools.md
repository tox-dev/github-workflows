# Locked tools and cutoffs

Release jobs install their tools from the caller's own lock, hash-checked, so a release runs exactly the
release-creator, Towncrier, and prek versions the repository reviewed. Tools the Actions need for themselves come from
PyPI under an upload cutoff instead, so a new upstream release reaches callers only after it has been public for a week.
Tests are the exception on purpose: CI resolves test, type, and documentation dependencies fresh, to catch upstream
changes early.

## The caller's lock

`pylock.toml` comes from `nab lock --all-groups --all-extras`. It records runtime dependencies, every extra, and every
dependency group across the supported Python versions and platforms. The cutoff and any per-package exception live in
the caller's `[tool.nab]` table. The groups the shared workflows install:

| Group             | Must provide                     | Installed by                                                                         |
| ----------------- | -------------------------------- | ------------------------------------------------------------------------------------ |
| `release-prepare` | release-creator, Towncrier, prek | `prepare-towncrier-release`, `prepare-release-creator`, `update-python-dependencies` |
| `release-notes`   | release-creator                  | `release-notes`                                                                      |
| `release-news`    | release-creator, Towncrier       | the caller's news job, before `validate-news`                                        |
| `release-build`   | maturin                          | `build-maturin-wheels` (source job)                                                  |
| `build`           | the build backend and its needs  | build constraints for every package build                                            |

A full lock records each group and extra, but a new combination still needs an install check before a caller uses it.
Lock integrity comes from Nab: [`refresh-release-lock`](#refresh-release-lock) in `check` mode regenerates the lock and
fails if it differs, on every pull request that changes a release input (through
[`validate-news`](pr-checks.md#check-pull-request-news-validate-news)).

## Cutoffs

The Actions install the tools they run themselves, such as Nab, `packaging`, `certifi`, and `pypi-attestations`, from
PyPI with `uv pip install --exclude-newer`, without hashes. Each tool has only a minimum version, such as `nab>=0.0.22`,
and there is no shared lock, so a tool release reaches callers once it is older than the cutoff. Every Action and
reusable workflow that installs such a tool takes two inputs:

- `exclude-newer`: the cutoff, `7 days` by default. uv accepts a timestamp or a duration.
- `exclude-newer-package`: newline-separated `name=date` pairs, each passed to uv as `--exclude-newer-package`, to let a
  single package past the cutoff in an emergency.

```yaml
  - uses: tox-dev/github-workflows/refresh-release-lock@SHA
    with:
      mode: check
      exclude-newer-package: |
        nab=2026-10-24T00:00:00Z
```

The tools the caller's release jobs run, such as release-creator, Towncrier, and prek, still come hash-checked from the
caller's `pylock.toml`. [`cooled-prek`](#run-prek-under-the-cutoff-cooled-prek) has a fixed cutoff and no such inputs.

## Expire cutoff exceptions

A `[tool.nab]` exception that admits one package past the cutoff, `packages.<name>.uploaded-prior-to`, carries its
expiry date in a comment directly above the package table header or dotted key:

```toml
# expires 2026-11-09
[tool.nab.packages.release-creator]
uploaded-prior-to = 2026-11-02T21:45:00Z
```

Nab rejects unknown keys in a package table, so the date cannot sit beside the value. The date is the last day the
exception is valid. The check fails when an exception has no such comment, a malformed date, or a date that has passed,
and names the package. A standalone `nab.toml` is checked the same way. An exception in `[[tool.nab.package-rules]]` is
rejected, since the check does not read those tables; move it to a package table.

The check runs in three places:

- `upgrade-release-tools.yaml`, before it refreshes the lock. Every caller's scheduled run therefore fails on an expired
  or undated exception, even when no release input changed.

- `refresh-release-lock` in `check` mode, which `validate-news` calls when a pull request changes `pyproject.toml`,
  `pylock.toml`, a root `pylock.*.toml`, or `nab.toml`.

- The `check-nab-exceptions` Action on its own. It reads `pyproject.toml` and, if present, `nab.toml` from the checkout
  and takes no inputs:

  ```yaml
  - uses: tox-dev/github-workflows/check-nab-exceptions@SHA
  ```

## Run prek under the cutoff: `cooled-prek`

Shared workflows run every prek command through this Action. Hook environments install from PyPI under a fixed seven-day
cutoff, with the repository's uv settings (config file, indexes, certificates) ignored. It passes
`--config .pre-commit-config.yaml`; without that flag prek prefers a root `prek.toml` and also runs nested
configurations, which no guard checks.

```yaml
  - uses: tox-dev/github-workflows/cooled-prek@SHA
    with:
      args: run --all-files
```

Input `args` **(required)**: whitespace-separated prek arguments, such as `install-hooks`. prek must be on `PATH`.

A package with a `packages.<name>.uploaded-prior-to` exception in `pyproject.toml`'s `[tool.nab]` is admitted up to that
date in hook environments too. So a hook dependency pinned to a release newer than the cutoff, such as `sphinx` for
`docstrfmt`, needs the same temporary exception the release lock uses; delete it once the release is a week old.
Pitfall: hook environments read exceptions only from `pyproject.toml`, not from a standalone `nab.toml`.

## Install locked tools: `install-locked-tools`

Creates a virtual environment and installs the selected groups from the caller's `pylock.toml`, hash-checked. Source
builds use constraints generated from the lock's `build` group under the runner's temporary directory. It leaves tracked
files unchanged. Run `actions/checkout` and `astral-sh/setup-uv` with Python 3.15 before it.

```yaml
  - uses: tox-dev/github-workflows/install-locked-tools@SHA
    with:
      groups: release-news
      venv: ${{ runner.temp }}/release-tools
```

| Input                   | Default       | Purpose                                                                                                                           |
| ----------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `groups`                | empty         | Whitespace-separated groups to install from `pylock.toml`. Empty exports build constraints without installing anything.           |
| `venv`                  | empty         | Directory for the virtual environment; required when `groups` is set.                                                             |
| `constraints-lock`      | `pylock.toml` | Lock to export build constraints from. Use a secondary lock when the build matrix differs from the release-tool matrix.           |
| `target-platform`       | empty         | Nab platform ID for the constraints. Pass it with `targets` for a specific build target; otherwise the runner selects the target. |
| `targets`               | empty         | Space-separated `full-version:implementation` pairs for the constraints.                                                          |
| `exclude-newer`         | `7 days`      | Cutoff for the lock reader the Action installs from PyPI, see [cutoffs](#cutoffs).                                                |
| `exclude-newer-package` | empty         | Newline-separated `name=date` overrides.                                                                                          |

Output `build-constraints`: path of the hashed constraints file. The Action adds the installed command launchers to
`GITHUB_PATH` for later steps, while the runner's `python`, `pip`, and `uv` keep their original paths. Groups always
install from `pylock.toml`.

Build constraints: a lock with a `build` group exports that group; a lock that declares other groups but no `build`
group exports an empty file; a lock with no dependency groups at all exports every locked package.

## Export build constraints: `export-build-constraints`

Writes a temporary hashed requirements file of build constraints, for a build matrix that needs constraints for specific
interpreters. It writes no tracked files.

```yaml
  - id: constraints
    uses: tox-dev/github-workflows/export-build-constraints@SHA
    with:
      lock: pylock.build.toml
      target-platform: linux_aarch64
      targets: 3.15.0:cpython
```

| Input                   | Default       | Purpose                                                |
| ----------------------- | ------------- | ------------------------------------------------------ |
| `lock`                  | `pylock.toml` | Lock to read, such as a secondary `pylock.build.toml`. |
| `target-platform`       | empty         | Nab platform ID.                                       |
| `targets`               | empty         | Space-separated `full-version:implementation` pairs.   |
| `exclude-newer`         | `7 days`      | Cutoff for the tools it installs.                      |
| `exclude-newer-package` | empty         | Newline-separated `name=date` overrides.               |

Output `path`: the constraints file.

## Refresh release lock

`refresh-release-lock` is the read-only half of [`upgrade-release-tools`](maintenance.md) and the lock check of
[`validate-news`](pr-checks.md#check-pull-request-news-validate-news). Neither mode pushes a branch or requests a write
token.

- `mode: refresh` (default) installs the newest Nab under the cutoff, upgrades the full primary lock and the optional
  secondary lock, and writes `$RUNNER_TEMP/maintenance.patch` if a lock changes. A lock whose only change is Nab's
  `created-at` stamp is restored and produces no patch.
- `mode: check` first runs [`check-nab-exceptions`](#expire-cutoff-exceptions), then regenerates the locks without
  upgrading and fails if anything other than Nab's recorded command line differs. The committed lock must carry a valid
  `created-at` that is not in the future. Check mode installs the Nab version that the committed `pylock.toml` records
  in `[tool.nab] nab-version`, and fails if the lock has none, because a newer Nab would rewrite that field in every
  committed lock.

Every Nab run unsets `SSL_CERT_FILE` and `SSL_CERT_DIR`, so Nab uses its own certificate store.

| Input                               | Default           | Purpose                                                          |
| ----------------------------------- | ----------------- | ---------------------------------------------------------------- |
| `mode`                              | `refresh`         | `refresh` or `check`.                                            |
| `additional-lock`                   | empty             | Basename of a secondary Nab lock for a separate build matrix.    |
| `additional-lock-groups`            | empty             | Groups for the secondary lock; empty selects build requirements. |
| `additional-lock-selection`         | `build-or-groups` | `project` selects the project's runtime dependencies instead.    |
| `additional-matrix-python`          | empty             | Python range for the secondary lock.                             |
| `additional-matrix-platforms`       | empty             | Space-separated Nab platform IDs.                                |
| `additional-matrix-implementations` | empty             | Space-separated Python implementations.                          |
| `exclude-newer`                     | `7 days`          | Cutoff for Nab in refresh mode and the other tools.              |
| `exclude-newer-package`             | empty             | Newline-separated `name=date` overrides.                         |

Output `changed`: `true` only when refresh produces a patch. The resulting pull request's normal formatting job runs
prek, and the writer checks patch paths and modes.

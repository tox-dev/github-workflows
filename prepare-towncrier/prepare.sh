#!/usr/bin/env bash
set -euo pipefail

if [[ -n $(git status --porcelain) ]]; then
	echo '::error::release preparation requires a clean checkout' >&2
	exit 1
fi

if [[ -z "$VERSION" ]]; then
	VERSION=$(git tag --list | release-creator tags --next "$BUMP")
fi
git tag --list | release-creator tags "$VERSION" --require-newer

if [[ "$LINK_FRAGMENTS" != true && "$LINK_FRAGMENTS" != false ]]; then
	echo '::error::link-fragments must be true or false' >&2
	exit 1
fi
if [[ "$LINK_FRAGMENTS" == true ]]; then
	release-creator fragments --repository "$GITHUB_REPOSITORY" --git --resolve-authors
fi

towncrier build --yes --version "$VERSION"
if [[ "$FORMAT" != markdown && "$FORMAT" != none ]]; then
	echo '::error::format must be markdown or none' >&2
	exit 1
fi
if [[ "$FORMAT" == markdown ]]; then
	if ! prek run mdformat --files "$CHANGELOG"; then
		prek run mdformat --files "$CHANGELOG"
	fi
fi
notes=$(release-creator notes --changelog "$CHANGELOG" --tag "$VERSION" --repository "$GITHUB_REPOSITORY")
if [[ "$notes" != *'### '* ]]; then
	echo '::error::release preparation has no release notes' >&2
	exit 1
fi

prek run --all-files
if [[ -n $(git ls-files --others --exclude-standard) ]]; then
	echo '::error::release preparation created untracked files' >&2
	exit 1
fi
git diff --check
git diff HEAD --binary >"$PATCH"
if [[ ! -s "$PATCH" ]]; then
	echo '::error::release preparation produced no patch' >&2
	exit 1
fi
printf 'version=%s\n' "$VERSION" >>"$GITHUB_OUTPUT"

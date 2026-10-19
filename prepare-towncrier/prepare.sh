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

case "$LINK_FRAGMENTS" in
true) release-creator fragments --repository "$GITHUB_REPOSITORY" --git --resolve-authors ;;
false) ;;
*)
	echo '::error::link-fragments must be true or false' >&2
	exit 1
	;;
esac

towncrier build --yes --version "$VERSION"
case "$FORMAT" in
markdown)
	if ! prek run mdformat --files "$CHANGELOG"; then
		prek run mdformat --files "$CHANGELOG"
	fi
	;;
none) ;;
*)
	echo '::error::format must be markdown or none' >&2
	exit 1
	;;
esac

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

#!/usr/bin/env bash
set -euo pipefail

if [[ $# == 0 || $1 == source ]]; then
	if [[ -n $(git status --porcelain) ]]; then
		echo '::error::release validation requires a clean checkout' >&2
		exit 1
	fi
	git fetch "$REMOTE" "$BRANCH"
	if [[ $(git rev-parse "$REMOTE/$BRANCH") != "${EXPECTED_SHA:-$GITHUB_SHA}" ]]; then
		echo "::error::$BRANCH changed during release preparation; dispatch again" >&2
		exit 1
	fi
fi

if [[ $# == 0 || $1 == patch ]]; then
	git apply --check "$PATCH"
	git apply --index "$PATCH"
	if git diff --cached --quiet; then
		echo '::error::release patch contains no changes' >&2
		exit 1
	fi
	mapfile -d '' -t paths < <(git diff --cached --name-only -z)
	for path in "${paths[@]}"; do
		if [[ "$path" != "$CHANGELOG" && "$path" != "$FRAGMENTS/"* ]]; then
			echo "::error::unexpected release path: $path" >&2
			exit 1
		fi
	done

	heading_found=false
	mapfile -t changelog_lines <"$CHANGELOG"
	for line in "${changelog_lines[@]}"; do
		if [[ "$line" == "$HEADING_PREFIX$VERSION ("* ]]; then
			heading_found=true
		fi
	done
	if [[ "$heading_found" != true ]]; then
		echo "::error::$CHANGELOG has no section for $VERSION" >&2
		exit 1
	fi
fi

if [[ $# == 0 || $1 == prek ]]; then
	git diff --cached --check
	staged_patch_sha=$(git diff --cached --binary | sha256sum)
	if ! prek run --all-files; then
		echo '::error::prek failed on the validated release patch' >&2
		exit 1
	fi
	if [[ $(git diff --cached --binary | sha256sum) != "$staged_patch_sha" ]] ||
		! git diff --quiet ||
		[[ -n $(git ls-files --others --exclude-standard) ]]; then
		echo '::error::prek changed the validated release patch' >&2
		exit 1
	fi
fi

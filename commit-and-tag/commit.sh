#!/usr/bin/env bash
set -euo pipefail

if git diff --cached --quiet || ! git diff --quiet || [[ -n $(git ls-files --others --exclude-standard) ]]; then
  echo '::error::expected only a staged release patch' >&2
  exit 1
fi
if [[ "$ANNOTATED" != true && "$ANNOTATED" != false ]]; then
  echo '::error::annotated must be true or false' >&2
  exit 1
fi
if ! git check-ref-format "refs/tags/$VERSION"; then
  echo "::error::invalid release tag: $VERSION" >&2
  exit 1
fi

app_user_id=$(gh api "/users/${APP_SLUG}[bot]" --jq .id)
git config user.name "${APP_SLUG}[bot]"
git config user.email "${app_user_id}+${APP_SLUG}[bot]@users.noreply.github.com"
git commit -m "$MESSAGE"
case "$ANNOTATED" in
  true) git tag -a -m "$MESSAGE" -- "$VERSION" ;;
  false) git tag -- "$VERSION" ;;
esac
gh auth setup-git --hostname github.com --force
git push --atomic origin "HEAD:$BRANCH" "refs/tags/$VERSION"

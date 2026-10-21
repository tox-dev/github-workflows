#!/usr/bin/env bash
set -euo pipefail

case "$REPOSITORY" in
*/*) ;;
*) exit 1 ;;
esac
for part in "${REPOSITORY%%/*}" "${REPOSITORY#*/}"; do
  case "$part" in
  '' | *[!A-Za-z0-9_.-]*) exit 1 ;;
  esac
done
case "$PR_NUMBER" in
'' | 0* | *[!0-9]*) exit 1 ;;
esac
test "${#HEAD_SHA}" -eq 40
case "$HEAD_SHA" in
*[!0-9a-f]*) exit 1 ;;
esac
case "$MINIMUM_DAYS" in
'' | 0* | *[!0-9]*) exit 1 ;;
esac
test "$GITHUB_EVENT_NAME" = pull_request
jq -e --argjson number "$PR_NUMBER" --arg head "$HEAD_SHA" '
  .number == $number and .pull_request.head.sha == $head
' "$GITHUB_EVENT_PATH" >/dev/null
gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" >"$RUNNER_TEMP/hook-update-pr.json"
jq -e --arg repository "$REPOSITORY" --arg head "$HEAD_SHA" '
  .state == "open" and .base.repo.full_name == $repository and
  .head.sha == $head and
  (.user.login | type == "string")
' "$RUNNER_TEMP/hook-update-pr.json" >/dev/null
author=$(jq -r .user.login "$RUNNER_TEMP/hook-update-pr.json")
if [[ "$author" == 'pre-commit-ci[bot]' ]]; then
  committed=$(gh api "repos/$REPOSITORY/commits/$HEAD_SHA" --jq .commit.committer.date)
  committed_epoch=$(date --utc --date="$committed" +%s)
  now_epoch=$(date --utc +%s)
  test "$committed_epoch" -le "$now_epoch"
  eligible_epoch=$((committed_epoch + MINIMUM_DAYS * 86400))
  if ((now_epoch < eligible_epoch)); then
    eligible=$(date --utc --date="@$eligible_epoch" '+%Y-%m-%dT%H:%M:%SZ')
    echo "::error::Hook update cooldown ends $eligible"
    exit 1
  fi
fi

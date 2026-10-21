#!/usr/bin/env bash
set -euo pipefail

[[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
[[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]
[[ "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]
[[ "$MINIMUM_DAYS" =~ ^[1-9][0-9]*$ ]]
test "$GITHUB_EVENT_NAME" = pull_request
jq -e --argjson number "$PR_NUMBER" --arg head "$HEAD_SHA" '
  .number == $number and .pull_request.head.sha == $head
' "$GITHUB_EVENT_PATH" >/dev/null
gh api "repos/$REPOSITORY/pulls/$PR_NUMBER" >"$RUNNER_TEMP/hook-update-pr.json"
jq -e --arg repository "$REPOSITORY" --arg head "$HEAD_SHA" '
  .state == "open" and .base.repo.full_name == $repository and
  .head.sha == $head and
  (.user.login | type == "string") and (.updated_at | type == "string")
' "$RUNNER_TEMP/hook-update-pr.json" >/dev/null
author=$(jq -r .user.login "$RUNNER_TEMP/hook-update-pr.json")
if [[ "$author" == 'pre-commit-ci[bot]' ]]; then
  committed=$(gh api "repos/$REPOSITORY/commits/$HEAD_SHA" --jq .commit.committer.date)
  committed_epoch=$(date --utc --date="$committed" +%s)
  updated_epoch=$(date --utc --date="$(jq -r .updated_at "$RUNNER_TEMP/hook-update-pr.json")" +%s)
  now_epoch=$(date --utc +%s)
  test "$committed_epoch" -le "$now_epoch" && test "$updated_epoch" -le "$now_epoch"
  if ((updated_epoch > committed_epoch)); then
    committed_epoch=$updated_epoch
  fi
  eligible_epoch=$((committed_epoch + MINIMUM_DAYS * 86400))
  if ((now_epoch < eligible_epoch)); then
    eligible=$(date --utc --date="@$eligible_epoch" '+%Y-%m-%dT%H:%M:%SZ')
    echo "::error::Hook update cooldown ends $eligible"
    exit 1
  fi
fi

#!/usr/bin/env bash
set -euo pipefail

[[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
git check-ref-format --branch "$BASE"
git check-ref-format --branch "$BRANCH"
test "$BASE" != "$BRANCH"
[[ "$BASE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
test -n "$TITLE" && test -s "$BODY_FILE" && test -s "$PATHS_FILE" && test -n "$LABEL"
if [[ -n "$BUNDLE" ]]; then
  test -f "$BUNDLE"
  [[ "$CANDIDATE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
else
  test -z "$CANDIDATE_COMMIT"
fi

paths=()
while IFS=$'\t' read -r path blob; do
  [[ "$path" =~ ^[A-Za-z0-9._/-]+$ && "$path" != /* ]]
  case "$path" in
  . | .. | ./* | ../* | */. | */.. | */./* | */../*) exit 1 ;;
  esac
  [[ "$blob" =~ ^[0-9a-f]{40}$ ]]
  paths+=("$path")
done <"$PATHS_FILE"
test "${#paths[@]}" -gt 0
test "$(printf '%s\n' "${paths[@]}" | LC_ALL=C sort -u | wc -l)" -eq "${#paths[@]}"
printf '%s\n' "${paths[@]}" | LC_ALL=C sort >"$RUNNER_TEMP/expected-paths"

if [[ -n "$BUNDLE" ]]; then
  git init --bare "$RUNNER_TEMP/post-release.git" >/dev/null
  git -C "$RUNNER_TEMP/post-release.git" bundle verify "$BUNDLE" >/dev/null
  git -C "$RUNNER_TEMP/post-release.git" fetch "$BUNDLE" \
    refs/heads/release-candidate:refs/heads/release-candidate >/dev/null
  test "$(git -C "$RUNNER_TEMP/post-release.git" rev-parse refs/heads/release-candidate)" = "$CANDIDATE_COMMIT"
  read -r commit parent extra < <(git -C "$RUNNER_TEMP/post-release.git" rev-list --parents -n 1 "$CANDIDATE_COMMIT")
  test "$commit" = "$CANDIDATE_COMMIT" && test "$parent" = "$BASE_COMMIT" && test -z "${extra:-}"
  candidate_tree=$(git -C "$RUNNER_TEMP/post-release.git" rev-parse "$CANDIDATE_COMMIT^{tree}")
  git -C "$RUNNER_TEMP/post-release.git" diff --name-only --no-renames "$BASE_COMMIT" "$CANDIDATE_COMMIT" |
    LC_ALL=C sort >"$RUNNER_TEMP/candidate-paths"
  cmp -s "$RUNNER_TEMP/expected-paths" "$RUNNER_TEMP/candidate-paths"
  while IFS=$'\t' read -r path blob; do
    read -r mode object actual _ < <(git -C "$RUNNER_TEMP/post-release.git" ls-tree "$CANDIDATE_COMMIT" -- "$path")
    test "$mode" = 100644 && test "$object" = blob && test "$actual" = "$blob"
  done <"$PATHS_FILE"
fi

head_owner=${REPOSITORY%%/*}
gh api -X GET "repos/$REPOSITORY/pulls" -f state=all -f "head=$head_owner:$BRANCH" -f per_page=100 \
  >"$RUNNER_TEMP/post-release-prs.json"
jq -e --arg repository "$REPOSITORY" --arg title "$TITLE" --arg base "$BASE" --arg branch "$BRANCH" --rawfile body "$BODY_FILE" '
  length <= 1 and all(.[];
    .title == $title and .body == $body and .base.ref == $base and
    .head.repo.full_name == $repository and .head.ref == $branch and
    (.state == "open" or (.state == "closed" and .merged_at != null))
  )
' "$RUNNER_TEMP/post-release-prs.json" >/dev/null
pr_number=$(jq -r '.[0].number // empty' "$RUNNER_TEMP/post-release-prs.json")
merged=$(jq -r '.[0].merged_at != null' "$RUNNER_TEMP/post-release-prs.json")

base_sha=$(gh api "repos/$REPOSITORY/git/ref/heads/$BASE" --jq .object.sha)
[[ "$base_sha" =~ ^[0-9a-f]{40}$ ]]
if [[ "$merged" == true ]]; then
  while IFS=$'\t' read -r path blob; do
    read -r object actual < <(gh api "repos/$REPOSITORY/contents/$path?ref=$BASE" --jq '[.type, .sha] | @tsv')
    test "$object" = file && test "$actual" = "$blob"
  done <"$PATHS_FILE"
  gh api "repos/$REPOSITORY/pulls/$pr_number/files" --paginate --jq '.[].filename' |
    LC_ALL=C sort | cmp -s - "$RUNNER_TEMP/expected-paths"
else
  test -n "$BUNDLE"
  if branch_sha=$(gh api "repos/$REPOSITORY/git/ref/heads/$BRANCH" --jq .object.sha 2>"$RUNNER_TEMP/branch-error"); then
    read -r branch_parent branch_tree < <(
      gh api "repos/$REPOSITORY/git/commits/$branch_sha" --jq '[.parents[0].sha, .tree.sha] | @tsv'
    )
    test "$branch_parent" = "$BASE_COMMIT" && test "$branch_tree" = "$candidate_tree"
  elif grep -Fq '(HTTP 404)' "$RUNNER_TEMP/branch-error"; then
    test -z "$pr_number" && test "$base_sha" = "$BASE_COMMIT"
    if [[ -z "${GIT_REMOTE_URL:-}" ]]; then
      gh auth setup-git --hostname "${GH_HOST:-github.com}" --force
    fi
    git -C "$RUNNER_TEMP/post-release.git" remote add origin \
      "${GIT_REMOTE_URL:-https://${GH_HOST:-github.com}/$REPOSITORY.git}"
    git -C "$RUNNER_TEMP/post-release.git" push origin "refs/heads/release-candidate:refs/heads/$BRANCH"
    branch_sha=$(gh api "repos/$REPOSITORY/git/ref/heads/$BRANCH" --jq .object.sha)
    test "$branch_sha" = "$CANDIDATE_COMMIT"
  else
    cat "$RUNNER_TEMP/branch-error" >&2
    exit 1
  fi
  if [[ -n "$pr_number" ]]; then
    test "$(jq -r '.[0].head.sha' "$RUNNER_TEMP/post-release-prs.json")" = "$branch_sha"
  else
    gh api -X POST "repos/$REPOSITORY/pulls" -f "head=$BRANCH" -f "base=$BASE" \
      -f "title=$TITLE" -F "body=@$BODY_FILE" >"$RUNNER_TEMP/post-release-created.json"
    pr_number=$(jq -r .number "$RUNNER_TEMP/post-release-created.json")
    [[ "$pr_number" =~ ^[1-9][0-9]*$ ]]
  fi
fi

if ! gh api "repos/$REPOSITORY/issues/$pr_number/labels" --jq '.[].name' | grep -Fxq "$LABEL"; then
  if [[ "$merged" == true ]]; then
    echo '::error::merged pull request lost its required label' >&2
    exit 1
  fi
  gh api -X POST "repos/$REPOSITORY/issues/$pr_number/labels" -f "labels[]=$LABEL" >/dev/null
fi
printf 'pull-request=%s\n' "$pr_number" >>"$GITHUB_OUTPUT"

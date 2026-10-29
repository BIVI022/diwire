#!/usr/bin/env bash
set -euo pipefail

: "${GH_REPO:?}"
: "${PR_URL:?}"
: "${PR_HEAD_SHA:?}"
: "${PR_BASE_SHA:?}"

wait_attempts="${MERGE_WAIT_ATTEMPTS:-60}"
wait_seconds="${MERGE_WAIT_SECONDS:-5}"

for workflow in ci.yaml docs.yaml; do
    run_id=""
    for ((attempt = 0; attempt < wait_attempts; attempt++)); do
        run_id="$(gh run list --repo "$GH_REPO" --workflow "$workflow" \
            --event pull_request --commit "$PR_HEAD_SHA" --limit 1 \
            --json databaseId --jq '.[0].databaseId // empty')"
        if [[ -n "$run_id" ]]; then
            break
        fi
        sleep "$wait_seconds"
    done
    if [[ -z "$run_id" ]]; then
        echo "No $workflow run found for $PR_HEAD_SHA. Refusing to merge." >&2
        exit 1
    fi
    gh run watch "$run_id" --repo "$GH_REPO" --exit-status --interval 15
done

current_head="$(gh pr view "$PR_URL" --repo "$GH_REPO" --json headRefOid --jq .headRefOid)"
current_base="$(gh api "repos/$GH_REPO/git/ref/heads/main" --jq .object.sha)"
if [[ "$current_head" != "$PR_HEAD_SHA" || "$current_base" != "$PR_BASE_SHA" ]]; then
    echo "The PR head or main changed during validation. Refusing to merge." >&2
    exit 1
fi

gh pr merge --squash --match-head-commit "$PR_HEAD_SHA" "$PR_URL" --repo "$GH_REPO"

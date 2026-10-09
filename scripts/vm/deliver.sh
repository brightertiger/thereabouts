#!/usr/bin/env bash
# Laptop side: ships a branch to the pipeline VM as a git bundle and syncs its locked dependencies.
# Usage: scripts/vm/deliver.sh [branch]   (default: work/2026-10-09). Nothing is pushed to any remote.
set -euo pipefail

: "${PIPELINE_GCP_PROJECT:=summer-sector-488705-m8}"
: "${PIPELINE_VM_NAME:=thereabouts-pipeline}"
: "${PIPELINE_VM_ZONE:=asia-south1-a}"
PIPELINE_BRANCH="${1:-work/2026-10-09}"
PIPELINE_REMOTE_ROOT=/srv/thereabouts

PIPELINE_REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
PIPELINE_HEAD="$(git -C "$PIPELINE_REPO" rev-parse --verify "refs/heads/$PIPELINE_BRANCH")"
PIPELINE_SCRATCH="$(mktemp -d)"
trap 'rm -rf "$PIPELINE_SCRATCH"' EXIT

gcloud_vm=(--project "$PIPELINE_GCP_PROJECT" --zone "$PIPELINE_VM_ZONE" --quiet)

if [[ -n "$(git -C "$PIPELINE_REPO" status --porcelain --untracked-files=no)" ]]; then
  printf 'Warning: tracked files are modified; only commits on %s are delivered.\n' "$PIPELINE_BRANCH" >&2
fi

git -C "$PIPELINE_REPO" bundle create "$PIPELINE_SCRATCH/delivery.bundle" "refs/heads/$PIPELINE_BRANCH"
gcloud compute scp "${gcloud_vm[@]}" "$PIPELINE_SCRATCH/delivery.bundle" \
  "$PIPELINE_VM_NAME:$PIPELINE_REMOTE_ROOT/delivery.bundle"

# The VM checkout is delivery-only: a dirty tree means someone edited it by hand, so stop.
gcloud compute ssh "$PIPELINE_VM_NAME" "${gcloud_vm[@]}" --command \
  "bash -l -s -- $(printf '%q ' "$PIPELINE_BRANCH" "$PIPELINE_HEAD" "$PIPELINE_REMOTE_ROOT")" <<'REMOTE'
set -euo pipefail
branch="$1"; head="$2"; root="$3"
git init -q "$root/repo"
cd "$root/repo"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "$root/repo has local changes; refusing to overwrite them" >&2
  exit 1
fi
git fetch -q "$root/delivery.bundle" "+refs/heads/$branch:refs/delivery/$branch"
git checkout -q -f -B "$branch" "refs/delivery/$branch"
[[ "$(git rev-parse HEAD)" == "$head" ]] || { echo "checked out $(git rev-parse HEAD), expected $head" >&2; exit 1; }
git log -1 --oneline
uv sync --locked </dev/null
REMOTE

printf 'Delivered %s at %s to %s:%s/repo\n' \
  "$PIPELINE_BRANCH" "${PIPELINE_HEAD:0:12}" "$PIPELINE_VM_NAME" "$PIPELINE_REMOTE_ROOT"

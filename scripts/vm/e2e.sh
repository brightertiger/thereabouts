#!/usr/bin/env bash
# World end-to-end test (spec §9 steps 2-7) over a staged release, on the VM.
#
#   scripts/vm/e2e.sh RELEASE_DIR [URL]
#
# RELEASE_DIR holds dataset/<version>/ and packs/ (as published to
# file:///mnt/data/staging). Without URL the packs/ tree is served on loopback
# with python's http.server. Sample sizes default to the spec; override with
# THEREABOUTS_E2E_LAND, _OCEAN, _NAMES, _FORWARD, _CROSS. The plate evaluation
# examples are read from the pinned plate_country evidence of the workspace in
# THEREABOUTS_E2E_WORKSPACE (default /mnt/data, read only), and the lookups
# quality gates from the manifest its cells/current.json names; that manifest
# must be the release's input, so run this before lookups runs again (set the
# variable empty to skip both checks). Writes the log and the
# Markdown report under E2E_RUN (default /srv/thereabouts/scratch/e2e/<UTC time>).
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 RELEASE_DIR [URL]" >&2
  exit 2
fi
release=$(realpath "$1")
repo=$(cd "$(dirname "$0")/../.." && pwd)
run=${E2E_RUN:-/srv/thereabouts/scratch/e2e/$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$run"

export THEREABOUTS_E2E_RELEASE="$release"
export THEREABOUTS_E2E_URL="${2:-}"
export THEREABOUTS_E2E_WORK="$run/work"
export THEREABOUTS_E2E_REPORT="$run/world-e2e.md"
export THEREABOUTS_E2E_WORKSPACE="${THEREABOUTS_E2E_WORKSPACE-/mnt/data}"

cd "$repo"
status=0
nice -n 10 uv run --no-sync pytest -m world tests/e2e/world_e2e.py \
  -p no:cacheprovider --basetemp="$run/pytest" -q -rA 2>&1 | tee "$run/e2e.log" ||
  status=$?
echo "report: $THEREABOUTS_E2E_REPORT"
exit "$status"

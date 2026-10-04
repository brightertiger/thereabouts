#!/usr/bin/env bash
# Owner-run provisioning only. This script was not executed during implementation.
set -euo pipefail

: "${PIPELINE_GCP_PROJECT:?Set the GCP project that will own the VM}"
: "${PIPELINE_SERVICE_ACCOUNT:?Set the VM service-account email}"
: "${PIPELINE_VM_NAME:=thereabouts-pipeline}"
: "${PIPELINE_RAW_BUCKET:=gs://pyofflinegeocoder-summer-sector-488705-m8}"

PIPELINE_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_MACHINE_TYPE=e2-standard-8 # 8 vCPU / 32 GB memory; requested, not benchmarked.
PIPELINE_DISK_GB=300

# Discover the actual bucket location at execution time; do not guess a region.
PIPELINE_BUCKET_REGION="$(gcloud storage buckets describe "$PIPELINE_RAW_BUCKET" \
  --project "$PIPELINE_GCP_PROJECT" --format='value(location)' | tr '[:upper:]' '[:lower:]')"
if [[ ! "$PIPELINE_BUCKET_REGION" =~ ^[a-z]+-[a-z]+[0-9]+$ ]]; then
  printf 'Bucket location %s is not a single region. Choose regional storage before provisioning.\n' \
    "$PIPELINE_BUCKET_REGION" >&2
  exit 2
fi
PIPELINE_VM_ZONE="${PIPELINE_VM_ZONE:-$(gcloud compute zones list \
  --project "$PIPELINE_GCP_PROJECT" \
  --filter="region:/$PIPELINE_BUCKET_REGION AND status=UP" \
  --sort-by=name --limit=1 --format='value(name)')}"
if [[ "$PIPELINE_VM_ZONE" != "$PIPELINE_BUCKET_REGION"-* ]]; then
  printf 'Zone %s is not in raw-mirror region %s.\n' "$PIPELINE_VM_ZONE" "$PIPELINE_BUCKET_REGION" >&2
  exit 2
fi

gcloud compute instances create "$PIPELINE_VM_NAME" \
  --project "$PIPELINE_GCP_PROJECT" --zone "$PIPELINE_VM_ZONE" \
  --machine-type "$PIPELINE_MACHINE_TYPE" \
  --boot-disk-size "${PIPELINE_DISK_GB}GB" --boot-disk-type pd-balanced \
  --image-family ubuntu-2404-lts-amd64 --image-project ubuntu-os-cloud \
  --service-account "$PIPELINE_SERVICE_ACCOUNT" --scopes cloud-platform \
  --metadata-from-file "startup-script=$PIPELINE_SCRIPT_DIR/pipeline_vm_startup.sh"

printf 'VM created in %s. Inspect startup logs before using it.\n' "$PIPELINE_VM_ZONE"
printf 'gcloud compute ssh %q --project %q --zone %q\n' \
  "$PIPELINE_VM_NAME" "$PIPELINE_GCP_PROJECT" "$PIPELINE_VM_ZONE"
printf 'Continue with docs/pipeline/release-procedure.md; no pipeline has been started.\n'

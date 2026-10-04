#!/usr/bin/env bash
# GCE startup metadata script; not executed during this task.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# A stable installer version already present on the development machine.
PIPELINE_UV_VERSION=0.6.14
PIPELINE_BOOTSTRAP=/opt/thereabouts-bootstrap

apt-get update
apt-get install -y git rsync python3-venv python3-pip ca-certificates poppler-utils build-essential pkg-config curl
python3 -m venv "$PIPELINE_BOOTSTRAP"
"$PIPELINE_BOOTSTRAP/bin/python" -m pip install "uv==$PIPELINE_UV_VERSION"
install -d -m 0755 /mnt/data /srv/thereabouts

cat > /etc/profile.d/thereabouts-pipeline.sh <<'EOF'
export PATH="/opt/thereabouts-bootstrap/bin:$PATH"
EOF

cat > /srv/thereabouts/SETUP_PENDING.txt <<'EOF'
Hardware and bootstrap tools are ready; no pipeline was run.
The owner must assign /srv/thereabouts and /mnt/data to the intended login user,
install the reviewed checkout and synchronize its locked dependencies.
Install the Rust toolchain required by the merged core/Cargo.toml before building
the client extension (the inspected branch requires Rust 1.99).
Check pdftotext against config/sources/plates.yaml: the distribution's package
may not match the pinned 25.11.0 extractor. Install that exact extractor before
rebuilding plate evidence. The apt package is not a reproducibility guarantee.
The Rust writer merge/coalesced-input proof and an s3fs dependency lock are also
required before pack construction or cloud publication.
Follow docs/pipeline/release-procedure.md in the reviewed checkout.
EOF

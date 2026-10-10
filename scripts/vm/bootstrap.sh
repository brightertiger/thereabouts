#!/usr/bin/env bash
# Prepares the pipeline VM after its startup script: directories, swap, Rust, Node, wasm-bindgen, pdftotext.
# Run on the VM as the ssh login user (needs sudo); re-running skips every step that is already done.
set -euo pipefail

PIPELINE_RUST_TOOLCHAIN=1.99
PIPELINE_WASM_BINDGEN=0.2.129
PIPELINE_NODE_VERSION=22.23.3
PIPELINE_NODE_SHA256=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de
PIPELINE_POPPLER_VERSION=25.11.0
# Release tarball signed by key CA262C6C83DE4D2FB28A332A3A6A4DB839EAA6D7; this hash was recorded on first download.
PIPELINE_POPPLER_SHA256=63f155142b77349e2bccaef148e754e7506ab1641e713b83af4f54a8f8b15369
PIPELINE_PYTHON_VERSION=3.12.8
PIPELINE_SWAP_GB=16
PIPELINE_USER="$(id -un)"
PIPELINE_BUILD_DIR="${PIPELINE_BUILD_DIR:-$HOME/build}"

step() { printf '\n== %s\n' "$*"; }

export DEBIAN_FRONTEND=noninteractive
export PATH="/opt/thereabouts-bootstrap/bin:/opt/node22/bin:$HOME/.cargo/bin:$PATH"

step "wait for the startup script"
for _ in $(seq 1 120); do
  [[ -f /srv/thereabouts/SETUP_PENDING.txt && -x /opt/thereabouts-bootstrap/bin/uv ]] && break
  sleep 10
done
[[ -x /opt/thereabouts-bootstrap/bin/uv ]] || { echo "startup script did not finish" >&2; exit 1; }
df -h /

step "working directories"
sudo install -d -o "$PIPELINE_USER" -g "$(id -gn)" -m 0755 /mnt/data /srv/thereabouts

step "swap file (${PIPELINE_SWAP_GB} GB)"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  if [[ ! -f /swapfile ]]; then
    sudo fallocate -l "${PIPELINE_SWAP_GB}G" /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
  fi
  sudo swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
swapon --show

step "apt packages: tmux, python3-yaml for seed_mirror.py, the poppler build"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  cmake ninja-build tmux xz-utils poppler-data python3-yaml \
  libfreetype-dev libfontconfig1-dev libjpeg-dev libpng-dev libtiff-dev \
  liblcms2-dev libopenjp2-7-dev zlib1g-dev

step "keep tmux jobs alive when no ssh session is open"
# tmux 3.4 puts every pane in a systemd --user scope; without lingering the user
# manager stops at the last logout and kills them (lost a world build on 2026-10-10).
sudo loginctl enable-linger "$USER"

step "rustup, toolchain ${PIPELINE_RUST_TOOLCHAIN}, wasm32 target"
if [[ ! -x "$HOME/.cargo/bin/rustup" ]]; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs |
    sh -s -- -y --profile minimal --default-toolchain none
fi
rustup toolchain install "$PIPELINE_RUST_TOOLCHAIN" --profile minimal
rustup default "$PIPELINE_RUST_TOOLCHAIN"
rustup target add wasm32-unknown-unknown --toolchain "$PIPELINE_RUST_TOOLCHAIN"

step "Node ${PIPELINE_NODE_VERSION} in /opt/node22"
if [[ "$(/opt/node22/bin/node --version 2>/dev/null || true)" != "v${PIPELINE_NODE_VERSION}" ]]; then
  node_work="$(mktemp -d)"
  node_archive="node-v${PIPELINE_NODE_VERSION}-linux-x64.tar.xz"
  curl -fsSL -o "$node_work/$node_archive" "https://nodejs.org/dist/v${PIPELINE_NODE_VERSION}/$node_archive"
  echo "${PIPELINE_NODE_SHA256}  $node_work/$node_archive" | sha256sum -c -
  sudo rm -rf /opt/node22
  sudo install -d -m 0755 /opt/node22
  sudo tar -xJf "$node_work/$node_archive" -C /opt/node22 --strip-components=1
  rm -rf "$node_work"
fi
sudo tee /etc/profile.d/thereabouts-tools.sh >/dev/null <<'EOF'
export PATH="/opt/node22/bin:$PATH"
[ -d "$HOME/.cargo/bin" ] && export PATH="$HOME/.cargo/bin:$PATH"
EOF
node --version
npm --version

step "wasm-bindgen-cli ${PIPELINE_WASM_BINDGEN}"
if ! wasm-bindgen --version 2>/dev/null | grep -qx "wasm-bindgen ${PIPELINE_WASM_BINDGEN}"; then
  cargo install --locked wasm-bindgen-cli --version "$PIPELINE_WASM_BINDGEN"
fi
wasm-bindgen --version

step "pdftotext ${PIPELINE_POPPLER_VERSION} from source"
wanted="pdftotext version ${PIPELINE_POPPLER_VERSION}"
if [[ "$(/usr/local/bin/pdftotext -v 2>&1 | sed -n 1p || true)" != "$wanted" ]]; then
  mkdir -p "$PIPELINE_BUILD_DIR"
  poppler_archive="poppler-${PIPELINE_POPPLER_VERSION}.tar.xz"
  curl -fsSL -o "$PIPELINE_BUILD_DIR/$poppler_archive" "https://poppler.freedesktop.org/$poppler_archive"
  echo "${PIPELINE_POPPLER_SHA256}  $PIPELINE_BUILD_DIR/$poppler_archive" | sha256sum -c -
  rm -rf "$PIPELINE_BUILD_DIR/poppler-${PIPELINE_POPPLER_VERSION}" "$PIPELINE_BUILD_DIR/poppler-build"
  tar -xJf "$PIPELINE_BUILD_DIR/$poppler_archive" -C "$PIPELINE_BUILD_DIR"
  cmake -S "$PIPELINE_BUILD_DIR/poppler-${PIPELINE_POPPLER_VERSION}" -B "$PIPELINE_BUILD_DIR/poppler-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=release -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DPOPPLER_DATADIR=/usr/share/poppler \
    -DENABLE_UTILS=ON -DENABLE_LIBOPENJPEG=openjpeg2 -DENABLE_DCTDECODER=libjpeg \
    -DENABLE_LCMS=ON -DENABLE_LIBTIFF=ON \
    -DENABLE_QT5=OFF -DENABLE_QT6=OFF -DENABLE_GLIB=OFF -DENABLE_GOBJECT_INTROSPECTION=OFF \
    -DENABLE_CPP=OFF -DENABLE_NSS3=OFF -DENABLE_GPGME=OFF -DENABLE_LIBCURL=OFF -DENABLE_BOOST=OFF \
    -DBUILD_GTK_TESTS=OFF -DBUILD_QT5_TESTS=OFF -DBUILD_QT6_TESTS=OFF \
    -DBUILD_CPP_TESTS=OFF -DBUILD_MANUAL_TESTS=OFF
  ninja -C "$PIPELINE_BUILD_DIR/poppler-build"
  sudo ninja -C "$PIPELINE_BUILD_DIR/poppler-build" install
  sudo ldconfig
fi
actual="$(pdftotext -v 2>&1 | sed -n 1p)"
[[ "$actual" == "$wanted" ]] || { echo "pdftotext prints '$actual', expected '$wanted'" >&2; exit 1; }
command -v pdftotext

step "Python ${PIPELINE_PYTHON_VERSION} for uv"
uv python install "$PIPELINE_PYTHON_VERSION"

step "versions"
{
  date -u +%Y-%m-%dT%H:%M:%SZ
  uv --version
  rustc --version
  cargo --version
  rustup target list --installed
  node --version
  npm --version
  wasm-bindgen --version
  pdftotext -v 2>&1 | sed -n 1p
  git --version
} | tee /srv/thereabouts/BOOTSTRAP_DONE.txt
df -h /

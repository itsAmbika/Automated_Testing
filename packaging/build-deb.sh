#!/bin/bash
#
# build-deb.sh — build the jiopc-agent .deb package from source.
# Run from the repository root.
#
# Output: packaging/out/jiopc-agent_<version>_all.deb

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGING="$REPO_ROOT/packaging/debian"
OUT_DIR="$REPO_ROOT/packaging/out"
VERSION="1.0.0"

echo "[build-deb] Repository root: $REPO_ROOT"
echo "[build-deb] Staging tree:    $STAGING"

# --- Copy source into the staging /opt/jiopc-agent/ ---
INSTALL_DIR="$STAGING/opt/jiopc-agent"
mkdir -p "$INSTALL_DIR"

# Clean any leftover source from a previous build (but keep the DEBIAN/,
# usr/, opt/ scaffolding intact).
rm -rf "$INSTALL_DIR"/{jiopc_agent.py,analyse.py,src,configs,prompts}

# Copy the agent source
cp "$REPO_ROOT/jiopc_agent.py"  "$INSTALL_DIR/"
cp "$REPO_ROOT/analyse.py"      "$INSTALL_DIR/"
cp -r "$REPO_ROOT/src"          "$INSTALL_DIR/"
cp -r "$REPO_ROOT/configs"      "$INSTALL_DIR/"
cp -r "$REPO_ROOT/prompts"      "$INSTALL_DIR/"

# --- Fix permissions on package-metadata scripts ---
chmod 755 "$STAGING/DEBIAN/postinst"
chmod 755 "$STAGING/usr/bin/jiopc-agent"

# --- Build the .deb ---
mkdir -p "$OUT_DIR"
OUT_FILE="$OUT_DIR/jiopc-agent_${VERSION}_all.deb"

echo "[build-deb] Building .deb ..."
dpkg-deb --root-owner-group --build "$STAGING" "$OUT_FILE"

echo "[build-deb] Built: $OUT_FILE"
echo "[build-deb] Verify with: dpkg-deb -I $OUT_FILE"

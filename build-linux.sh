#!/usr/bin/env bash
set -euo pipefail

# Build the Atlas Chat Linux desktop bundle (.deb / .AppImage) via Tauri.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$ROOT_DIR/atlas-rust-desktop"

if [[ ! -d "$DESKTOP_DIR" ]]; then
    echo "ERROR: atlas-rust-desktop directory not found at $DESKTOP_DIR" >&2
    exit 1
fi

echo "=== 1. Check Python backend bundle ==="
python3 "$ROOT_DIR/check-bundle.py"

echo "=== 2. Install & build frontend (atlas-rust-desktop) ==="
cd "$DESKTOP_DIR"
npm install
npm run build

echo "=== 3. Build Linux Tauri bundle (.deb / .AppImage) ==="
npx tauri build

BUNDLE_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle"
echo "=== Build complete ==="
if [[ -d "$BUNDLE_DIR" ]]; then
    find "$BUNDLE_DIR" -maxdepth 3 \( -name "*.deb" -o -name "*.AppImage" \) -print
fi

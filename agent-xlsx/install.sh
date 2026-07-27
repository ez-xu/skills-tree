#!/usr/bin/env bash
# Download the latest agent-xlsx release for the current platform.
#
# Usage: ./install.sh [INSTALL_DIR]
#   INSTALL_DIR defaults to the directory this script lives in, so the
#   binary lands next to SKILL.md as `./agent-xlsx`.
#
# Supported targets:
#   - aarch64-apple-darwin       (Apple Silicon Mac)
#   - x86_64-unknown-linux-gnu   (x86_64 Linux)
#   - x86_64-pc-windows-msvc     (x86_64 Windows, requires unzip)
set -euo pipefail

REPO="carderne/agent-xlsx"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${1:-$SCRIPT_DIR}"

# Detect the target triple for the host. Fail loudly on unsupported combos
# rather than silently downloading the wrong build.
uname_s="$(uname -s)"
uname_m="$(uname -m)"
case "$uname_s-$uname_m" in
    Darwin-arm64)   target="aarch64-apple-darwin"; ext="tar.gz" ;;
    Linux-x86_64)   target="x86_64-unknown-linux-gnu"; ext="tar.gz" ;;
    MINGW*-*|MSYS*-*|CYGWIN*-*)
                    target="x86_64-pc-windows-msvc"; ext="zip" ;;
    *)              echo "unsupported platform: $uname_s $uname_m" >&2; exit 1 ;;
esac

# Resolve the latest release tag via the GitHub API (unauthenticated; public
# repo). We use the `tag_name` field so we don't need jq.
tag="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)"
if [ -z "$tag" ]; then
    echo "failed to resolve latest release tag" >&2
    exit 1
fi
version="${tag#v}"

asset="agent-xlsx-${version}-${target}.${ext}"
url="https://github.com/$REPO/releases/download/${tag}/${asset}"

echo "installing agent-xlsx $tag for $target" >&2
echo "  → $INSTALL_DIR" >&2

mkdir -p "$INSTALL_DIR"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL "$url" -o "$tmp/$asset"

case "$ext" in
    tar.gz) tar -xzf "$tmp/$asset" -C "$tmp" ;;
    zip)    unzip -q "$tmp/$asset" -d "$tmp" ;;
esac

# Release archives contain a single binary at the top level; locate it
# without caring about the exact wrapper-dir layout.
bin="$(find "$tmp" -type f -name 'agent-xlsx' -o -name 'agent-xlsx.exe' | head -n1)"
if [ -z "$bin" ]; then
    echo "binary not found in archive $asset" >&2
    exit 1
fi
install -m 0755 "$bin" "$INSTALL_DIR/$(basename "$bin")"

echo "installed $INSTALL_DIR/$(basename "$bin")" >&2
"$INSTALL_DIR/$(basename "$bin")" --help >/dev/null

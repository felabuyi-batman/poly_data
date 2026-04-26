#!/bin/bash
# Clone the three external repos into vendor/.
# Run once before bot/run.sh.

set -e
cd "$(dirname "$0")/.."
mkdir -p vendor
cd vendor

clone_or_pull() {
  local url=$1; local dir=$2
  if [ -d "$dir/.git" ]; then
    echo "[vendor] updating $dir"
    git -C "$dir" pull --ff-only || true
  else
    echo "[vendor] cloning $url"
    git clone --depth 1 "$url" "$dir" || echo "[vendor] WARN: clone of $url failed (skipping)"
  fi
}

clone_or_pull https://github.com/Polymarket/polymarket-cli           polymarket-cli
clone_or_pull https://github.com/Polymarket/agents                   polymarket-agents
clone_or_pull https://github.com/dylanpersonguy/Polymarket-Trading-Bot polymarket-trading-bot

echo
echo "[vendor] done. Next steps:"
echo "  1. Build the CLI:   cd vendor/polymarket-cli && cargo install --path ."
echo "     (or: brew tap Polymarket/polymarket-cli && brew install polymarket)"
echo "  2. The Polymarket/agents framework is imported via PYTHONPATH at runtime."

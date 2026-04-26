#!/bin/bash
# Bot startup — runs the full pipeline once, in order.
# For 24/7 operation, schedule with cron or systemd.
#
# Pre-req (one-time):
#   bash bot/setup_vendor.sh          # clones the 3 external repos
#   cd vendor/polymarket-cli && cargo install --path .   # or: brew install polymarket
#   pip install -r vendor/polymarket-agents/requirements.txt   # for the agents framework

set -e
cd "$(dirname "$0")/.."

# Make Polymarket/agents importable if cloned.
export PYTHONPATH="$PWD/vendor/polymarket-agents:${PYTHONPATH:-}"

# 1. refresh trade + market data (warproxxx/poly_data)
uv run python -c \
  "from update_utils.process_live import process_live; process_live()"

# 2. rebuild target wallet list
uv run python -m bot.targets

# 3. scan markets via polymarket-cli / Polymarket-agents → queue.json
uv run python -m bot.scanner

# 4. brain: 4 checks (Claude API) + Kelly → theses.json
uv run python -m bot.brain

# 5. executor: 3 strategies + consensus → positions.json
uv run python -m bot.executor

# 6. exit monitor: target / volume / stale triggers
uv run python -m bot.exit_monitor

echo "$(date -u +%FT%TZ) — bot cycle complete" >> bot/state/log.txt

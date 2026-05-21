#!/bin/bash
# Bot startup — runs the full ENTRY pipeline once, in order.
# Exit monitor is split into bot/run_exit.sh so it can run at a faster cadence.
#
# Recommended cron:
#   */15 * * * *  cd /srv/poly_data && bash bot/run.sh      >> bot/state/cron.log 2>&1
#   */5  * * * *  cd /srv/poly_data && bash bot/run_exit.sh >> bot/state/cron.log 2>&1
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

# 4. brain: 4 checks (LLM) + Kelly → theses.json
uv run python -m bot.brain

# 5. executor: 3 strategies + consensus → positions.json
#    (no-ops if bot/state/HALT exists)
uv run python -m bot.executor

echo "$(date -u +%FT%TZ) — bot entry cycle complete" >> bot/state/cron.log

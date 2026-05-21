#!/bin/bash
# Exit monitor only — runs the 3 exit triggers against open positions.
# Designed for a faster cadence than the entry pipeline (every 5 min).
#
# IMPORTANT: This script intentionally does NOT honor bot/state/HALT.
# HALT stops new entries (executor). Existing positions must still be
# managed so they can be closed cleanly — that's the whole point of a
# kill switch.

set -e
cd "$(dirname "$0")/.."

export PYTHONPATH="$PWD/vendor/polymarket-agents:${PYTHONPATH:-}"

uv run python -m bot.exit_monitor

echo "$(date -u +%FT%TZ) — exit monitor cycle complete" >> bot/state/cron.log

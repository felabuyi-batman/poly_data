"""Configuration for the trading bot.

Reads from environment variables. Copy `.env.example` to `.env` and fill in.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = Path(__file__).resolve().parent
STATE_DIR = BOT_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)

# Files
TRADES_CSV = REPO_ROOT / "processed" / "trades.csv"
MARKETS_CSV = REPO_ROOT / "markets.csv"
TARGETS_JSON = STATE_DIR / "targets.json"
QUEUE_JSON = STATE_DIR / "queue.json"
THESES_JSON = STATE_DIR / "theses.json"
POSITIONS_JSON = STATE_DIR / "positions.json"
MARKETS_JSON = STATE_DIR / "markets.json"

# Targets analyzer thresholds
TARGETS_MIN_TRADES = int(os.getenv("TARGETS_MIN_TRADES", "100"))
TARGETS_MIN_WIN_RATE = float(os.getenv("TARGETS_MIN_WIN_RATE", "0.70"))
TARGETS_TOP_N = int(os.getenv("TARGETS_TOP_N", "50"))

# Scanner thresholds
SCAN_MIN_GAP = float(os.getenv("SCAN_MIN_GAP", "0.07"))
SCAN_MIN_DEPTH_USD = float(os.getenv("SCAN_MIN_DEPTH_USD", "500"))
SCAN_MIN_HOURS = float(os.getenv("SCAN_MIN_HOURS", "4"))
SCAN_MAX_HOURS = float(os.getenv("SCAN_MAX_HOURS", "168"))
# Per the article's "what didn't work" notes: sports markets win-rated 52% and
# were killed. Comma-separated, case-insensitive substring match on category.
SCAN_CATEGORY_BLACKLIST = [
    c.strip().lower()
    for c in os.getenv("SCAN_CATEGORY_BLACKLIST", "sports").split(",")
    if c.strip()
]

# Brain
BRAIN_MIN_CONFIDENCE = float(os.getenv("BRAIN_MIN_CONFIDENCE", "0.75"))
BRAIN_MIN_CHECKS_AGREEING = int(os.getenv("BRAIN_MIN_CHECKS_AGREEING", "3"))
KELLY_MAX_FRACTION = float(os.getenv("KELLY_MAX_FRACTION", "0.25"))

# Execution
BANKROLL_USD = float(os.getenv("BANKROLL_USD", "200"))
WHALE_COPY_DELAY_SEC = int(os.getenv("WHALE_COPY_DELAY_SEC", "60"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

# Exit
EXIT_TARGET_PCT = float(os.getenv("EXIT_TARGET_PCT", "0.85"))
EXIT_VOLUME_SPIKE_MULT = float(os.getenv("EXIT_VOLUME_SPIKE_MULT", "3.0"))
EXIT_STALE_HOURS = float(os.getenv("EXIT_STALE_HOURS", "24"))
EXIT_STALE_MAX_MOVE = float(os.getenv("EXIT_STALE_MAX_MOVE", "0.02"))

# Polymarket CLI
POLYMARKET_CLI = os.getenv("POLYMARKET_CLI", "polymarket")

# OpenAI (used for news, disposition, and probability estimate checks)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
LLM_CACHE_TTL_SEC = int(os.getenv("LLM_CACHE_TTL_SEC", "1800"))  # 30 min

# Categories to copy whales on (per "what survived" notes)
WHALE_COPY_CATEGORIES = [
    c.strip().lower()
    for c in os.getenv("WHALE_COPY_CATEGORIES", "crypto").split(",")
    if c.strip()
]

# Minimum market depth (notional) — the article cites $50k after iteration
MIN_MARKET_VOLUME_USD = float(os.getenv("MIN_MARKET_VOLUME_USD", "50000"))

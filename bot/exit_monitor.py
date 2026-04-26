"""Step 4 — exit monitor.

Three triggers (per the article):
  1. TARGET_HIT    — current price ≥ entry + 0.85 * expected move
  2. VOLUME_EXIT   — last-10-minute notional volume > 3 * trailing average
  3. STALE_THESIS  — open >24h with <2c price movement

Volume comes from the CLOB `/trades` endpoint (real fills, not the
price-history proxy). We sum USDC notional in the last 10 minutes vs the
trailing 60 minutes (averaged into 10-min buckets).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

import requests

from bot.config import (
    EXIT_STALE_HOURS,
    EXIT_STALE_MAX_MOVE,
    EXIT_TARGET_PCT,
    EXIT_VOLUME_SPIKE_MULT,
    POSITIONS_JSON,
)
from bot.state import state_lock

CLOB = "https://clob.polymarket.com"


def _midpoint(token_id: str) -> float | None:
    try:
        r = requests.get(f"{CLOB}/midpoint", params={"token_id": token_id}, timeout=10)
        return float(r.json()["mid"]) if r.status_code == 200 else None
    except Exception:
        return None


def _trades_window(token_id: str, minutes: int = 10) -> tuple[float, float]:
    """Return (last-window notional, trailing avg notional per window) for the
    last hour split into 10-min buckets. (0,0) on failure → no spike."""
    try:
        r = requests.get(
            f"{CLOB}/data/trades",
            params={"market": token_id, "limit": 500},
            timeout=10,
        )
        if r.status_code != 200:
            return 0.0, 0.0
        trades = r.json() or []
    except Exception:
        return 0.0, 0.0
    if not isinstance(trades, list) or not trades:
        return 0.0, 0.0

    now = time.time()
    window_s = minutes * 60
    last = 0.0
    prior_buckets: list[float] = [0.0] * 6  # 60 minutes / 10
    for t in trades:
        try:
            ts = float(t.get("match_time") or t.get("timestamp") or 0)
            notional = float(t.get("price", 0)) * float(t.get("size", 0))
        except (TypeError, ValueError):
            continue
        age = now - ts
        if age < 0 or age > 6 * window_s:
            continue
        bucket = int(age // window_s)
        if bucket == 0:
            last += notional
        elif 1 <= bucket < 6:
            prior_buckets[bucket] += notional
    avg_prior = sum(prior_buckets[1:]) / 5 if prior_buckets[1:] else 0.0
    return last, avg_prior


def exit_check(pos: dict, current: float, vol_window: float, vol_avg: float) -> str | None:
    entry = pos["entry_price"]
    target = pos["target_price"]
    expected = target - entry if pos["side"] == "BUY_YES" else entry - target

    if pos["side"] == "BUY_YES":
        if current >= entry + expected * EXIT_TARGET_PCT:
            return "TARGET_HIT"
    else:
        if current <= entry - expected * EXIT_TARGET_PCT:
            return "TARGET_HIT"

    if vol_avg > 0 and vol_window > vol_avg * EXIT_VOLUME_SPIKE_MULT:
        return "VOLUME_EXIT"

    opened = datetime.fromisoformat(pos["opened_at"])
    hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
    if hours > EXIT_STALE_HOURS and abs(current - entry) < EXIT_STALE_MAX_MOVE:
        return "STALE_THESIS"
    return None


def main() -> None:
    if not POSITIONS_JSON.exists():
        print(f"[exit] {POSITIONS_JSON} not found", file=sys.stderr)
        return

    with state_lock():
        positions: list[dict[str, Any]] = json.loads(POSITIONS_JSON.read_text())
        changed = False
        for pos in positions:
            if pos.get("status") != "OPEN":
                continue
            order = pos.get("order") or {}
            token = order.get("token")
            if not token:
                continue
            current = _midpoint(token)
            if current is None:
                continue
            if pos["side"] == "BUY_NO":
                current = 1 - current
            vol_window, vol_avg = _trades_window(token)
            reason = exit_check(pos, current, vol_window, vol_avg)
            if reason:
                pos["status"] = "CLOSED"
                pos["exit_reason"] = reason
                pos["exit_price"] = round(current, 4)
                pos["closed_at"] = datetime.now(timezone.utc).isoformat()
                shares = order.get("size_shares", 0)
                pos["realized_pnl"] = round(
                    shares * (current - order.get("price", current)), 2
                )
                changed = True
                print(f"[exit] {reason} {pos['question'][:60]}… "
                      f"@ {current:.3f}  pnl=${pos['realized_pnl']}")
            time.sleep(0.2)
        if changed:
            POSITIONS_JSON.write_text(json.dumps(positions, indent=2))


if __name__ == "__main__":
    main()

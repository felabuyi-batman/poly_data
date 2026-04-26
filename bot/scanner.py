"""Step 1 — scan all live markets and filter to a tradeable queue.

Three integration layers, in order of preference:

  1. `Polymarket/agents` GammaMarketClient (when vendor/polymarket-agents present)
  2. `polymarket` Rust CLI via subprocess (when binary on PATH)
  3. Direct HTTP to gamma-api.polymarket.com / clob.polymarket.com

The probability estimate used to compute the price-vs-truth gap is produced
by `bot.llm.estimate_probability` (OpenAI). If no key is set the gap filter
is skipped and we keep the market — the brain stage will re-score later.

Output: bot/state/queue.json.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

from bot import polycli
from bot.agents_adapter import gamma_client, have_agents_framework
from bot.config import (
    MIN_MARKET_VOLUME_USD,
    QUEUE_JSON,
    SCAN_MAX_HOURS,
    SCAN_MIN_DEPTH_USD,
    SCAN_MIN_GAP,
    SCAN_MIN_HOURS,
)
from bot.llm import estimate_probability
from bot.state import state_lock


def fetch_active_markets(limit: int = 500) -> list[dict[str, Any]]:
    if have_agents_framework():
        gc = gamma_client()
        try:
            print("[scanner] using Polymarket/agents GammaMarketClient", file=sys.stderr)
            return gc.get_current_markets(limit=limit)
        except Exception as e:  # noqa: BLE001
            print(f"[scanner] agents framework error, falling back: {e}", file=sys.stderr)
    return polycli.list_markets(limit=limit)


def hours_until(end_iso: str | None) -> float | None:
    if not end_iso:
        return None
    try:
        end = datetime.fromisoformat(str(end_iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (end - datetime.now(timezone.utc)).total_seconds() / 3600.0


def _token_ids(market: dict[str, Any]) -> list[str]:
    raw = market.get("clobTokenIds") or market.get("tokens") or []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return []
    return list(raw)


def score_market(market: dict, estimate: float | None, midpoint: float,
                 bid: float, ask: float, hours: float | None) -> dict | None:
    if hours is None or hours < SCAN_MIN_HOURS or hours > SCAN_MAX_HOURS:
        return None
    if min(bid, ask) < SCAN_MIN_DEPTH_USD:
        return None
    gap = abs(estimate - midpoint) if estimate is not None else None
    # If we have a real estimate, enforce the gap threshold; otherwise let the
    # market through and let the brain re-score it.
    if gap is not None and gap < SCAN_MIN_GAP:
        return None
    return {
        "market_id": market.get("id"),
        "condition_id": market.get("conditionId") or market.get("condition_id"),
        "question": market.get("question"),
        "slug": market.get("slug") or market.get("market_slug"),
        "category": (market.get("category") or "").lower(),
        "midpoint": midpoint,
        "estimate": estimate,
        "gap": round(gap, 4) if gap is not None else None,
        "bid_depth": round(bid, 2),
        "ask_depth": round(ask, 2),
        "hours": round(hours, 2),
        "volume": float(market.get("volume") or market.get("volumeNum") or 0),
    }


def scan() -> list[dict]:
    markets = fetch_active_markets(limit=500)
    print(f"[scanner] fetched {len(markets)} active markets", file=sys.stderr)
    survivors: list[dict] = []
    for m in markets:
        vol = float(m.get("volume") or m.get("volumeNum") or 0)
        if vol < MIN_MARKET_VOLUME_USD:
            continue
        tokens = _token_ids(m)
        if not tokens:
            continue
        yes_token = tokens[0]
        mid = polycli.midpoint(yes_token)
        if mid is None:
            continue
        bid, ask = polycli.book_depth(yes_token)
        if min(bid, ask) < SCAN_MIN_DEPTH_USD:
            continue  # cheap pre-filter before paying for an LLM call
        end = m.get("endDate") or m.get("end_date_iso") or m.get("endDateIso")
        hours = hours_until(end)
        if hours is None or hours < SCAN_MIN_HOURS or hours > SCAN_MAX_HOURS:
            continue

        estimate = estimate_probability(m.get("question") or "", mid, hours)
        scored = score_market(m, estimate, mid, bid, ask, hours)
        if scored is None:
            continue
        scored["yes_token"] = yes_token
        scored["no_token"] = tokens[1] if len(tokens) > 1 else None
        survivors.append(scored)
        time.sleep(0.05)

    survivors.sort(key=lambda x: x["bid_depth"] + x["ask_depth"], reverse=True)
    return survivors


def main() -> None:
    with state_lock():
        survivors = scan()
        QUEUE_JSON.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_JSON.write_text(json.dumps(survivors, indent=2))
    print(f"[scanner] {len(survivors)} markets passed filters → {QUEUE_JSON}")


if __name__ == "__main__":
    main()

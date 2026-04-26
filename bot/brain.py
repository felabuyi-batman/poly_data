"""Step 2 — for each queued market run 4 checks (base rate, news, whale,
disposition), then size with quarter-Kelly. Outputs theses.json.
"""
from __future__ import annotations

import json
import sys
from typing import Any

import polars as pl

from bot.config import (
    BANKROLL_USD,
    BRAIN_MIN_CHECKS_AGREEING,
    BRAIN_MIN_CONFIDENCE,
    OPENAI_API_KEY,
    QUEUE_JSON,
    TARGETS_JSON,
    THESES_JSON,
    TRADES_CSV,
)
from bot.llm import disposition_signal, news_signal
from bot.sizing import kelly_size
from bot.state import state_lock


# --- check 1: base-rate / mean reversion from poly_data ----------------------

def base_rate_check(market: dict, trades: pl.DataFrame | None) -> dict:
    if trades is None or trades.height == 0:
        return {"signal": "NEUTRAL", "confidence": 0.5, "note": "no historical data"}
    mid = market["midpoint"]
    market_trades = trades.filter(pl.col("market_id") == market["market_id"])
    if market_trades.height < 10:
        return {"signal": "NEUTRAL", "confidence": 0.5, "note": "too few prior trades"}
    mean_price = float(market_trades["price"].mean() or mid)
    delta = mean_price - mid
    if abs(delta) < 0.05:
        return {"signal": "NEUTRAL", "confidence": 0.5,
                "note": f"mean={mean_price:.2f} mid={mid:.2f}"}
    return {
        "signal": "BUY_YES" if delta > 0 else "BUY_NO",
        "confidence": min(0.5 + abs(delta), 0.85),
        "note": f"reverts toward mean={mean_price:.2f}",
    }


# --- check 2: news (OpenAI) --------------------------------------------------

def news_check(market: dict) -> dict:
    return news_signal(
        market.get("question") or "",
        float(market["midpoint"]),
        float(market.get("hours") or 0),
    )


# --- check 3: whale ----------------------------------------------------------

def whale_check(market: dict, target_wallets: set[str],
                trades: pl.DataFrame | None) -> dict:
    if trades is None or not target_wallets:
        return {"signal": "NEUTRAL", "confidence": 0.5, "note": "no targets/trades"}
    legs = trades.filter(pl.col("market_id") == market["market_id"])
    if legs.height == 0:
        return {"signal": "NEUTRAL", "confidence": 0.5, "note": "no whale activity"}
    targets_list = list(target_wallets)
    taker = legs.filter(pl.col("taker").is_in(targets_list)).select(
        pl.col("taker").alias("wallet"),
        pl.when(pl.col("taker_direction") == "BUY")
        .then(pl.col("token_amount"))
        .otherwise(-pl.col("token_amount"))
        .alias("net_tokens"),
    )
    maker = legs.filter(pl.col("maker").is_in(targets_list)).select(
        pl.col("maker").alias("wallet"),
        pl.when(pl.col("maker_direction") == "BUY")
        .then(pl.col("token_amount"))
        .otherwise(-pl.col("token_amount"))
        .alias("net_tokens"),
    )
    by_wallet = (
        pl.concat([taker, maker], how="vertical_relaxed")
        .group_by("wallet")
        .agg(pl.col("net_tokens").sum())
    )
    long_n = by_wallet.filter(pl.col("net_tokens") > 0).height
    short_n = by_wallet.filter(pl.col("net_tokens") < 0).height
    if long_n >= 3 and long_n > short_n:
        return {"signal": "BUY_YES",
                "confidence": min(0.6 + 0.05 * long_n, 0.95),
                "note": f"{long_n} target wallets long"}
    if short_n >= 3 and short_n > long_n:
        return {"signal": "BUY_NO",
                "confidence": min(0.6 + 0.05 * short_n, 0.95),
                "note": f"{short_n} target wallets short"}
    return {"signal": "NEUTRAL", "confidence": 0.5,
            "note": f"long={long_n} short={short_n}"}


# --- check 4: disposition (OpenAI) ------------------------------------------

def disposition_check(market: dict) -> dict:
    return disposition_signal(market.get("question") or "", float(market["midpoint"]))


# --- aggregate ---------------------------------------------------------------

def synthesize(checks: list[dict], midpoint: float) -> dict:
    sides = [c["signal"] for c in checks if c["signal"] != "NEUTRAL"]
    if not sides:
        return {"action": "PASS", "reason": "all neutral"}
    side = max(set(sides), key=sides.count)
    agreeing = [c for c in checks if c["signal"] == side]
    if len(agreeing) < BRAIN_MIN_CHECKS_AGREEING:
        return {"action": "PASS", "reason": f"only {len(agreeing)}/4 agree"}
    confidence = sum(c["confidence"] for c in agreeing) / len(agreeing)
    if confidence < BRAIN_MIN_CONFIDENCE:
        return {"action": "PASS",
                "reason": f"confidence {confidence:.2f} < {BRAIN_MIN_CONFIDENCE}"}
    price = midpoint if side == "BUY_YES" else 1 - midpoint
    return {
        "action": side,
        "confidence": round(confidence, 3),
        "p_win": round(confidence, 3),
        "price_at_decision": round(price, 4),
        "agreeing_checks": [c["note"] for c in agreeing],
    }


def _load_trades_lazy() -> pl.DataFrame | None:
    if not TRADES_CSV.exists():
        return None
    try:
        return pl.read_csv(
            TRADES_CSV,
            columns=[
                "timestamp", "market_id", "maker", "taker",
                "taker_direction", "maker_direction",
                "price", "usd_amount", "token_amount",
            ],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[brain] could not load trades: {e}", file=sys.stderr)
        return None


def main() -> None:
    if not QUEUE_JSON.exists():
        print(f"[brain] {QUEUE_JSON} not found — run scanner first", file=sys.stderr)
        sys.exit(1)
    if not OPENAI_API_KEY:
        print("[brain] WARNING: OPENAI_API_KEY unset — news/disposition/estimate "
              "checks will be neutral", file=sys.stderr)

    with state_lock():
        queue = json.loads(QUEUE_JSON.read_text())
        targets = json.loads(TARGETS_JSON.read_text()) if TARGETS_JSON.exists() else []
        target_wallets = {t["wallet"] for t in targets}
        trades = _load_trades_lazy()

        theses: list[dict[str, Any]] = []
        for market in queue:
            checks = [
                base_rate_check(market, trades),
                news_check(market),
                whale_check(market, target_wallets, trades),
                disposition_check(market),
            ]
            decision = synthesize(checks, market["midpoint"])
            if decision["action"] == "PASS":
                continue
            size = kelly_size(decision["p_win"], decision["price_at_decision"],
                              BANKROLL_USD)
            if size <= 0:
                continue
            theses.append({
                "market_id": market["market_id"],
                "question": market["question"],
                "yes_token": market.get("yes_token"),
                "no_token": market.get("no_token"),
                "category": market.get("category"),
                "midpoint": market["midpoint"],
                "decision": decision,
                "size_usd": size,
                "checks": checks,
            })

        THESES_JSON.parent.mkdir(parents=True, exist_ok=True)
        THESES_JSON.write_text(json.dumps(theses, indent=2))
    print(f"[brain] generated {len(theses)} theses → {THESES_JSON}")


if __name__ == "__main__":
    main()

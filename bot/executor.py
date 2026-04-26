"""Step 3 — strategies vote, consensus decides, order is placed.

Order placement preference:
  1. Polymarket/agents Polymarket class (vendor/polymarket-agents)
  2. polymarket Rust CLI
  3. paper trade (DRY_RUN=true or no credentials)

Idempotency: each thesis gets a stable client_id (sha256 of market_id+side);
we never place two orders for the same client_id within a run.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any

from bot import polycli
from bot.agents_adapter import Polymarket as AgentsPolymarket
from bot.sizing import kelly_size
from bot.config import (
    DRY_RUN,
    POSITIONS_JSON,
    THESES_JSON,
)
from bot.state import state_lock, usable_bankroll
from bot.strategies import ALL as STRATEGIES


def _client_id(market_id: str, side: str) -> str:
    return hashlib.sha256(f"{market_id}:{side}".encode()).hexdigest()[:16]


def consensus(votes: list[dict]) -> tuple[str, float, float]:
    """Return (action, avg_confidence, size_multiplier).

    - 2+ agents agree on a side → full position (mult=1.0)
    - 1 agent only              → half position (mult=0.5)
    - none / disagree            → no trade
    """
    actionable = [v for v in votes if v["action"] in ("BUY_YES", "BUY_NO")]
    if not actionable:
        return "HOLD", 0.0, 0.0
    side = max({v["action"] for v in actionable},
               key=lambda s: sum(1 for v in actionable if v["action"] == s))
    agreeing = [v for v in actionable if v["action"] == side]
    avg_conf = sum(v["confidence"] for v in agreeing) / len(agreeing)
    if len(agreeing) >= 2:
        return side, avg_conf, 1.0
    return side, avg_conf, 0.5


def place_order(thesis: dict, side: str, size_usd: float, cid: str) -> dict:
    token = thesis["yes_token"] if side == "BUY_YES" else thesis["no_token"]
    if not token:
        return {"status": "error", "reason": "no token id", "client_id": cid}
    price = thesis["midpoint"] if side == "BUY_YES" else 1 - thesis["midpoint"]
    if not (0 < price < 1):
        return {"status": "error", "reason": f"invalid price {price}", "client_id": cid}
    shares = round(size_usd / price, 2)
    base = {"client_id": cid, "token": token, "price": round(price, 4),
            "size_usd": size_usd, "size_shares": shares, "side": "BUY"}

    if DRY_RUN:
        return {**base, "status": "paper"}

    if AgentsPolymarket is not None:
        try:
            pm = AgentsPolymarket()
            resp = pm.execute_market_order(token, size_usd)
            return {**base, "status": "live-agents", "response": resp}
        except Exception as e:  # noqa: BLE001
            print(f"[exec] agents order failed: {e}", file=sys.stderr)

    try:
        resp = polycli.create_order(token, "buy", price, shares)
        return {**base, "status": "live-cli", "response": resp}
    except Exception as e:  # noqa: BLE001
        return {**base, "status": "error", "reason": f"all order paths failed: {e}"}


def main() -> None:
    if not THESES_JSON.exists():
        print(f"[exec] {THESES_JSON} not found — run brain first", file=sys.stderr)
        sys.exit(1)

    with state_lock():
        theses = json.loads(THESES_JSON.read_text())
        positions: list[dict[str, Any]] = []
        if POSITIONS_JSON.exists():
            try:
                positions = json.loads(POSITIONS_JSON.read_text())
            except json.JSONDecodeError:
                positions = []

        held_cids = {p.get("order", {}).get("client_id") for p in positions}
        held_markets = {p["market_id"] for p in positions if p.get("status") == "OPEN"}

        for thesis in theses:
            if thesis["market_id"] in held_markets:
                continue
            votes = [agent(thesis) for agent in STRATEGIES]
            side, avg_conf, mult = consensus(votes)
            if side == "HOLD" or mult == 0:
                continue
            cid = _client_id(thesis["market_id"], side)
            if cid in held_cids:
                continue

            available = usable_bankroll(positions)
            full_size = kelly_size(avg_conf, thesis["midpoint"], available) * mult
            size = min(full_size, available)
            if size <= 0:
                continue

            order = place_order(thesis, side, size, cid)
            positions.append({
                "market_id": thesis["market_id"],
                "question": thesis["question"],
                "side": side,
                "entry_price": thesis["midpoint"],
                "target_price": (
                    min(0.99, thesis["midpoint"] + 0.30)
                    if side == "BUY_YES"
                    else max(0.01, (1 - thesis["midpoint"]) + 0.30)
                ),
                "size_usd": size,
                "votes": votes,
                "order": order,
                "status": "OPEN" if order["status"] != "error" else "FAILED",
                "opened_at": datetime.now(timezone.utc).isoformat(),
            })
            held_cids.add(cid)
            print(f"[exec] {side} {thesis['question'][:60]}… ${size:.2f} ({order['status']})")
            time.sleep(0.3)

        POSITIONS_JSON.parent.mkdir(parents=True, exist_ok=True)
        POSITIONS_JSON.write_text(json.dumps(positions, indent=2))
    open_n = len([p for p in positions if p["status"] == "OPEN"])
    print(f"[exec] {open_n} open positions")


if __name__ == "__main__":
    main()

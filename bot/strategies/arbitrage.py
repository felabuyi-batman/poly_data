"""Arbitrage strategy.

Vote BUY when the gap between Claude's estimated probability and the market
price exceeds the configured threshold (default 7c).
"""
from __future__ import annotations


def agent_arbitrage(thesis: dict) -> dict:
    d = thesis["decision"]
    side = d["action"]
    edge = abs(d["p_win"] - d["price_at_decision"])
    if edge >= 0.07:
        return {"agent": "arbitrage", "action": side, "confidence": d["p_win"],
                "note": f"edge={edge:.3f}"}
    return {"agent": "arbitrage", "action": "HOLD", "confidence": 0.0,
            "note": f"edge={edge:.3f} below 0.07"}

"""Whale-copy strategy.

Vote BUY when the whale check agrees AND the market falls into an allow-listed
category. Per the article's "what survived" rules we default to crypto-only.
"""
from __future__ import annotations

from bot.config import WHALE_COPY_CATEGORIES


def agent_whale_copy(thesis: dict) -> dict:
    d = thesis["decision"]
    side = d["action"]
    cat = (thesis.get("category") or "").lower()
    if WHALE_COPY_CATEGORIES and not any(c in cat for c in WHALE_COPY_CATEGORIES):
        return {"agent": "whale_copy", "action": "HOLD", "confidence": 0.0,
                "note": f"category {cat!r} not in allow-list"}
    whale = next(
        (c for c in thesis["checks"] if "target wallets" in c.get("note", "")),
        None,
    )
    if whale and whale["signal"] == side:
        return {"agent": "whale_copy", "action": side,
                "confidence": whale["confidence"], "note": whale["note"]}
    return {"agent": "whale_copy", "action": "HOLD", "confidence": 0.0,
            "note": "no whale agreement"}

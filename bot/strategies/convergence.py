"""Convergence strategy.

Vote BUY when at least one base/news/disposition check agrees with the chosen
side at >= 0.6 confidence — i.e. independent signals are converging.
"""
from __future__ import annotations


def agent_convergence(thesis: dict) -> dict:
    d = thesis["decision"]
    side = d["action"]
    matching = [
        c for c in thesis["checks"]
        if c["signal"] == side and c["confidence"] >= 0.6
    ]
    if matching:
        return {
            "agent": "convergence",
            "action": side,
            "confidence": max(c["confidence"] for c in matching),
            "note": f"{len(matching)} checks agree",
        }
    return {"agent": "convergence", "action": "HOLD", "confidence": 0.0,
            "note": "no converging checks"}

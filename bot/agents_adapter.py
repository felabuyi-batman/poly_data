"""Adapter for `Polymarket/agents` (vendor/polymarket-agents).

Adds the cloned repo to sys.path and re-exports the framework classes we use:
- `GammaMarketClient` (agents/connectors/gamma.py) — official market metadata
- `Polymarket` (agents/polymarket/polymarket.py) — official trade execution

Falls back to None if the vendor repo isn't present, so the rest of the bot
keeps working with our HTTP adapters.
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "polymarket-agents"

GammaMarketClient = None  # type: ignore[assignment]
Polymarket = None  # type: ignore[assignment]


def _load() -> None:
    global GammaMarketClient, Polymarket
    if not VENDOR.exists():
        return
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    try:
        from agents.connectors.gamma import GammaMarketClient as _G  # type: ignore
        GammaMarketClient = _G
    except Exception as e:  # noqa: BLE001
        print(f"[agents-adapter] could not import GammaMarketClient: {e}")
    try:
        from agents.polymarket.polymarket import Polymarket as _P  # type: ignore
        Polymarket = _P
    except Exception as e:  # noqa: BLE001
        print(f"[agents-adapter] could not import Polymarket: {e}")


_load()


def have_agents_framework() -> bool:
    return GammaMarketClient is not None


def gamma_client():
    if GammaMarketClient is None:
        return None
    return GammaMarketClient()

"""Pure-Python unit tests for Kelly + consensus + strategies + exit logic."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Avoid importing polars-heavy modules; test pure helpers via direct import.
from bot.executor import consensus, _client_id  # noqa: E402
from bot.exit_monitor import exit_check  # noqa: E402
from bot.strategies.arbitrage import agent_arbitrage  # noqa: E402
from bot.strategies.convergence import agent_convergence  # noqa: E402
from bot.strategies.whale_copy import agent_whale_copy  # noqa: E402


def test_kelly():
    from bot.sizing import kelly_size
    assert kelly_size(0.82, 0.65, 800) == 200.0           # quarter-cap binds
    assert kelly_size(0.4, 0.65, 800) == 0                # negative EV
    assert kelly_size(0.6, 0.5, 1000) == 200.0            # capped
    assert kelly_size(0.5, 0.5, 1000) == 0                # break-even
    assert kelly_size(0.0, 0.5, 1000) == 0


def test_consensus_modes():
    yes_y_h = [
        {"action": "BUY_YES", "confidence": 0.8},
        {"action": "BUY_YES", "confidence": 0.7},
        {"action": "HOLD", "confidence": 0.0},
    ]
    yes_h_h = [
        {"action": "BUY_YES", "confidence": 0.8},
        {"action": "HOLD", "confidence": 0.0},
        {"action": "HOLD", "confidence": 0.0},
    ]
    holds = [{"action": "HOLD", "confidence": 0.0}] * 3
    assert consensus(yes_y_h)[2] == 1.0
    assert consensus(yes_h_h)[2] == 0.5
    assert consensus(holds) == ("HOLD", 0.0, 0.0)


def test_client_id_stable():
    assert _client_id("m1", "BUY_YES") == _client_id("m1", "BUY_YES")
    assert _client_id("m1", "BUY_YES") != _client_id("m1", "BUY_NO")


def test_strategies():
    base_thesis = {
        "decision": {"action": "BUY_YES", "p_win": 0.8, "price_at_decision": 0.6},
        "checks": [
            {"signal": "BUY_YES", "confidence": 0.8, "note": "3 target wallets long"},
            {"signal": "NEUTRAL", "confidence": 0.5, "note": ""},
        ],
        "category": "crypto",
    }
    assert agent_arbitrage(base_thesis)["action"] == "BUY_YES"
    assert agent_convergence(base_thesis)["action"] == "BUY_YES"
    assert agent_whale_copy(base_thesis)["action"] == "BUY_YES"

    # Non-allowlisted category kills whale_copy
    sports = {**base_thesis, "category": "sports"}
    assert agent_whale_copy(sports)["action"] == "HOLD"

    # Thin edge kills arbitrage
    thin = {**base_thesis,
            "decision": {"action": "BUY_YES", "p_win": 0.61, "price_at_decision": 0.6}}
    assert agent_arbitrage(thin)["action"] == "HOLD"


def test_exit_check_target():
    pos = {"side": "BUY_YES", "entry_price": 0.4, "target_price": 0.7,
           "opened_at": "2030-01-01T00:00:00+00:00"}
    # 0.4 + 0.85 * 0.3 = 0.655
    assert exit_check(pos, 0.66, 0, 0) == "TARGET_HIT"
    assert exit_check(pos, 0.55, 0, 0) is None


def test_exit_check_volume_spike():
    pos = {"side": "BUY_YES", "entry_price": 0.4, "target_price": 0.7,
           "opened_at": "2099-01-01T00:00:00+00:00"}
    assert exit_check(pos, 0.5, vol_window=1000, vol_avg=200) == "VOLUME_EXIT"
    assert exit_check(pos, 0.5, vol_window=300, vol_avg=200) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all tests passed")

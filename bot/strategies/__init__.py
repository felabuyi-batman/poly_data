"""Strategy modules.

Each strategy is a callable: `evaluate(thesis: dict) -> Vote`.
Upstream reference (TypeScript): https://github.com/dylanpersonguy/Polymarket-Trading-Bot
We re-implement the three strategies the article actually uses:

  - arbitrage   — gap between price and our estimated probability
  - convergence — market is moving toward our thesis
  - whale_copy  — mirror the 47 target wallets, gated by category

If `vendor/polymarket-trading-bot` is present and exports a JSON config we
honor it; otherwise we use sensible defaults from bot.config.
"""
from .arbitrage import agent_arbitrage
from .convergence import agent_convergence
from .whale_copy import agent_whale_copy

ALL = (agent_arbitrage, agent_convergence, agent_whale_copy)

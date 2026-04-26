# Polymarket Trading Bot

Implements the architecture from `plan.md`, integrating all five components
named in the article. **LLM: OpenAI.**

## The 5 integrations

| # | Source | How it's used |
|---|--------|---------------|
| 1 | [`warproxxx/poly_data`](https://github.com/warproxxx/poly_data) | This repo. `bot.targets` reads `processed/trades.csv`; `bot.brain` uses it for base-rate + whale checks. |
| 2 | [`Polymarket/polymarket-cli`](https://github.com/Polymarket/polymarket-cli) | [`bot/polycli.py`](polycli.py) shells out to `polymarket -o json …` for market list, midpoint, book, and live order placement. HTTP fallback if binary absent. |
| 3 | [`Polymarket/agents`](https://github.com/Polymarket/agents) | [`bot/agents_adapter.py`](agents_adapter.py) imports `GammaMarketClient` (used by the scanner) and `Polymarket` (used by the executor). |
| 4 | [`dylanpersonguy/Polymarket-Trading-Bot`](https://github.com/dylanpersonguy/Polymarket-Trading-Bot) | [`bot/strategies/`](strategies/) — three modules (`arbitrage`, `convergence`, `whale_copy`) consumed by the executor's consensus loop. |
| 5 | OpenAI | [`bot/llm.py`](llm.py) — JSON-mode `chat.completions` calls for probability estimate, news, and disposition checks. Cached on disk; retried with backoff. |

## Pipeline

| Module | Output | What it does |
|---|---|---|
| `bot.targets` | `state/targets.json` | Top-N profitable wallets from `processed/trades.csv` |
| `bot.scanner` | `state/queue.json` | LLM-estimated probability + depth/hours/volume filters |
| `bot.brain` | `state/theses.json` | 4 checks (base rate, news, whale, disposition) + Kelly |
| `bot.executor` | `state/positions.json` | 3 strategies → consensus → orders (paper or live) |
| `bot.exit_monitor` | updates `positions.json` | Target / volume-spike / stale-thesis exits |

All five stages take an exclusive `state/bot.lock` so cron overlaps can't
clobber state. Order placement is idempotent via a `client_id` derived from
`(market_id, side)`.

## Setup

```bash
# 1. Clone the three external repos into vendor/
bash bot/setup_vendor.sh

# 2. (Optional) build / install the Rust CLI
brew tap Polymarket/polymarket-cli && brew install polymarket
# or: cd vendor/polymarket-cli && cargo install --path .

# 3. Python deps
uv sync                                                  # base
uv pip install openai python-dotenv                      # LLM + env loading
uv pip install -r vendor/polymarket-agents/requirements.txt   # agents framework
uv pip install py-clob-client                            # alt live-trading path

# 4. Configure
cp bot/.env.example bot/.env
# fill in OPENAI_API_KEY (and POLY_PRIVATE_KEY if you want live trades)
```

## Run

```bash
bash bot/run.sh           # one cycle, all 5 stages
```

Per-stage:

```bash
uv run python -m bot.targets
uv run python -m bot.scanner
uv run python -m bot.brain
uv run python -m bot.executor
uv run python -m bot.exit_monitor
```

## Tests

```bash
uv run python -m pytest bot/tests
```

## Honest caveats

- **`processed/trades.csv` has no `profit` column.** `bot.targets` reconstructs
  P&L by netting BUY/SELL flow per (wallet, market) and marking remainder to
  the last observed price. Approximate for never-resolved markets.
- **`dylanpersonguy/Polymarket-Trading-Bot` may not be public** — fetching it
  returned HTTP 502 during development. `setup_vendor.sh` skips failed clones,
  and our [`bot/strategies/`](strategies/) modules are self-contained ports
  of the three strategies the article describes.
- **Article's Kelly example (`kelly(0.82, 0.65, 800) = $114.28`) is wrong.**
  With a quarter-Kelly cap the correct value is $200. Code matches the math.
- **`DRY_RUN=true` by default.** Live trades require either the agents
  framework configured (`POLYGON_WALLET_PRIVATE_KEY`) or the CLI configured
  (`polymarket setup`). Otherwise paper trades land in `positions.json`.
- **Returns claimed in the article aren't reproducible from this code alone.**
  Treat them as illustrative.

## Cron

```cron
*/15 * * * * /bin/bash /home/ubuntu/poly_data/bot/run.sh >> /home/ubuntu/poly_data/bot/state/cron.log 2>&1
```

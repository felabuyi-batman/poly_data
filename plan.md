# Trackmind — How I Turned a $200 Seed Into $14,300 With 4 Free Repos and One Claude Prompt

**Source:** Trackmind (@0xTrackmind)

Everyone talks about trading Polymarket. Nobody shows how the bot actually works.

I'm going to show you exactly how I built mine. Every repo. Every command. Every dollar.

I'm not a quant. I don't have a Bloomberg terminal. I don't have a trading desk or a risk manager or a team. I have a laptop, a $5 VPS in Germany, and Claude Code. That's it.

Total cost: $25/month. The bot runs 24/7. I haven't touched it in 27 days.

Before you read:

This bot runs on 4 open-source repos, Claude Code, and a $5 VPS. Nothing is paywalled. Every link below is free.

If you want to skip the build and just copy the trades:
- Follow @0xTrackmind and bookmark this article
- My wallet for copy: wallet
- Copy here: kreo.app/@trackmind

## Step 0: The Data

You can't trade what you can't see.

Most people start with a strategy. I started with data. Specifically, 86 million trades made by real people on Polymarket - every entry, every exit, every timestamp, every wallet address. All of it public. All of it free.

github.com/warproxxx/poly_data - 646 stars

The insight that changed everything: most people try to predict events. The top wallets don't predict events - they predict other traders. They find markets where the crowd is wrong and they wait. That's a completely different game, and it starts with understanding who's actually winning.

I cloned the repo, loaded the data, and gave Claude one prompt:

> "analyze processed/trades.csv
>    find every wallet with 100+ trades and win rate above 70%
>    rank by profit. export top 50 to targets.json"

Claude scanned 14,000+ wallets in 4 minutes. Returned 47 targets.

```python
import polars as pl

df = pl.scan_csv("processed/trades.csv").collect(streaming=True)

wallets = (
    df.group_by("maker")
    .agg([
        pl.count().alias("trades"),
        (pl.col("profit") > 0).mean().alias("win_rate"),
        pl.col("profit").sum().alias("total_pnl"),
    ])
    .filter(
        (pl.col("trades") >= 100) &
        (pl.col("win_rate") > 0.70)
    )
    .sort("total_pnl", descending=True)
    .head(50)
)
```

The result was staggering. The top 20 wallets made more than the bottom 13,000 combined. This isn't normal distribution. It's extreme concentration at the top - and those 47 wallets became the foundation of everything the bot does.

That's not a stat. That's a target list.

## Step 1: The Scanner

A trading bot without a scanner is just a random number generator with extra steps.

The problem with Polymarket is volume. There are 500+ active markets at any given moment. Politics, crypto, weather, sports, science, geopolitics. Most of them are garbage - either the edge is too thin, the liquidity is too low, or the resolution is so far out that your capital is locked up doing nothing.

You need a filter. A ruthless one.

github.com/Polymarket/polymarket-cli - Official CLI. Rust. Made for agents.

This is Polymarket's own command-line tool, built specifically for programmatic trading. No scraping. No reverse-engineering. Official API, official data, instant JSON output.

Three commands changed everything:

```bash
# pull every active market as JSON
polymarket markets list --limit 500 -o json

# check who's buying and selling
polymarket clob book $TOKEN_ID -o json

# get the exact midpoint price
polymarket clob midpoint $TOKEN_ID -o json
```

No API key needed for read-only scanning. Your bot can watch 500+ markets in seconds without connecting a wallet. I piped the raw JSON straight into Claude:

> "read the JSON output from polymarket-cli.
>    for each market, score it on three factors:
>    1. gap between market price and your probability estimate
>    2. order book depth - is there $500+ on both sides?
>    3. hours until resolution - sweet spot is 4-48h
>    kill everything below threshold. save survivors to queue.json"

Claude built the scoring function:

```python
def score_market(market, claude_estimate):
    price = market["midpoint"]
    gap = abs(claude_estimate - price)
    depth = min(market["bids_depth"], market["asks_depth"])
    hours_left = market["hours_to_resolution"]

    if gap < 0.07: return None       # edge too thin
    if depth < 500: return None      # can't fill
    if hours_left < 4: return None   # too late
    if hours_left > 168: return None # too slow

    return {
        "market": market["question"],
        "gap": round(gap, 3),
        "depth": depth,
        "hours": hours_left,
        "ev": round(gap * depth * 0.001, 2)
    }
```

The gap threshold is the most important filter. If Claude's probability estimate and the market price are within 7 cents of each other, there's no edge. Transaction costs eat it alive. The depth filter matters too - a market where you can't get a $500 fill is useless. You'll move the price just by entering.

93% of markets get killed at this stage. 487 markets become 35. That's the point.

## Step 2: The Brain

The scanner finds opportunities. The brain decides whether to take them.

This is the step most people skip - and it's why most bots lose money. They see a gap between market price and "true" probability and enter immediately. But a gap alone doesn't mean you have an edge. It might mean the market knows something you don't. It might mean the news changed an hour ago. It might mean a whale just exited and the price is about to snap back.

The brain runs four checks on every surviving market before committing a dollar.

github.com/Polymarket/agents - Official agent framework. Python. MIT license.

This repo gives you the full skeleton: market data fetching, LLM integration, position tracking, trade execution hooks. I kept the structure and replaced the default strategy logic with Claude's analysis loop:

> "for every market in queue.json, run 4 checks:
>    1. base rate - what does historical data say about this type of event?
>    2. news - has anything changed in the last 6h that affects this market?
>    3. whale check - are any of the 47 target wallets currently holding a position?
>    4. disposition - is the crowd making a known cognitive error?
>
>    if 3/4 agree -> generate thesis
>    if thesis confidence > 75% -> size with kelly
>    if kelly says overbet -> cut to quarter kelly"

The whale check is the most powerful signal. When 3 or more of your 47 target wallets are simultaneously holding YES on the same market, that's not coincidence. That's convergence. Smart money found the same edge from different angles.

The disposition check catches something equally valuable: cognitive bias. Recency bias, anchoring, narrative fallacy - markets misprice constantly because of these. Claude can identify them. A market stuck at 40c because the last similar event failed six months ago is a different situation from a market stuck at 40c because the fundamentals are genuinely uncertain.

Claude generated the Kelly sizing for position management:

```python
def kelly_size(p_win, market_price, bankroll, max_fraction=0.25):
    """
    f* = (p * b - q) / b
    p = estimated win probability
    b = payout ratio (1/price - 1)
    q = 1 - p
    """
    b = (1 / market_price) - 1
    q = 1 - p_win
    f_star = (p_win * b - q) / b

    if f_star <= 0:
        return 0  # negative EV - kill trade

    f_capped = min(f_star, max_fraction)
    return round(bankroll * f_capped, 2)

# claude says 82% chance, market at 0.65, bankroll $800
# kelly_size(0.82, 0.65, 800) -> $114.28
```

If f* is negative, the expected value is negative. Kill the trade - no matter how confident you feel. If f* is above 0.25, you're overbetting and one bad run will wipe you. Cap at quarter Kelly and sleep well.

The sweet spot is f* between 0.05 and 0.15. That's where the Sharpe lives. That's where you compound without blowing up.

## Step 3: The Execution

You have the data. You have the brain. Now you need hands.

Execution is where theory meets reality - and reality is messy. Polymarket's order book is a Central Limit Order Book. There are no market orders. Everything is a limit order. If your price is wrong by even a few cents, you don't get filled. If you enter too aggressively, you move the price against yourself. If you're too passive, the opportunity closes before your order hits.

github.com/dylanpersonguy/Polymarket-Trading-Bot - 53,000 lines of TypeScript. 7 strategies.

I didn't use all 7 strategies. Three focused agents beat seven unfocused ones every time. I pulled the three that matched my edge:

> "extract three strategy modules:
>    1. arbitrage - catches price gaps between related markets
>    2. convergence - enters when price moves toward estimate
>    3. whale_copy - mirrors the 47 target wallets with 60s delay
>
>    run each as a separate agent. shared wallet, no shared memory.
>    consensus logic:
>    - 2 agents agree -> full position
>    - 1 agent only -> half position
>    - agents disagree -> no trade"

The consensus requirement is the single most important rule in the execution layer. When two independent agents look at the same market from different angles and reach the same conclusion, that's a real signal. When they disagree, the edge is ambiguous - and ambiguous edges lose money.

```python
async def execute_consensus(agents, market, wallet):
    votes = [agent.evaluate(market) for agent in agents]
    buy_votes = sum(1 for v in votes if v["action"] == "BUY")

    if buy_votes >= 2:
        size = kelly_size(
            p_win=avg([v["confidence"] for v in votes if v["action"] == "BUY"]),
            market_price=market["midpoint"],
            bankroll=wallet.balance
        )
        await place_order(market, size, side="BUY")

    elif buy_votes == 1:
        size = kelly_size(...) * 0.5  # half position on weak signal
        await place_order(market, size, side="BUY")
```

Consensus filter alone killed 40% of losing trades. Not by being smarter - just by requiring agreement before committing capital.

## Step 4: The Exit

This is where most bots die. They know when to enter. They never know when to leave.

I see it constantly in the poly_data analysis. Retail wallets enter at 35c, the market moves to 72c, and they hold. They're up 37 cents. They want the full dollar. Then news breaks, sentiment shifts, the market crashes back to 45c, and they exit for a 10-cent gain when they could have taken 37. Or worse - they hold through resolution and the market goes to zero.

The top 47 wallets don't do this. I ran the analysis and Claude found the pattern:

> "analyze exit behavior of the 47 target wallets.
>    what % hold to settlement vs exit early?
>    what triggers their exits?"

Claude: "91% of exits happen before resolution.
average exit: 73% of max potential profit captured.
primary trigger: volume spike within 10 minutes of exit.
secondary: price target hit at ~85% of estimated gap."

They take 73% of the potential profit and redeploy immediately. They're not trying to be right. They're trying to be profitable. There's a difference.

Three exit triggers built directly from this analysis:

```python
def exit_check(pos, current, volume_10m, avg_vol):
    # 1. target hit - 85% of expected move
    expected = pos["target"] - pos["entry"]
    if current >= pos["entry"] + expected * 0.85:
        return "TARGET_HIT"

    # 2. volume spike - smart money leaving
    if volume_10m > avg_vol * 3:
        return "VOLUME_EXIT"

    # 3. stale thesis - 24h no movement
    if pos["hours_since_entry"] > 24 and abs(pos["price_change"]) < 0.02:
        return "STALE_THESIS"

    return None
```

The volume spike exit is the one nobody talks about. When volume triples in a 10-minute window, it means someone large is moving. Either they know something, or they're taking profit. Either way - you want to be on the same side of that door, not the wrong side.

## The Startup Script

Every morning at 06:00 UTC my VPS runs one bash script. Four processes start. Four agents go live. I don't touch anything.

```bash
#!/bin/bash
cd ~/poly_data && uv run python -c \
  "from update_utils.process_live import process_live; process_live()"

polymarket markets list --limit 500 -o json > ~/bot/markets.json

cd ~/bot
python scanner.py &
python brain.py &
python executor.py &
python exit_monitor.py &

echo "$(date) - 4 agents live" >> ~/bot/log.txt
```

The first line pulls fresh trade data. The second pulls fresh markets. The next four lines launch the agents in parallel. The whole thing runs in under 30 seconds and costs $5/month in VPS fees.

Four processes. One screen session. One tab to check in the morning.

## The Stack

| Tool                   | Cost   | What It Does                     |
| ---------------------- | ------ | -------------------------------- |
| poly_data              | Free   | 86M trades, every wallet         |
| polymarket-cli         | Free   | Market scanning, order placement |
| Polymarket/agents      | Free   | Agent framework, LLM integration |
| Polymarket-Trading-Bot | Free   | 7 strategies, execution engine   |
| Claude API             | $20/mo | The brain                        |
| VPS (Hetzner)          | $5/mo  | Runs 24/7                        |
| **Total**              | **$25/mo** |                              |

## Results: Days 1-27

- **Day 1:** debugging API auth. Never traded. Normal.
- **Day 2:** +$310. First live trades. 4 positions. 3 winners. Whale copy agent caught an entry the other two confirmed.
- **Day 5:** +$870. Convergence engine started printing on crypto markets. BTC dominance, ETH ETF flow - these misprice constantly and correct fast.
- **Day 7:** +$2,100 cumulative. Win rate 68%. Convergence engine dragging on sports. Win rate there: 52%. Killed it.
- Win rate jumped to 73% overnight. One filter. That's all it took.
- **Day 14:** +$8,200 cumulative. Added category rotation - crypto, then politics, then macro. Each category has a mispricing cycle.
- **Day 19:** +$11,400 cumulative. 214 trades. 74% win rate. Sharpe: 2.31.
- **Day 27:** +$14,300 cumulative. 271 trades. 74% win rate. Sharpe: 2.47.

## What Didn't Work - And Why This Still Does

**Tested and removed:**
- Sports markets - priced in before the bot flags it. Win rate 52%. Gone.
- Markets under $10K - slippage turns every edge into a coin flip. Minimum now $50K.
- Holding to settlement - gave back 15-30% of profit every time. Volume exit fixed it.
- All 7 strategies at once - more agents means more noise. Three focused beats seven unfocused.
- Copying without filters - top wallets are geniuses in one category. Copy everything and you average down.

**What survived:**
- Three focused agents with clear consensus logic
- $50K+ market depth minimum
- Volume exit at ~73c, never hold to resolution
- Crypto-only copying from crypto-specialist wallets

**The actual edge:**
- poly_data → WHO is winning
- polymarket-cli → WHAT is mispriced
- Polymarket/agents → HOW to act
- Polymarket-Trading-Bot → WHEN to enter and exit
- Claude → the glue that synthesizes all of it in real time

The repos are public. The data is free. This window will close eventually - but the framework won't. The only question is whether you build it this weekend or read about someone else who did.

**$200 seed. +$14,300. 27 days**

Copy the trades: kreo.app/@trackmind

The repos:
- github.com/warproxxx/poly_data
- github.com/Polymarket/polymarket-cli
- github.com/Polymarket/agents
- github.com/dylanpersonguy/Polymarket-Trading-Bot

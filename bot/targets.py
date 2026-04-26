"""Step 0 — analyze trades.csv and produce targets.json.

The article's prompt assumes a `profit` column exists on trades.csv. The real
schema does not have one, so we compute it: per (wallet, market_id) we sum
signed USD flow (negative on BUY, positive on SELL) and mark remaining token
inventory to the last observed market price. The wallet's total_pnl is the
sum across all markets they touched. Win rate is fraction of (wallet, market)
positions that ended profitable.

Run:
    uv run python -m bot.targets

Output: bot/state/targets.json — list of top N wallets to track.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

from bot.config import (
    TARGETS_JSON,
    TARGETS_MIN_TRADES,
    TARGETS_MIN_WIN_RATE,
    TARGETS_TOP_N,
    TRADES_CSV,
)


def _load_trades() -> pl.DataFrame:
    if not TRADES_CSV.exists():
        raise FileNotFoundError(
            f"{TRADES_CSV} not found. Run `uv run python update_all.py` first."
        )
    return pl.read_csv(TRADES_CSV)


def _wallet_market_pnl(trades: pl.DataFrame) -> pl.DataFrame:
    """Compute realized + mark-to-market P&L per (wallet, market_id).

    Rows are present once per side (taker, maker). For each side:
    - direction BUY  → wallet spent usd_amount, gained token_amount
    - direction SELL → wallet received usd_amount, lost token_amount
    """
    taker = trades.select(
        pl.col("taker").alias("wallet"),
        pl.col("market_id"),
        pl.col("price"),
        pl.col("usd_amount"),
        pl.col("token_amount"),
        pl.col("taker_direction").alias("direction"),
        pl.col("timestamp"),
    )
    maker = trades.select(
        pl.col("maker").alias("wallet"),
        pl.col("market_id"),
        pl.col("price"),
        pl.col("usd_amount"),
        pl.col("token_amount"),
        pl.col("maker_direction").alias("direction"),
        pl.col("timestamp"),
    )
    legs = pl.concat([taker, maker], how="vertical_relaxed").filter(
        pl.col("wallet").is_not_null() & (pl.col("wallet") != "")
    )

    legs = legs.with_columns(
        pl.when(pl.col("direction") == "BUY")
        .then(-pl.col("usd_amount"))
        .otherwise(pl.col("usd_amount"))
        .alias("signed_usd"),
        pl.when(pl.col("direction") == "BUY")
        .then(pl.col("token_amount"))
        .otherwise(-pl.col("token_amount"))
        .alias("signed_tokens"),
    )

    # Last observed price per market (proxy for current mark)
    last_price = (
        trades.sort("timestamp")
        .group_by("market_id")
        .agg(pl.col("price").last().alias("last_price"))
    )

    per_pos = (
        legs.group_by(["wallet", "market_id"])
        .agg(
            pl.col("signed_usd").sum().alias("net_usd"),
            pl.col("signed_tokens").sum().alias("net_tokens"),
            pl.len().alias("legs"),
        )
        .join(last_price, on="market_id", how="left")
        .with_columns(
            (pl.col("net_usd") + pl.col("net_tokens") * pl.col("last_price")).alias("pnl")
        )
    )
    return per_pos


def build_targets() -> list[dict]:
    trades = _load_trades()
    print(f"[targets] loaded {trades.height:,} trades", file=sys.stderr)

    per_pos = _wallet_market_pnl(trades)
    print(
        f"[targets] computed P&L on {per_pos.height:,} (wallet, market) positions",
        file=sys.stderr,
    )

    wallets = (
        per_pos.group_by("wallet")
        .agg(
            pl.len().alias("positions"),
            (pl.col("pnl") > 0).mean().alias("win_rate"),
            pl.col("pnl").sum().alias("total_pnl"),
            pl.col("legs").sum().alias("trades"),
        )
        .filter(
            (pl.col("trades") >= TARGETS_MIN_TRADES)
            & (pl.col("win_rate") > TARGETS_MIN_WIN_RATE)
        )
        .sort("total_pnl", descending=True)
        .head(TARGETS_TOP_N)
    )

    targets = [
        {
            "wallet": row["wallet"],
            "trades": int(row["trades"]),
            "positions": int(row["positions"]),
            "win_rate": round(float(row["win_rate"]), 4),
            "total_pnl": round(float(row["total_pnl"]), 2),
        }
        for row in wallets.iter_rows(named=True)
    ]
    return targets


def main() -> None:
    targets = build_targets()
    TARGETS_JSON.parent.mkdir(parents=True, exist_ok=True)
    TARGETS_JSON.write_text(json.dumps(targets, indent=2))
    print(f"[targets] wrote {len(targets)} wallets → {TARGETS_JSON}")
    for i, t in enumerate(targets[:10], 1):
        print(
            f"  {i:>2}. {t['wallet'][:10]}…  pnl=${t['total_pnl']:>12,.0f}  "
            f"wr={t['win_rate']:.0%}  trades={t['trades']}"
        )


if __name__ == "__main__":
    main()

"""Thin wrapper around the `polymarket` Rust CLI.

All read-only commands fall back to direct HTTP calls if the CLI binary
isn't installed, so the bot still works on a fresh machine. To force CLI
usage set `POLYMARKET_REQUIRE_CLI=1`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

import requests

from bot.config import POLYMARKET_CLI

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"


def _have_cli() -> bool:
    return shutil.which(POLYMARKET_CLI) is not None


def _cli(args: list[str]) -> Any:
    out = subprocess.run(
        [POLYMARKET_CLI, "-o", "json", *args],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(f"{POLYMARKET_CLI} {' '.join(args)}: {out.stderr.strip()}")
    return json.loads(out.stdout)


def _require_cli() -> bool:
    return os.getenv("POLYMARKET_REQUIRE_CLI", "0") in ("1", "true", "yes")


# ---------- markets ----------

def list_markets(limit: int = 500) -> list[dict[str, Any]]:
    if _have_cli():
        try:
            return _cli(["markets", "list", "--limit", str(limit),
                         "--active", "true", "--closed", "false"])
        except Exception as e:  # noqa: BLE001
            if _require_cli():
                raise
            print(f"[cli] falling back to HTTP: {e}")
    # HTTP fallback (Gamma)
    out: list[dict] = []
    offset = 0
    while len(out) < limit:
        page_size = min(100, limit - len(out))
        r = requests.get(
            f"{GAMMA}/markets",
            params={"active": "true", "closed": "false", "archived": "false",
                    "limit": page_size, "offset": offset},
            timeout=20,
        )
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        out.extend(page)
        offset += page_size
        if len(page) < page_size:
            break
    return out


# ---------- clob ----------

def midpoint(token_id: str) -> float | None:
    if _have_cli():
        try:
            return float(_cli(["clob", "midpoint", token_id])["mid"])
        except Exception:
            if _require_cli():
                raise
    try:
        r = requests.get(f"{CLOB}/midpoint", params={"token_id": token_id}, timeout=10)
        if r.status_code != 200:
            return None
        return float(r.json().get("mid"))
    except Exception:
        return None


def book(token_id: str) -> dict[str, list[dict]]:
    if _have_cli():
        try:
            return _cli(["clob", "book", token_id])
        except Exception:
            if _require_cli():
                raise
    try:
        r = requests.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=10)
        if r.status_code != 200:
            return {"bids": [], "asks": []}
        return r.json()
    except Exception:
        return {"bids": [], "asks": []}


def book_depth(token_id: str) -> tuple[float, float]:
    """Total notional resting on each side of the book."""
    b = book(token_id)
    def notional(levels: list[dict]) -> float:
        return sum(float(l["price"]) * float(l["size"]) for l in levels or [])
    return notional(b.get("bids", [])), notional(b.get("asks", []))


def create_order(token: str, side: str, price: float, size: float) -> dict:
    """Place a limit order via CLI. Requires `polymarket setup` first."""
    if not _have_cli():
        raise RuntimeError("polymarket CLI not installed; run bot/setup_vendor.sh")
    return _cli([
        "clob", "create-order",
        "--token", token,
        "--side", side.lower(),
        "--price", f"{price:.4f}",
        "--size", f"{size:.4f}",
    ])

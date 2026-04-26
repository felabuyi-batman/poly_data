"""Filesystem advisory lock + balance helpers shared by all bot stages."""
from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path

from bot import polycli
from bot.config import BANKROLL_USD, STATE_DIR

LOCK_FILE = STATE_DIR / "bot.lock"


@contextlib.contextmanager
def state_lock(timeout_sec: float = 30.0):
    """Process-wide advisory lock so cron overlap can't clobber state files."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.time() + timeout_sec
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.time() > deadline:
                os.close(fd)
                raise RuntimeError(f"could not acquire {LOCK_FILE} within {timeout_sec}s")
            time.sleep(0.5)
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def usable_bankroll(positions: list[dict]) -> float:
    """BANKROLL_USD minus capital already allocated to OPEN paper/live positions.

    For live runs this is conservative — we don't poll on-chain balance because
    the CLI does that for us at order-placement time. Adding a real check is
    one CLI call; we keep this fast for the inner loop.
    """
    used = sum(float(p.get("size_usd") or 0) for p in positions
               if p.get("status") == "OPEN")
    return max(0.0, BANKROLL_USD - used)


def live_balance_usdc() -> float | None:
    """Best-effort live USDC balance via `polymarket clob balance`."""
    try:
        import json as _json
        import shutil
        import subprocess

        if not shutil.which("polymarket"):
            return None
        out = subprocess.run(
            ["polymarket", "-o", "json", "clob", "balance",
             "--asset-type", "collateral"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return None
        return float(_json.loads(out.stdout).get("balance", 0))
    except Exception:
        return None


__all__ = ["state_lock", "usable_bankroll", "live_balance_usdc"]

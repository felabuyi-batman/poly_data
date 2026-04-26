"""OpenAI-backed helpers used by the brain and the scanner.

Provides:
  - estimate_probability(question, midpoint, hours)  → float in (0,1)
  - news_signal(question, midpoint, hours)           → {signal, confidence, note}
  - disposition_signal(question, midpoint)           → {signal, confidence, note}

All calls are JSON-only, retried with exponential backoff, and disk-cached for
LLM_CACHE_TTL_SEC seconds keyed on the prompt. If OPENAI_API_KEY is unset or
the SDK is missing, every helper returns a neutral default so the rest of the
pipeline still runs.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from bot.config import (
    LLM_CACHE_TTL_SEC,
    OPENAI_API_KEY,
    OPENAI_MAX_RETRIES,
    OPENAI_MODEL,
    STATE_DIR,
)

CACHE_DIR = STATE_DIR / "llm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(prompt: str) -> Path:
    h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.json"


def _cache_get(prompt: str) -> Any | None:
    p = _cache_key(prompt)
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text())
        if time.time() - blob["t"] > LLM_CACHE_TTL_SEC:
            return None
        return blob["v"]
    except Exception:
        return None


def _cache_put(prompt: str, value: Any) -> None:
    _cache_key(prompt).write_text(json.dumps({"t": time.time(), "v": value}))


def _client():
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


def _ask_json(prompt: str, schema_hint: str) -> dict | None:
    """Send prompt to OpenAI, return parsed JSON object or None on failure."""
    cached = _cache_get(prompt)
    if cached is not None:
        return cached

    client = _client()
    if client is None:
        return None

    full = (
        f"{prompt}\n\n"
        f"Respond as STRICT JSON matching this shape and nothing else:\n{schema_hint}"
    )
    delay = 1.0
    for attempt in range(OPENAI_MAX_RETRIES):
        try:
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": full}],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=300,
            )
            text = resp.choices[0].message.content or ""
            value = json.loads(text)
            _cache_put(prompt, value)
            return value
        except Exception as e:  # noqa: BLE001
            if attempt == OPENAI_MAX_RETRIES - 1:
                print(f"[llm] giving up after {attempt+1} tries: {e}")
                return None
            time.sleep(delay)
            delay *= 2
    return None


# -------------------- public helpers --------------------

NEUTRAL = {"signal": "NEUTRAL", "confidence": 0.5, "note": "OPENAI_API_KEY unset"}


def estimate_probability(question: str, midpoint: float, hours: float) -> float | None:
    prompt = (
        f'Polymarket question: "{question}"\n'
        f"Current YES midpoint: {midpoint:.3f}\n"
        f"Hours to resolution: {hours:.1f}\n\n"
        "Estimate the true probability that YES resolves true. "
        "Use base rates and any common knowledge about this category."
    )
    out = _ask_json(prompt, '{"p":0..1,"reason":"..."}')
    if not out:
        return None
    try:
        p = float(out.get("p"))
        return p if 0 < p < 1 else None
    except (TypeError, ValueError):
        return None


def news_signal(question: str, midpoint: float, hours: float) -> dict:
    if not OPENAI_API_KEY:
        return dict(NEUTRAL)
    prompt = (
        f'Polymarket question: "{question}"\n'
        f"Current YES price: {midpoint:.2f}, hours to resolution: {hours:.1f}\n\n"
        "Has any news in the last 6 hours materially changed the probability? "
        'signal: "BUY_YES", "BUY_NO", or "NEUTRAL".'
    )
    out = _ask_json(
        prompt,
        '{"signal":"BUY_YES|BUY_NO|NEUTRAL","confidence":0..1,"note":"..."}',
    )
    return out or {"signal": "NEUTRAL", "confidence": 0.5, "note": "llm error"}


def disposition_signal(question: str, midpoint: float) -> dict:
    if not OPENAI_API_KEY:
        return dict(NEUTRAL)
    prompt = (
        f'Polymarket question: "{question}"\n'
        f"Current YES price: {midpoint:.2f}\n\n"
        "Is the crowd making a known cognitive error here "
        "(recency bias, anchoring, narrative fallacy)?"
    )
    out = _ask_json(
        prompt,
        '{"signal":"BUY_YES|BUY_NO|NEUTRAL","confidence":0..1,"note":"..."}',
    )
    return out or {"signal": "NEUTRAL", "confidence": 0.5, "note": "llm error"}

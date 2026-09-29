"""Shared Grok settings and cost accounting for every caller.

Used by the live API (main.py), the signal-test logger and the Apify Actor so
all three search X the same way and can be tuned in one place with env vars:

    GROK_MODEL        model id (default grok-4.7)
    GROK_SEARCH_DAYS  only search posts from the last N days (default 3; 0 = no limit)
    GROK_MAX_TURNS    cap on search/reasoning rounds (unset = xAI default, about 3)

X Search is billed per post read ($5 per 1,000), plus tokens for every post the
model reads, so fewer, more recent posts is the main cost lever.
"""
import os
from datetime import date, timedelta
from typing import Optional

# USD per 1M tokens (short context) and per X item, from docs.x.ai/developers/pricing (Sep 2026).
PRICES = {
    "grok-4.7": {"input": 2.00, "cached": 0.50, "output": 6.00},
    "grok-4.6": {"input": 2.00, "cached": 0.50, "output": 6.00},
    "grok-4.5": {"input": 2.00, "cached": 0.30, "output": 6.00},
    "grok-4.3": {"input": 1.25, "cached": 0.20, "output": 2.50},
}
X_POST_USD = 5.00 / 1000
X_PROFILE_USD = 10.00 / 1000


def model() -> str:
    return os.environ.get("GROK_MODEL", "grok-4.7").strip() or "grok-4.7"


def search_days() -> int:
    try:
        return max(0, int(os.environ.get("GROK_SEARCH_DAYS", "3")))
    except ValueError:
        return 3


def max_turns() -> Optional[int]:
    raw = os.environ.get("GROK_MAX_TURNS", "").strip()
    try:
        return max(1, int(raw)) if raw else None
    except ValueError:
        return None


def x_search_tool(days: Optional[int] = None, today: Optional[date] = None) -> dict:
    days = search_days() if days is None else days
    tool = {"type": "x_search"}
    if days > 0:
        tool["from_date"] = ((today or date.today()) - timedelta(days=days)).isoformat()
    return tool


def request_kwargs(prompt: str, model_id: Optional[str] = None, days: Optional[int] = None,
                   turns: Optional[int] = None) -> dict:
    """Keyword arguments for client.responses.create(...)."""
    kwargs = {
        "model": model_id or model(),
        "input": [{"role": "user", "content": prompt}],
        "tools": [x_search_tool(days)],
    }
    turns = max_turns() if turns is None else turns
    if turns:
        kwargs["extra_body"] = {"max_turns": turns}
    return kwargs


def _get(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    value = getattr(obj, name, None)
    if value is None:
        extra = getattr(obj, "model_extra", None) or {}
        value = extra.get(name, default)
    return default if value is None else value


def usage_summary(resp) -> dict:
    """Token and X-search counts from a Responses API result (missing fields are 0)."""
    usage = _get(resp, "usage")
    details = _get(usage, "input_tokens_details")
    tool_details = _get(usage, "server_side_tool_usage_details")
    return {
        "input_tokens": int(_get(usage, "input_tokens", 0) or 0),
        "cached_tokens": int(_get(details, "cached_tokens", 0) or 0),
        "output_tokens": int(_get(usage, "output_tokens", 0) or 0),
        "x_posts": int(_get(tool_details, "x_posts_fetched", 0) or 0),
        "x_users": int(_get(tool_details, "x_users_fetched", 0) or 0),
    }


def estimate_cost(summary: dict, model_id: str) -> float:
    p = PRICES.get(model_id, PRICES["grok-4.7"])
    fresh = max(0, summary["input_tokens"] - summary["cached_tokens"])
    usd = (
        fresh * p["input"] + summary["cached_tokens"] * p["cached"] + summary["output_tokens"] * p["output"]
    ) / 1_000_000
    usd += summary["x_posts"] * X_POST_USD + summary["x_users"] * X_PROFILE_USD
    return round(usd, 4)

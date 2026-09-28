"""Pure logic for the Apify Actor: no Apify imports, so it is unit-testable.

Scores X sentiment for prediction-market questions with Grok (live X search)
and shapes one output row per question. Odds come from the repo's odds.py,
which the Dockerfile copies next to this package.
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

PROMPT_VERSION = "v2"
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4.7")
MAX_QUESTIONS = 25
MAX_QUESTION_CHARS = 300
NL = chr(10)


def clean_questions(raw) -> list:
    """Trimmed, de-duplicated (case-insensitive) questions, capped at MAX_QUESTIONS."""
    if isinstance(raw, str):
        raw = [raw]
    out, seen = [], set()
    for item in raw or []:
        if not isinstance(item, str):
            continue
        q = " ".join(item.split())[:MAX_QUESTION_CHARS]
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[:MAX_QUESTIONS]


def build_prompt(question: str) -> str:
    """Same prompt as the signal-test logger (v2): the event, not the market's prices."""
    return (
        "Search X for recent posts about this prediction market:" + NL
        + '"' + question + '"' + NL + NL
        + "Score what people are saying about the underlying event itself. "
        + "Ignore posts that only discuss betting odds, prediction-market prices or "
        + "trading positions (Polymarket, Kalshi or similar), and do not mention "
        + "market odds or prices in the catalyst." + NL + NL
        + "Return ONLY valid JSON, no markdown:" + NL
        + '{"score": <int -100 to 100>, "catalyst": "<one sentence about the event>", '
        + '"volume_signal": "<rising|falling|flat>"}'
    )


def parse_json_object(text: str) -> Optional[dict]:
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize(raw: dict) -> dict:
    try:
        score = max(-100, min(100, int(raw.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    catalyst = raw.get("catalyst")
    volume = raw.get("volume_signal")
    return {
        "score": score,
        "catalyst": catalyst.strip() if isinstance(catalyst, str) else "",
        "volume_signal": volume if volume in ("rising", "falling", "flat") else "flat",
    }


def make_client(api_key: str):
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=120)


def response_text(resp) -> str:
    text = getattr(resp, "output_text", None) or ""
    if text:
        return text
    parts = []
    for item in getattr(resp, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "text", None):
                parts.append(block.text)
    return NL.join(parts)


def grok_score(question: str, client) -> dict:
    """Normalized score for one question. Raises on API errors or unusable output."""
    resp = client.responses.create(
        model=GROK_MODEL,
        input=[{"role": "user", "content": build_prompt(question)}],
        tools=[{"type": "x_search"}],
    )
    parsed = parse_json_object(response_text(resp))
    if parsed is None:
        raise ValueError("no_json")
    return normalize(parsed)


def safe_score(question: str, client, attempts: int = 2):
    """(score dict, None) or (None, error code). Never raises."""
    err = "scoring_failed"
    for _ in range(attempts):
        try:
            return grok_score(question, client), None
        except Exception as e:  # noqa: BLE001 - reported per row, never fatal
            err = f"scoring_failed_{type(e).__name__}"
    return None, err


def _pct(block: Optional[dict]) -> Optional[float]:
    return block.get("implied_prob_pct") if isinstance(block, dict) else None


def result_item(question: str, scored: Optional[dict], odds_block: Optional[dict], error: Optional[str]) -> dict:
    """One dataset row. Flat fields for tables, the full odds block for detail."""
    scored = scored or {}
    odds_block = odds_block or {}
    poly, kalshi = odds_block.get("polymarket"), odds_block.get("kalshi")
    return {
        "question": question,
        "score": scored.get("score"),
        "catalyst": scored.get("catalyst"),
        "volume_signal": scored.get("volume_signal"),
        "polymarket_yes_pct": _pct(poly),
        "kalshi_yes_pct": _pct(kalshi),
        "polymarket_market": poly.get("market") if isinstance(poly, dict) else None,
        "kalshi_market": kalshi.get("market") if isinstance(kalshi, dict) else None,
        "odds": odds_block or None,
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "error": error,
    }

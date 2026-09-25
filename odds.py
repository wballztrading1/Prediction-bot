"""Live Polymarket odds for a market question (used by /brief).

Polymarket's public search (no key) finds candidate markets; the closest open
market by word overlap is returned with its Yes price. Fails soft: any error,
timeout or weak match gives polymarket=None and the brief still returns.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Callable, Optional

SEARCH_URL = os.environ.get(
    "POLYMARKET_SEARCH_URL", "https://gamma-api.polymarket.com/public-search"
)
TIMEOUT = float(os.environ.get("ODDS_TIMEOUT_SEC", "3"))
TTL = int(os.environ.get("ODDS_TTL_SEC", "120"))
MIN_MATCH = float(os.environ.get("ODDS_MIN_MATCH", "0.6"))

STOPWORDS = {
    "a", "an", "and", "at", "be", "before", "by", "do", "does", "for", "in",
    "is", "it", "of", "on", "or", "the", "to", "will", "win", "with",
}

_cache: dict = {}


def tokens(text: str) -> set:
    text = (text or "").lower().replace("$", "").replace(",", "")
    parts = (t.strip(".") for t in re.split(r"[^a-z0-9.]+", text))
    return {t for t in parts if t and t not in STOPWORDS}


def match_score(query: str, candidate: str) -> float:
    q, c = tokens(query), tokens(candidate)
    if not q or not c:
        return 0.0
    overlap = len(q & c)
    recall = overlap / len(q)
    jaccard = overlap / len(q | c)
    score = 0.7 * recall + 0.3 * jaccard
    # Numbers (years, price levels, dates) must agree: "2026" is not "2027".
    if any(t[0].isdigit() and t not in c for t in q):
        score *= 0.5
    return round(score, 3)


def _loads(value) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _num(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def yes_price(market: dict) -> Optional[float]:
    outcomes = _loads(market.get("outcomes"))
    prices = _loads(market.get("outcomePrices"))
    for outcome, price in zip(outcomes, prices):
        if str(outcome).strip().lower() == "yes":
            return _num(price)
    return None


def pick_polymarket(query: str, payload: dict) -> Optional[dict]:
    """Best open market for the query, or None if nothing matches well enough."""
    best, best_score = None, 0.0
    for event in (payload or {}).get("events") or []:
        if not isinstance(event, dict) or event.get("closed"):
            continue
        for market in event.get("markets") or []:
            if not isinstance(market, dict) or market.get("closed"):
                continue
            if market.get("active") is False:
                continue
            price = yes_price(market)
            if price is None:
                continue
            score = match_score(query, market.get("question") or "")
            if score > best_score:
                best, best_score = (event, market, price), score
    if best is None or best_score < MIN_MATCH:
        return None
    event, market, price = best
    slug = event.get("slug") or market.get("slug") or ""
    return {
        "source": "polymarket",
        "market": market.get("question"),
        "yes_price": round(price, 4),
        "implied_prob_pct": round(price * 100, 1),
        "best_bid": _num(market.get("bestBid")),
        "best_ask": _num(market.get("bestAsk")),
        "volume_24h": _num(market.get("volume24hr")),
        "url": f"https://polymarket.com/event/{slug}" if slug else None,
        "match_score": best_score,
    }


def fetch_polymarket(query: str) -> Optional[dict]:
    params = {
        "q": query,
        "limit_per_type": 5,
        "keep_closed_markets": 0,
        "events_status": "active",
    }
    try:
        import httpx

        resp = httpx.get(SEARCH_URL, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as e:
        print(f"ALERT odds_fetch_error polymarket {type(e).__name__}")
        return None


FIXTURE = {
    "events": [
        {
            "slug": "when-will-bitcoin-hit-150k",
            "closed": False,
            "markets": [
                {
                    "question": "Will Bitcoin hit $150k by December 31, 2026?",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0.028", "0.972"]',
                    "bestBid": 0.021,
                    "bestAsk": 0.035,
                    "active": True,
                    "closed": False,
                },
                {
                    "question": "Will Bitcoin hit $150k by September 30?",
                    "outcomes": '["Yes", "No"]',
                    "outcomePrices": '["0", "1"]',
                    "active": True,
                    "closed": True,
                },
            ],
        }
    ]
}


def market_odds(query: str, fetch: Optional[Callable[[str], Optional[dict]]] = None) -> dict:
    """Cached odds block for a brief. Never raises."""
    key = query.strip().lower()
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]
    fetch = fetch or fetch_polymarket
    payload = fetch(query)
    result = {
        "polymarket": pick_polymarket(query, payload) if payload else None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload is None:
        result["error"] = "odds_unavailable"
    else:
        _cache[key] = (now, result)
    return result

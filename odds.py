"""Live Polymarket and Kalshi odds for a market question (used by /brief).

Polymarket: public search (no key); closest open market by word overlap.
Kalshi: no text search, so a background-refreshed index of open events is
matched by title, then prices are fetched for the top candidates only.

Everything fails soft: errors, timeouts or weak matches give null for that
source and the brief still returns.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

SEARCH_URL = os.environ.get(
    "POLYMARKET_SEARCH_URL", "https://gamma-api.polymarket.com/public-search"
)
KALSHI_BASE = os.environ.get(
    "KALSHI_API_BASE", "https://external-api.kalshi.com/trade-api/v2"
).rstrip("/")
TIMEOUT = float(os.environ.get("ODDS_TIMEOUT_SEC", "3"))
TTL = int(os.environ.get("ODDS_TTL_SEC", "120"))
MIN_MATCH = float(os.environ.get("ODDS_MIN_MATCH", "0.6"))
KALSHI_MIN_MATCH = float(os.environ.get("KALSHI_MIN_MATCH", "0.55"))
KALSHI_EVENT_MIN = float(os.environ.get("KALSHI_EVENT_MIN", "0.35"))
KALSHI_CANDIDATES = int(os.environ.get("KALSHI_CANDIDATES", "3"))
KALSHI_MAX_PAGES = int(os.environ.get("KALSHI_MAX_PAGES", "40"))
KALSHI_INDEX_TTL = int(os.environ.get("KALSHI_INDEX_TTL_SEC", "1800"))
KALSHI_PAGE_PAUSE = float(os.environ.get("KALSHI_PAGE_PAUSE_SEC", "0.25"))

STOPWORDS = {
    "a", "an", "and", "at", "be", "before", "by", "do", "does", "for", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "what", "which", "who",
    "will", "win", "with",
}

_cache: dict = {}


# --- text matching -----------------------------------------------------------
def _norm(tok: str) -> str:
    """'150k' -> '150000', '1.5m' -> '1500000' so $150k matches $150,000."""
    for suffix, mult in (("k", 1_000), ("m", 1_000_000), ("b", 1_000_000_000)):
        if tok.endswith(suffix) and len(tok) > 1:
            try:
                val = float(tok[:-1]) * mult
                return str(int(val)) if val == int(val) else str(val)
            except ValueError:
                return tok
    return tok


def tokens(text: str) -> set:
    text = (text or "").lower().replace("$", "").replace(",", "")
    parts = (_norm(t.strip(".")) for t in re.split(r"[^a-z0-9.]+", text))
    return {t for t in parts if t and t not in STOPWORDS}


def _numeric(tok: str) -> bool:
    return tok[0].isdigit()


def _overlap_score(q: set, c: set) -> float:
    if not q or not c:
        return 0.0
    overlap = len(q & c)
    return 0.7 * (overlap / len(q)) + 0.3 * (overlap / len(q | c))


def match_score(query: str, candidate: str) -> float:
    q, c = tokens(query), tokens(candidate)
    score = _overlap_score(q, c)
    # Numbers (years, price levels, dates) must agree: "2026" is not "2027".
    if any(_numeric(t) and t not in c for t in q):
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


def _http_get(url: str, params: dict) -> dict:
    import httpx

    resp = httpx.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {}


# --- Polymarket ----------------------------------------------------------------
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
        return _http_get(SEARCH_URL, params)
    except Exception as e:
        print(f"ALERT odds_fetch_error polymarket {type(e).__name__}")
        return None


# --- Kalshi ----------------------------------------------------------------------
_kx = {"events": [], "built_at": 0.0, "truncated": False, "building": False, "error": None}
_kx_lock = threading.Lock()


def _index_entry(event: dict) -> dict:
    title = event.get("title") or ""
    sub = event.get("sub_title") or ""
    return {
        "event_ticker": event.get("event_ticker"),
        "series_ticker": event.get("series_ticker") or "",
        "title": title,
        "sub_title": sub,
        "tokens": tokens(f"{title} {sub}"),
    }


def build_kalshi_index(get: Callable = _http_get, max_pages: int = KALSHI_MAX_PAGES, pause: float = KALSHI_PAGE_PAUSE):
    events, cursor, truncated = [], None, False
    for page in range(max_pages):
        params = {"status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data = get(f"{KALSHI_BASE}/events", params)
        for event in data.get("events") or []:
            if isinstance(event, dict) and event.get("event_ticker"):
                events.append(_index_entry(event))
        cursor = data.get("cursor")
        if not cursor:
            break
        if pause:
            time.sleep(pause)
    else:
        truncated = bool(cursor)
    return events, truncated


def _refresh_kalshi(get: Callable) -> None:
    try:
        events, truncated = build_kalshi_index(get)
        _kx.update(events=events, built_at=time.time(), truncated=truncated, error=None)
        print(f"kalshi_index events={len(events)} truncated={truncated}")
    except Exception as e:
        # Retry in about 5 minutes instead of on every request.
        _kx.update(error=type(e).__name__, built_at=time.time() - KALSHI_INDEX_TTL + 300)
        print(f"ALERT kalshi_index_error {type(e).__name__}")
    finally:
        _kx["building"] = False


def ensure_kalshi_index(get: Optional[Callable] = None, background: bool = True) -> None:
    if time.time() - _kx["built_at"] < KALSHI_INDEX_TTL:
        return
    with _kx_lock:
        if _kx["building"]:
            return
        _kx["building"] = True
    if background:
        threading.Thread(target=_refresh_kalshi, args=(get or _http_get,), daemon=True).start()
    else:
        _refresh_kalshi(get or _http_get)


def kalshi_index_status() -> dict:
    built = _kx["built_at"]
    return {
        "kalshi_events": len(_kx["events"]),
        "kalshi_age_sec": int(time.time() - built) if _kx["events"] else None,
        "kalshi_truncated": _kx["truncated"],
        "kalshi_building": _kx["building"],
        "kalshi_error": _kx["error"],
    }


def _kalshi_price(market: dict):
    bid = _num(market.get("yes_bid_dollars"))
    ask = _num(market.get("yes_ask_dollars"))
    last = _num(market.get("last_price_dollars"))
    if bid is not None and ask is not None and ask > 0:
        return (bid + ask) / 2, bid, ask
    if last is not None:
        return last, bid, ask
    return None, bid, ask


def fetch_kalshi_markets(event_ticker: str) -> list:
    data = _http_get(f"{KALSHI_BASE}/markets", {"event_ticker": event_ticker, "status": "open"})
    return [m for m in data.get("markets") or [] if isinstance(m, dict)]


def pick_kalshi(query: str, index: list, get_markets: Callable[[str], list]) -> Optional[dict]:
    q = tokens(query)
    if not q:
        return None
    ranked = sorted(
        ((_overlap_score(q, ev["tokens"]), ev) for ev in index),
        key=lambda pair: pair[0],
        reverse=True,
    )
    candidates = [ev for score, ev in ranked[:KALSHI_CANDIDATES] if score >= KALSHI_EVENT_MIN]
    q_numbers = {t for t in q if _numeric(t)}
    best, best_score = None, 0.0
    for ev in candidates:
        scored = []
        for m in get_markets(ev["event_ticker"]):
            if m.get("status") not in ("active", "open"):
                continue
            price, bid, ask = _kalshi_price(m)
            if price is None:
                continue
            label = m.get("yes_sub_title") or ""
            text = f"{ev['title']} {ev['sub_title']} {label}"
            c = tokens(text)
            # Every number in the question must appear in the title or outcome
            # (not the sub_title: "Before Jan 1, 2027" is a 2026 market).
            if not q_numbers <= tokens(f"{ev['title']} {label}"):
                continue
            if not (q - q_numbers) & c:
                continue  # and at least one topic word
            scored.append((round(_overlap_score(q, c), 3), m, price, bid, ask, label))
        if not scored:
            continue
        scored.sort(key=lambda row: row[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            continue  # ambiguous multi-outcome event: don't guess
        if scored[0][0] > best_score:
            best, best_score = (ev, scored[0]), scored[0][0]
    if best is None or best_score < KALSHI_MIN_MATCH:
        return None
    ev, (score, m, price, bid, ask, label) = best
    title = ev["title"]
    market_name = f"{title}: {label}" if label and label.lower() not in title.lower() else title
    series = ev["series_ticker"].lower()
    return {
        "source": "kalshi",
        "market": market_name,
        "ticker": m.get("ticker"),
        "yes_price": round(price, 4),
        "implied_prob_pct": round(price * 100, 1),
        "best_bid": bid,
        "best_ask": ask,
        "volume_24h": _num(m.get("volume_24h_fp")),
        "url": f"https://kalshi.com/markets/{series}" if series else None,
        "match_score": score,
    }


def kalshi_odds(query: str):
    """(odds or None, error or None). Never raises."""
    ensure_kalshi_index()
    if not _kx["events"]:
        return None, "kalshi_index_warming" if _kx["building"] else "kalshi_unavailable"
    try:
        return pick_kalshi(query, _kx["events"], fetch_kalshi_markets), None
    except Exception as e:
        print(f"ALERT odds_fetch_error kalshi {type(e).__name__}")
        return None, "kalshi_unavailable"


# --- fixtures (TEST_MODE) --------------------------------------------------------
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

KALSHI_FIXTURE_EVENTS = [
    {"event_ticker": "KXBTCMAXY-26", "series_ticker": "KXBTCMAXY", "title": "How high will Bitcoin get in 2026?", "sub_title": "Before Jan 1, 2027"},
    {"event_ticker": "KXWARMING-50", "series_ticker": "KXWARMING", "title": "Will the world pass 2 degrees Celsius over pre-industrial levels before 2050?", "sub_title": "Before 2050"},
]
KALSHI_FIXTURE_MARKETS = {
    "KXBTCMAXY-26": [
        {"ticker": "KXBTCMAXY-26-150000", "status": "active", "yes_sub_title": "$150,000 or above", "yes_bid_dollars": "0.0300", "yes_ask_dollars": "0.0500", "last_price_dollars": "0.0400", "volume_24h_fp": "1200.00"},
        {"ticker": "KXBTCMAXY-26-200000", "status": "active", "yes_sub_title": "$200,000 or above", "yes_bid_dollars": "0.0100", "yes_ask_dollars": "0.0200", "last_price_dollars": "0.0100"},
    ],
    "KXWARMING-50": [
        {"ticker": "KXWARMING-50", "status": "active", "yes_sub_title": "Before 2050", "yes_bid_dollars": "0.6400", "yes_ask_dollars": "0.6800", "last_price_dollars": "0.6800"},
    ],
}


def fixture_kalshi(query: str):
    index = [_index_entry(e) for e in KALSHI_FIXTURE_EVENTS]
    return pick_kalshi(query, index, lambda t: KALSHI_FIXTURE_MARKETS.get(t, [])), None


# --- combined ------------------------------------------------------------------
def market_odds(
    query: str,
    fetch: Optional[Callable[[str], Optional[dict]]] = None,
    kalshi: Optional[Callable] = None,
) -> dict:
    """Cached odds block for a brief. Never raises."""
    key = query.strip().lower()
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]
    fetch = fetch or fetch_polymarket
    kalshi = kalshi or kalshi_odds
    with ThreadPoolExecutor(max_workers=2) as pool:
        poly_future = pool.submit(fetch, query)
        kalshi_future = pool.submit(kalshi, query)
        payload = poly_future.result()
        try:
            k_odds, k_err = kalshi_future.result()
        except Exception:
            k_odds, k_err = None, "kalshi_unavailable"
    result = {
        "polymarket": pick_polymarket(query, payload) if payload else None,
        "kalshi": k_odds,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if payload is None:
        result["error"] = "odds_unavailable"
    if k_err:
        result["kalshi_error"] = k_err
    if payload is not None and not k_err:
        _cache[key] = (now, result)
    return result

"""Polymarket + Kalshi odds matching and /brief enrichment. No network: fixtures only."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TEST_MODE"] = "1"
os.environ.setdefault("XAI_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import odds  # noqa: E402
import schemas  # noqa: E402

client = TestClient(main.app)
Q = "Will Bitcoin hit 150k in 2026"


def market(question, yes, closed=False):
    return {
        "question": question,
        "outcomes": '["Yes", "No"]',
        "outcomePrices": f'["{yes}", "{1 - yes}"]',
        "active": True,
        "closed": closed,
    }


def kx_index(*events):
    return [odds._index_entry(e) for e in events]


def kx_market(ticker, label, bid, ask):
    return {"ticker": ticker, "status": "active", "yes_sub_title": label, "yes_bid_dollars": bid, "yes_ask_dollars": ask}


# --- Polymarket ---
def test_picks_matching_open_market():
    pm = odds.pick_polymarket(Q, odds.FIXTURE)
    assert pm["market"] == "Will Bitcoin hit $150k by December 31, 2026?"
    assert pm["yes_price"] == 0.028
    assert pm["implied_prob_pct"] == 2.8
    assert pm["url"] == "https://polymarket.com/event/when-will-bitcoin-hit-150k"


def test_skips_closed_markets():
    payload = {"events": [{"slug": "e", "markets": [market("Will Bitcoin hit $150k in 2026?", 0.9, closed=True)]}]}
    assert odds.pick_polymarket(Q, payload) is None


def test_numbers_must_agree():
    assert odds.match_score(Q, "Will Bitcoin hit $150k by June 30, 2027?") < odds.MIN_MATCH
    assert odds.match_score(Q, "Will Bitcoin hit $200k by December 31, 2026?") < odds.MIN_MATCH
    payload = {"events": [{"slug": "e", "markets": [market("Will Bitcoin hit $150k by June 30, 2027?", 0.15)]}]}
    assert odds.pick_polymarket(Q, payload) is None


def test_unrelated_market_not_matched():
    payload = {"events": [{"slug": "e", "markets": [market("Fed rate cut by December 2026 meeting?", 0.03)]}]}
    assert odds.pick_polymarket(Q, payload) is None


def test_k_suffix_matches_full_number():
    assert odds.tokens("$150k") == odds.tokens("$150,000") == {"150000"}


# --- Kalshi ---
def test_kalshi_multi_outcome_picks_price_level():
    k, err = odds.fixture_kalshi(Q)
    assert err is None
    assert k["ticker"] == "KXBTCMAXY-26-150000"
    assert k["yes_price"] == 0.04  # bid/ask midpoint
    assert k["url"] == "https://kalshi.com/markets/kxbtcmaxy"


def test_kalshi_year_in_subtitle_does_not_count():
    # "Before Jan 1, 2027" sub_title must not make a 2026 market match a 2027 question.
    assert odds.fixture_kalshi("Will Bitcoin hit 150k in 2027")[0] is None
    assert odds.fixture_kalshi("Will Bitcoin hit 300k in 2026")[0] is None


def test_kalshi_ambiguous_outcomes_not_guessed():
    idx = kx_index({"event_ticker": "N", "series_ticker": "KXNATO", "title": "Who will be the next Secretary General of NATO?", "sub_title": "Before 2099"})
    mk = {"N": [kx_market("a", "Keir Starmer", "0.15", "0.23"), kx_market("b", "Kaja Kallas", "0.17", "0.20")]}
    assert odds.pick_kalshi("Who will be the next NATO Secretary General?", idx, mk.get) is None
    named = odds.pick_kalshi("Will Keir Starmer be the next NATO Secretary General?", idx, mk.get)
    assert named["ticker"] == "a"
    assert named["market"].endswith(": Keir Starmer")


def test_kalshi_index_paginates_and_flags_truncation():
    pages = {None: {"events": [{"event_ticker": "A", "title": "x"}], "cursor": "c1"}, "c1": {"events": [{"event_ticker": "B", "title": "y"}], "cursor": ""}}
    events, truncated = odds.build_kalshi_index(lambda url, p: pages[p.get("cursor")], pause=0)
    assert [e["event_ticker"] for e in events] == ["A", "B"] and truncated is False
    endless = lambda url, p: {"events": [{"event_ticker": "A", "title": "x"}], "cursor": "more"}  # noqa: E731
    assert odds.build_kalshi_index(endless, max_pages=3, pause=0)[1] is True


# --- combined ---
def test_fail_soft_when_sources_down():
    out = odds.market_odds("some new question", fetch=lambda q: None, kalshi=lambda q: (None, "kalshi_index_warming"))
    assert out["polymarket"] is None and out["kalshi"] is None
    assert out["error"] == "odds_unavailable"
    assert out["kalshi_error"] == "kalshi_index_warming"
    assert "some new question" not in odds._cache


def test_brief_includes_both_venues():
    main.CACHE.clear()
    main.PREV.clear()
    odds._cache.clear()
    body = client.get("/brief", params={"q": Q}).json()
    assert body["odds"]["polymarket"]["implied_prob_pct"] == 2.8
    assert body["odds"]["kalshi"]["implied_prob_pct"] == 4.0
    assert "Polymarket Yes: 2.8%." in body["summary"]
    assert "Kalshi Yes: 4.0%." in body["summary"]
    schemas.BriefOut.model_validate(body)


def test_health_reports_odds_index():
    body = client.get("/health").json()
    assert "kalshi_events" in body["odds_index"]
    schemas.HealthOut.model_validate(body)


def test_sentiment_unchanged_no_odds():
    body = client.get("/sentiment", params={"q": Q}).json()
    assert "odds" not in body

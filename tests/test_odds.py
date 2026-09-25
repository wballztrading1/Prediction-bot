"""Polymarket odds matching and /brief enrichment. No network: fixtures only."""
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


def test_fail_soft_when_source_down():
    out = odds.market_odds("some new question", fetch=lambda q: None)
    assert out["polymarket"] is None
    assert out["error"] == "odds_unavailable"


def test_brief_includes_odds_and_summary():
    main.CACHE.clear()
    main.PREV.clear()
    odds._cache.clear()
    body = client.get("/brief", params={"q": Q}).json()
    assert body["odds"]["polymarket"]["implied_prob_pct"] == 2.8
    assert "Polymarket Yes: 2.8%." in body["summary"]
    schemas.BriefOut.model_validate(body)


def test_sentiment_unchanged_no_odds():
    body = client.get("/sentiment", params={"q": Q}).json()
    assert "odds" not in body

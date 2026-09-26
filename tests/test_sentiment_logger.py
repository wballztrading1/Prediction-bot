"""Sentiment logger: fake market + fake Grok, no network, no spend."""
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sentiment_logger as sl  # noqa: E402

NOW = datetime(2026, 10, 1, 14, 17, tzinfo=timezone.utc)


def fake_market(market_id):
    return {
        "question": f"Question {market_id}?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.42", "0.58"]',
        "bestBid": "0.41",
        "bestAsk": "0.43",
        "volume24hr": 1234.5,
        "closed": market_id == "1892495",
    }


def fake_score(question):
    return {"score": 150, "catalyst": " rally ", "volume_signal": "rising"}


def read(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def test_writes_one_row_per_market(tmp_path):
    path = tmp_path / "log.csv"
    sl.run(now=NOW, path=path, fetch=fake_market, score=fake_score)
    rows = read(path)
    assert len(rows) == len(sl.MARKETS)
    first = rows[0]
    assert first["yes_price"] == "0.42"
    assert first["score"] == "100"  # clamped
    assert first["catalyst"] == "rally"
    assert first["grok_called"] == "1"


def test_closed_market_not_scored(tmp_path):
    path = tmp_path / "log.csv"
    rows = sl.run(now=NOW, path=path, fetch=fake_market, score=fake_score)
    lynx = [r for r in rows if r["market_id"] == "1892495"][0]
    assert lynx["grok_called"] == "0"
    assert lynx["error"] == "market_closed"


def test_monthly_cap_stops_grok(tmp_path):
    path = tmp_path / "log.csv"
    calls = []

    def counting_score(q):
        calls.append(q)
        return fake_score(q)

    sl.run(now=NOW, path=path, fetch=fake_market, score=counting_score, max_calls=6)
    sl.run(now=NOW, path=path, fetch=fake_market, score=counting_score, max_calls=6)
    assert len(calls) == 6
    assert sl.calls_this_month(path, NOW) == 6
    assert "monthly_grok_cap_reached" in [r["error"] for r in read(path)]


def test_errors_are_recorded_not_raised(tmp_path):
    path = tmp_path / "log.csv"

    def broken_fetch(market_id):
        raise TimeoutError()

    rows = sl.run(now=NOW, path=path, fetch=broken_fetch, score=fake_score)
    assert all(r["error"] == "market_fetch_TimeoutError" for r in rows)


def test_parse_json_object():
    assert sl.parse_json_object('Here: {"score": 5} done') == {"score": 5}
    assert sl.parse_json_object("no json") is None

"""Free /scores tier built from the logger CSV. No network."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["TEST_MODE"] = "1"
os.environ.setdefault("XAI_API_KEY", "test")

import scores  # noqa: E402

HEADER = "date_utc,market_id,label,question,yes_price,best_bid,best_ask,volume_24h,closed,grok_called,score,catalyst,volume_signal,error\n"
CSV = HEADER + (
    "2026-10-02T14:17Z,1,Fed,Will the Fed cut?,0.60,,,,0,1,25,Jobs data,rising,\n"
    "2026-10-03T14:17Z,1,Fed,Will the Fed cut?,0.18,,,,0,1,-35,Inflation cooled,flat,\n"
    "2026-10-03T14:17Z,2,Iran,Ceasefire holds?,0.62,,,,0,1,-35,Violations,rising,\n"
    "2026-10-02T14:17Z,3,Lynx,Lynx win?,0.40,,,,0,1,10,Playoffs,rising,\n"
    "2026-10-03T14:17Z,3,Lynx,Lynx win?,0.0,,,,1,0,,,,market_closed\n"
    "2026-10-03T14:17Z,4,Likud,Likud most seats?,0.54,,,,0,0,,,,budget_exhausted\n"
)
NOW = datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc)


def test_latest_per_market_with_shift():
    body = scores.latest_scores(CSV, now=NOW)
    by_id = {m["market_id"]: m for m in body["markets"]}
    fed = by_id["1"]
    assert (fed["score"], fed["score_before"], fed["shift"]) == (-35, 25, -60)
    assert fed["polymarket_yes_price"] == 0.18
    assert fed["catalyst"] == "Inflation cooled" and fed["stale"] is False
    assert by_id["2"]["score_before"] is None and by_id["2"]["shift"] is None


def test_closed_and_never_scored_markets_left_out():
    ids = {m["market_id"] for m in scores.latest_scores(CSV, now=NOW)["markets"]}
    assert ids == {"1", "2"}


def test_stale_flag_after_36_hours():
    later = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
    assert all(m["stale"] for m in scores.latest_scores(CSV, now=later)["markets"])


def test_source_falls_back_to_bundled_file_and_caches():
    calls = []

    def broken():
        calls.append(1)
        raise OSError("github down")

    src = scores.ScoresSource(fetch=broken, ttl=60)
    first = src.get()
    assert first["data_origin"] == "bundled"
    assert src.get() is first and len(calls) == 1


def test_source_uses_remote_text():
    src = scores.ScoresSource(fetch=lambda: CSV, ttl=0)
    body = src.get()
    assert body["data_origin"] == "remote" and body["count"] == 2


def test_scores_route_is_free():
    from fastapi.testclient import TestClient

    import main

    r = TestClient(main.app).get("/scores")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1 and "note" in body
    assert {"question", "score", "scored_at"} <= set(body["markets"][0])
    free = [row["path"] for row in TestClient(main.app).get("/catalog").json()["free"]]
    assert "/scores" in free and "/mcp" in free

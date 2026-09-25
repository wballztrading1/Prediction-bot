import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["TEST_MODE"] = "1"
os.environ.setdefault("XAI_API_KEY", "test")
os.environ.setdefault("PAY_TO_ADDRESS", "0x0000000000000000000000000000000000000001")

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_health_ladder():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["price_lite"] == "$0.01"
    assert body["price_brief"] == "$0.05"
    assert "/sentiment" in body["routes"]["paid_lite"]
    assert "/brief" in body["routes"]["paid_brief"]


def test_free_catalog_sample_root():
    for path in ("/", "/catalog", "/sample"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.json()


def test_sentiment_requires_q():
    r = client.get("/sentiment")
    assert r.status_code == 200
    assert "error" in r.json()


def test_sentiment_lite_shape():
    main.CACHE.clear()
    main.PREV.clear()
    r = client.get("/sentiment", params={"q": "Will Bitcoin hit 150k in 2026"})
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "lite"
    assert -100 <= body["score"] <= 100
    assert body["volume_signal"] in ("rising", "falling", "flat")


def test_brief_includes_summary_and_shift():
    main.CACHE.clear()
    main.PREV.clear()
    r1 = client.get("/sentiment", params={"q": "Will Bitcoin hit 150k in 2026"})
    assert r1.status_code == 200
    key = "will bitcoin hit 150k in 2026"
    old = main.CACHE[key][1]
    main.CACHE[key] = (0, {**old, "score": -10})
    r2 = client.get("/brief", params={"q": "Will Bitcoin hit 150k in 2026"})
    assert r2.status_code == 200
    body = r2.json()
    assert body["tier"] == "brief"
    assert "summary" in body
    assert "shift" in body


def test_shift_no_prior_note():
    main.CACHE.clear()
    main.PREV.clear()
    r = client.get("/shift", params={"q": "Unique market ABC never seen"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("note") == "no_prior_score"
    assert body["shift"] == 0


def test_top_shape():
    main.CACHE.clear()
    r = client.get("/top")
    assert r.status_code == 200
    body = r.json()
    assert "markets" in body
    assert isinstance(body["markets"], list)


def test_normalize_clamps():
    out = main.normalize_score_payload({"score": 999, "volume_signal": "nope"}, question="q")
    assert out["score"] == 100
    assert out["volume_signal"] == "flat"
    assert out["question"] == "q"

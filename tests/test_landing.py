"""Landing page (/about) and agent summary (/llms.txt)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TEST_MODE"] = "1"
os.environ.setdefault("XAI_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def test_about_is_html_with_live_prices():
    r = client.get("/about")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "{{" not in body
    assert main.PRICE_LITE in body and main.PRICE_BRIEF in body
    assert main.PAY_TO in body
    assert "prediction-bot-mcp" in body
    for link in ("/catalog", "/docs", "/llms.txt"):
        assert f'href="{link}"' in body


def test_llms_txt_is_plain_text_summary():
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "{{" not in body
    assert body.startswith("# Prediction Market X Sentiment API")
    for route in ("/top", "/shift?q=", "/sentiment?q=", "/brief?q="):
        assert route in body
    assert main.PUBLIC_BASE in body


def test_root_still_json_for_agents():
    r = client.get("/")
    assert r.headers["content-type"].startswith("application/json")
    paths = [row["path"] for row in r.json()["free"]]
    assert "/about" in paths and "/llms.txt" in paths

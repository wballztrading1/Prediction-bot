"""MCP server tests. Run against the FastAPI app in TEST_MODE; no network, no wallet."""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_server"))

os.environ["TEST_MODE"] = "1"
os.environ.setdefault("XAI_API_KEY", "test")

import main  # noqa: E402
from prediction_bot_mcp.server import (  # noqa: E402
    PredictionBotAPI,
    Settings,
    build_server,
    decode_payment_required,
)

BASE = "http://testserver"


def run(coro):
    return asyncio.run(coro)


def asgi_factory():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=BASE)


QUOTE = {
    "x402Version": 2,
    "accepts": [
        {
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": "50000",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "payTo": "0x0000000000000000000000000000000000000001",
        }
    ],
}


def payment_required_factory():
    """Simulates the live service: free routes via app, paid routes answer 402."""

    async def handler(request: httpx.Request):
        if request.url.path in ("/top", "/shift", "/sentiment", "/brief"):
            header = base64.b64encode(json.dumps(QUOTE).encode()).decode()
            return httpx.Response(402, headers={"PAYMENT-REQUIRED": header}, json={})
        async with asgi_factory() as c:
            r = await c.get(request.url.path, params=request.url.params)
        return httpx.Response(r.status_code, content=r.content, headers=r.headers)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE)


def settings(**env):
    return Settings({"PREDICTION_BOT_API_BASE": BASE, **env})


def test_free_tools_hit_free_routes():
    api = PredictionBotAPI(settings(), http_factory=asgi_factory)
    cat = run(api.get_free("/catalog"))
    assert cat["network"] == "eip155:8453"
    assert run(api.get_free("/pricing"))["price_brief"] == "$0.05"
    assert run(api.prices()) == {"lite": 0.01, "full": 0.05}


def test_paid_without_wallet_returns_quote_not_payment():
    api = PredictionBotAPI(settings(), http_factory=payment_required_factory())
    assert not api.can_pay
    out = run(api.get_paid("/brief", {"q": "Will Bitcoin hit 150k in 2026"}))
    assert out["payment_required"] is True
    assert out["price_usd"] == 0.05
    assert out["accepts"][0]["amount_usd"] == 0.05
    assert out["accepts"][0]["network"] == "eip155:8453"
    assert api.spent_usd == 0


def test_paid_with_wallet_tracks_spend_and_budget():
    # Paying client stubbed with the TEST_MODE app (no real signing / USDC).
    main.CACHE.clear()
    main.PREV.clear()
    api = PredictionBotAPI(
        settings(PREDICTION_BOT_SESSION_BUDGET_USD="0.06"),
        http_factory=asgi_factory,
        paying_http_factory=asgi_factory,
    )
    out = run(api.get_paid("/sentiment", {"q": "Will Bitcoin hit 150k in 2026"}))
    assert out["tier"] == "sentiment"
    assert out["_paid_usd"] == 0.05
    assert run(api.get_paid("/top"))["_session_spent_usd"] == 0.06
    blocked = run(api.get_paid("/top"))
    assert blocked["error"] == "session_budget_exhausted"


def test_per_call_cap_blocks_full_tier():
    api = PredictionBotAPI(
        settings(PREDICTION_BOT_MAX_USD_PER_CALL="0.01"),
        http_factory=asgi_factory,
        paying_http_factory=asgi_factory,
    )
    assert run(api.get_paid("/brief", {"q": "x"}))["error"] == "over_per_call_cap"
    assert "markets" in run(api.get_paid("/top"))


def test_decode_payment_required_body_fallback():
    r = httpx.Response(402, json=QUOTE)
    assert decode_payment_required(r)["accepts"][0]["amount"] == "50000"


def test_server_registers_tools():
    pytest.importorskip("mcp")
    server = build_server(PredictionBotAPI(settings(), http_factory=asgi_factory))
    names = {t.name for t in run(server.list_tools())}
    assert names == {
        "get_daily_scores", "get_catalog", "get_pricing", "get_sample", "get_health",
        "get_top_markets", "get_sentiment_shift", "get_market_sentiment", "get_market_brief",
    }


def test_scores_tool_is_free():
    api = PredictionBotAPI(settings(), http_factory=asgi_factory)
    body = run(api.get_free("/scores"))
    assert body["count"] >= 1 and api.spent_usd == 0


def test_hosted_mode_never_holds_a_wallet():
    s = Settings(
        {"PREDICTION_BOT_API_BASE": BASE, "PREDICTION_BOT_EVM_PRIVATE_KEY": "0x" + "11" * 32},
        hosted=True,
    )
    api = PredictionBotAPI(s, http_factory=payment_required_factory())
    assert s.private_key is None and not api.can_pay
    out = run(api.get_paid("/sentiment", {"q": "Will the Fed cut rates"}))
    assert out["payment_required"] is True
    assert "never pays" in out["how_to_pay"] and "x402" in out["how_to_pay"]


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_hosted_mcp_endpoint_end_to_end():
    """The real /mcp mount: initialize, list tools, call the free daily-scores tool."""
    pytest.importorskip("mcp")
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:  # runs the lifespan that starts the session manager
        init = c.post(
            "/mcp",
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert init.status_code == 200, init.text
        info = init.json()["result"]["serverInfo"]
        assert info["name"] == "prediction-bot" and info["version"]

        hdrs = {**MCP_HEADERS, "MCP-Protocol-Version": "2025-11-25"}
        listed = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed.status_code == 200, listed.text
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        tools = {t["name"]: t for t in listed.json()["result"]["tools"]}
        assert {"get_daily_scores", "get_market_sentiment", "get_market_brief"} <= names
        # What directory quality checks look for: parameter docs, output schemas, annotations.
        q = tools["get_market_sentiment"]["inputSchema"]["properties"]["q"]
        assert q.get("description") and q.get("maxLength") == 200
        for t in tools.values():
            assert t.get("outputSchema"), t["name"]
            assert t.get("annotations", {}).get("title"), t["name"]
        assert tools["get_daily_scores"]["annotations"]["readOnlyHint"] is True
        assert tools["get_market_brief"]["annotations"]["readOnlyHint"] is False

        called = c.post(
            "/mcp",
            headers=hdrs,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_daily_scores", "arguments": {}},
            },
        )
        assert called.status_code == 200, called.text
        result = called.json()["result"]
        assert not result.get("isError"), result
        payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
        if "count" not in payload and isinstance(payload.get("result"), dict):
            payload = payload["result"]
        assert payload["count"] >= 1

        # Free REST routes still answer next to the mount.
        assert c.get("/health").json()["status"] == "ok"


def test_icon_routes():
    from fastapi.testclient import TestClient

    c = TestClient(main.app)
    r = c.get("/icon.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get("/favicon.ico").status_code == 200
    assert 'rel="icon"' in c.get("/about").text


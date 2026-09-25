"""OpenAPI docs describe every route; runtime responses still match the models."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TEST_MODE"] = "1"
os.environ.setdefault("XAI_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import schemas  # noqa: E402

client = TestClient(main.app)
Q = "Will Bitcoin hit 150k in 2026"


def spec():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    return r.json()


def test_paid_routes_document_q_and_402():
    paths = spec()["paths"]
    for path in ("/sentiment", "/brief", "/shift"):
        op = paths[path]["get"]
        names = [p["name"] for p in op.get("parameters", [])]
        assert "q" in names, path
        assert "402" in op["responses"], path
        assert "x402" in op["responses"]["402"]["description"]
    assert "402" in paths["/top"]["get"]["responses"]


def test_tags_and_prices_in_docs():
    paths = spec()["paths"]
    assert paths["/sentiment"]["get"]["tags"] == ["paid-full"]
    assert paths["/top"]["get"]["tags"] == ["paid-lite"]
    assert paths["/health"]["get"]["tags"] == ["free"]
    assert "$0.05" in paths["/brief"]["get"]["responses"]["402"]["description"]
    assert "$0.01" in paths["/shift"]["get"]["responses"]["402"]["description"]


def test_component_schemas_present():
    comps = spec()["components"]["schemas"]
    for name in ("SentimentOut", "BriefOut", "ShiftOut", "TopOut", "HealthOut", "CatalogOut"):
        assert name in comps, name
    assert comps["SentimentOut"]["properties"]["score"]["maximum"] == 100


def test_runtime_payloads_match_models():
    main.CACHE.clear()
    main.PREV.clear()
    schemas.SentimentOut.model_validate(client.get("/sentiment", params={"q": Q}).json())
    schemas.BriefOut.model_validate(client.get("/brief", params={"q": Q}).json())
    schemas.ShiftOut.model_validate(client.get("/shift", params={"q": Q}).json())
    main.CACHE.clear()
    schemas.TopOut.model_validate(client.get("/top").json())
    schemas.HealthOut.model_validate(client.get("/health").json())
    schemas.PricingOut.model_validate(client.get("/pricing").json())
    schemas.CatalogOut.model_validate(client.get("/catalog").json())
    schemas.SampleOut.model_validate(client.get("/sample").json())
    schemas.MissingQueryOut.model_validate(client.get("/brief").json())


def test_catalog_advertises_mcp():
    assert "prediction-bot-mcp" in client.get("/catalog").json()["mcp"]

"""Bazaar listing metadata. Pure checks, no network, no wallet."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import discovery  # noqa: E402
from schemas import BriefOut, SentimentOut, ShiftOut, TopOut  # noqa: E402

PAID_ROUTES = ["GET /sentiment", "GET /brief", "GET /shift", "GET /top"]
MODELS = {
    "GET /sentiment": SentimentOut,
    "GET /brief": BriefOut,
    "GET /shift": ShiftOut,
    "GET /top": TopOut,
}


def test_every_paid_route_has_example_and_description():
    descs = discovery.descriptions("$0.35", "$0.35")
    assert sorted(discovery.EXAMPLES) == sorted(PAID_ROUTES)
    assert sorted(descs) == sorted(PAID_ROUTES)
    for route in PAID_ROUTES:
        assert len(descs[route]) >= 120, route


@pytest.mark.parametrize("route", PAID_ROUTES)
def test_examples_match_response_schemas(route):
    # The listing shows these to buyers, so they must be valid responses.
    MODELS[route].model_validate(discovery.EXAMPLES[route])


def test_brief_example_shows_both_venues():
    odds = discovery.BRIEF_EXAMPLE["odds"]
    assert odds["polymarket"]["source"] == "polymarket"
    assert odds["kalshi"]["source"] == "kalshi"


def test_descriptions_use_env_prices():
    descs = discovery.descriptions("$0.11", "$0.22")
    assert "$0.22" in descs["GET /sentiment"] and "$0.22" in descs["GET /brief"]
    assert "$0.11" in descs["GET /shift"] and "$0.11" in descs["GET /top"]
    for text in descs.values():
        assert "$0.35" not in text and "$0.05" not in text and "$0.01" not in text


def test_with_listing_adds_fields_and_keeps_declaration():
    declared = {"bazaar": {"info": {"input": {"type": "http"}}, "schema": {"type": "object"}}}
    out = discovery.with_listing(declared)
    bazaar = out["bazaar"]
    assert bazaar["discoverable"] is True
    assert bazaar["serviceName"] == discovery.SERVICE_NAME
    assert bazaar["category"] == discovery.CATEGORY
    assert bazaar["tags"] == ["prediction-markets", "polymarket", "kalshi", "x-sentiment"]
    assert bazaar["info"] == declared["bazaar"]["info"]
    assert bazaar["schema"] == declared["bazaar"]["schema"]
    assert "discoverable" not in declared["bazaar"]  # input not mutated


def test_with_real_x402_declaration():
    bazaar_mod = pytest.importorskip("x402.extensions.bazaar")
    declared = bazaar_mod.declare_discovery_extension(
        input=dict(discovery.Q_INPUT),
        input_schema=discovery.Q_SCHEMA,
        output=bazaar_mod.OutputConfig(example=discovery.SENTIMENT_EXAMPLE),
    )
    bazaar = discovery.with_listing(declared)["bazaar"]
    assert bazaar["info"]["input"]["queryParams"] == discovery.Q_INPUT
    assert bazaar["info"]["output"]["example"] == discovery.SENTIMENT_EXAMPLE
    assert bazaar["tags"] == discovery.TAGS

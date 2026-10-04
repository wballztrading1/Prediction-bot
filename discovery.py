"""Bazaar (x402 discovery) listing metadata for the paid routes.

Kept free of x402 imports so tests can check it without the payment stack.
main.py passes each route's ``declare_discovery_extension(...)`` output through
``with_listing`` to add the listing fields the Bazaar indexes: ``discoverable``,
``category`` and ``tags`` (documented in the x402 seller quickstart) plus
``serviceName`` (the name the CDP Bazaar shows; best effort, not in the SDK).
"""

from __future__ import annotations

import copy

SERVICE_NAME = "Prediction Market X Sentiment"
CATEGORY = "Data"
TAGS = ["prediction-markets", "polymarket", "kalshi", "x-sentiment"]

EXAMPLE_Q = "Will the Fed cut rates in October 2026"
SCORED_AT = "2026-10-03T14:17:00+00:00"
PRIOR_AT = "2026-10-02T14:17:00+00:00"

SENTIMENT_EXAMPLE = {
    "question": EXAMPLE_Q,
    "score": 45,
    "catalyst": "Soft jobs report and dovish Fed speakers boosted cut expectations.",
    "volume_signal": "rising",
    "scored_at": SCORED_AT,
    "tier": "sentiment",
}

SHIFT_EXAMPLE = {
    "question": EXAMPLE_Q,
    "score_now": 45,
    "score_before": 20,
    "shift": 25,
    "catalyst": "Soft jobs report and dovish Fed speakers boosted cut expectations.",
    "scored_at": SCORED_AT,
    "prior_scored_at": PRIOR_AT,
}

BRIEF_EXAMPLE = {
    "question": EXAMPLE_Q,
    "score": 45,
    "catalyst": "Soft jobs report and dovish Fed speakers boosted cut expectations.",
    "volume_signal": "rising",
    "shift": 25,
    "score_before": 20,
    "summary": "X leans clearly toward a cut (+45, up 25 since yesterday) while markets price it near 68%.",
    "scored_at": SCORED_AT,
    "odds": {
        "polymarket": {
            "source": "polymarket",
            "market": "Fed decreases interest rates by 25 bps after October 2026 meeting?",
            "yes_price": 0.685,
            "implied_prob_pct": 68.5,
            "best_bid": 0.68,
            "best_ask": 0.69,
            "url": "https://polymarket.com/event/fed-decision-in-october",
            "match_score": 0.8,
        },
        "kalshi": {
            "source": "kalshi",
            "market": "Fed rate cut in October 2026?",
            "ticker": "KXFEDDECISION-26OCT-C25",
            "yes_price": 0.66,
            "implied_prob_pct": 66.0,
            "best_bid": 0.65,
            "best_ask": 0.67,
            "url": "https://kalshi.com/markets/kxfeddecision",
            "match_score": 0.75,
        },
        "fetched_at": SCORED_AT,
    },
    "tier": "brief",
}

TOP_EXAMPLE = {
    "markets": [
        {
            "question": "Fed decreases interest rates by 25 bps after October 2026 meeting?",
            "score": 45,
            "catalyst": "Soft jobs report and dovish Fed speakers.",
            "volume_signal": "rising",
            "scored_at": SCORED_AT,
        },
        {
            "question": "US x Iran ceasefire holds through October 31?",
            "score": -35,
            "catalyst": "Reports of renewed strikes near the border.",
            "volume_signal": "rising",
            "scored_at": SCORED_AT,
        },
        {
            "question": "Likud wins the most seats in the 2026 Israeli election?",
            "score": 20,
            "catalyst": "New polls show Likud ahead of the main opposition bloc.",
            "volume_signal": "flat",
            "scored_at": SCORED_AT,
        },
    ],
    "scored_at": SCORED_AT,
}

EXAMPLES = {
    "GET /sentiment": SENTIMENT_EXAMPLE,
    "GET /brief": BRIEF_EXAMPLE,
    "GET /shift": SHIFT_EXAMPLE,
    "GET /top": TOP_EXAMPLE,
}

Q_SCHEMA = {
    "properties": {
        "q": {
            "type": "string",
            "maxLength": 200,
            "description": (
                "Polymarket or Kalshi market question in plain words, "
                "e.g. 'Will the Fed cut rates in October 2026'"
            ),
        }
    },
    "required": ["q"],
}
Q_INPUT = {"q": EXAMPLE_Q}


def descriptions(price_lite: str, price_brief: str) -> dict[str, str]:
    """Route descriptions for the Bazaar listing. Prices come from env, never hardcoded."""
    return {
        "GET /sentiment": (
            "Live X (Twitter) sentiment for any Polymarket or Kalshi prediction market. "
            "Pass the market question as q; Grok reads the last 3 days of X posts and returns "
            "a score from -100 (very bearish on the question) to +100 (very bullish), the "
            "one-line catalyst driving the chatter, and whether discussion volume is rising, "
            f"flat or falling. {price_brief} per call."
        ),
        "GET /brief": (
            "Full prediction-market brief for agents: X sentiment score (-100..+100), catalyst, "
            "volume trend, change since the last score, a one-line summary, and the live "
            "Polymarket and Kalshi Yes prices for the matched market, so you can see where the "
            f"crowd on X and the market price disagree. Pass the market question as q. {price_brief} per call."
        ),
        "GET /shift": (
            "Sentiment shift detector for Polymarket and Kalshi markets: the current X sentiment "
            "score minus the previous score, with timestamps and the catalyst, to catch narrative "
            f"flips between polls. Pass the market question as q. {price_lite} per call."
        ),
        "GET /top": (
            "The 3 Polymarket/Kalshi prediction markets most discussed on X right now, each with "
            "an X sentiment score (-100..+100), catalyst and volume trend. No input needed. "
            f"{price_lite} per scan."
        ),
    }


def with_listing(extension: dict) -> dict:
    """Add Bazaar listing fields to a ``declare_discovery_extension`` result.

    Returns a new dict; ``info`` and ``schema`` are left exactly as declared.
    """
    out = copy.deepcopy(extension)
    bazaar = out.setdefault("bazaar", {})
    bazaar["discoverable"] = True
    bazaar["serviceName"] = SERVICE_NAME
    bazaar["category"] = CATEGORY
    bazaar["tags"] = list(TAGS)
    return out

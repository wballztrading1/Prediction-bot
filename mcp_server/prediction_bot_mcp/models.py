"""Output models for the MCP tools.

They give each tool a published output schema. Every field is optional and extra
keys are allowed, so a model never rejects a real API response (or a payment
quote, which paid tools return when no payment was made); the schema documents
the common shape rather than enforcing it.
"""


from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- free -------------------------------------------------------------------
class ScoredMarket(_Open):
    market_id: Optional[str] = Field(None, description="Polymarket market id")
    label: Optional[str] = Field(None, description="Short market label")
    question: Optional[str] = Field(None, description="Market question")
    score: Optional[int | float] = Field(None, description="X sentiment: -100 very bearish .. +100 very bullish")
    score_before: Optional[int | float] = Field(None, description="Previous daily score, if any")
    shift: Optional[int | float] = Field(None, description="score minus score_before")
    catalyst: Optional[str] = Field(None, description="One-sentence driver of the chatter")
    volume_signal: Optional[str] = Field(None, description="rising, falling or flat")
    polymarket_yes_price: Optional[float] = Field(None, description="Polymarket Yes price (0..1) at scoring time")
    scored_at: Optional[str] = Field(None, description="ISO-8601 UTC time of the score")
    prior_scored_at: Optional[str] = None
    stale: Optional[bool] = Field(None, description="True when the score is more than 36 hours old")


class DailyScores(_Open):
    markets: list[ScoredMarket] = Field(default_factory=list)
    count: Optional[int | float] = None
    as_of: Optional[str] = Field(None, description="Time of the newest score")
    note: Optional[str] = None


class Catalog(_Open):
    service: Optional[str] = None
    base_url: Optional[str] = None
    network: Optional[str] = Field(None, description="Payment network (CAIP-2), e.g. eip155:8453 for Base")
    asset: Optional[str] = None
    pay_to: Optional[str] = None
    free: Optional[list[dict[str, Any]]] = Field(None, description="Free routes")
    paid: Optional[list[dict[str, Any]]] = Field(None, description="Paid routes with prices")


class Pricing(_Open):
    currency: Optional[str] = None
    network: Optional[str] = None
    price_lite: Optional[str] = Field(None, description="Price of /top and /shift, e.g. $0.35")
    price_brief: Optional[str] = Field(None, description="Price of /sentiment and /brief, e.g. $0.35")
    ladder: Optional[dict[str, Any]] = None


class Sample(_Open):
    demo: Optional[bool] = None
    note: Optional[str] = None
    example_request: Optional[str] = None
    example_response: Optional[dict[str, Any]] = None


class Health(_Open):
    status: Optional[str] = None
    price_lite: Optional[str] = None
    price_brief: Optional[str] = None
    network: Optional[str] = None
    routes: Optional[dict[str, Any]] = None


# --- paid -------------------------------------------------------------------
class PaymentOption(_Open):
    scheme: Optional[str] = None
    network: Optional[str] = None
    pay_to: Optional[str] = None
    asset: Optional[str] = None
    amount_atomic: Optional[str | int] = None
    amount_usd: Optional[float] = None


class _Paid(_Open):
    """Fields present when the call was not paid (quote) or was blocked by a cap."""

    payment_required: Optional[bool] = Field(
        None, description="True when no payment was made; accepts and how_to_pay say how to pay"
    )
    price_usd: Optional[float] = None
    accepts: Optional[list[PaymentOption]] = None
    how_to_pay: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = Field(None, description="Set when a spend cap blocked the call")


class MarketSentiment(_Paid):
    question: Optional[str] = None
    score: Optional[int | float] = Field(None, description="-100 very bearish .. +100 very bullish")
    catalyst: Optional[str] = None
    volume_signal: Optional[str] = Field(None, description="rising, falling or flat")
    scored_at: Optional[str] = None


class MarketBrief(MarketSentiment):
    shift: Optional[int | float] = Field(None, description="Change since the previous score")
    score_before: Optional[int | float] = None
    summary: Optional[str] = Field(None, description="One-line summary")
    odds: Optional[dict[str, Any]] = Field(None, description="Live Polymarket and Kalshi Yes prices for the matched market")


class SentimentShift(_Paid):
    question: Optional[str] = None
    score_now: Optional[int | float] = None
    score_before: Optional[int | float] = None
    shift: Optional[int | float] = None
    catalyst: Optional[str] = None
    scored_at: Optional[str] = None
    prior_scored_at: Optional[str] = None


class TopMarkets(_Paid):
    markets: Optional[list[dict[str, Any]]] = Field(None, description="Up to 3 markets, each with score, catalyst, volume_signal")
    scored_at: Optional[str] = None

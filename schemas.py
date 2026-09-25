"""Response models for OpenAPI docs (/docs, /openapi.json).

Used only to document shapes for agents and crawlers. Handlers still return
plain dicts, so runtime responses are unchanged.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

VolumeSignal = Literal["rising", "falling", "flat"]
Q_DESCRIPTION = (
    "Exact Polymarket or Kalshi market question text, "
    "e.g. 'Will Bitcoin hit 150k in 2026'"
)
Q_EXAMPLE = "Will Bitcoin hit 150k in 2026"


class SentimentOut(BaseModel):
    question: str = Field(examples=[Q_EXAMPLE])
    score: int = Field(ge=-100, le=100, description="X sentiment: -100 very bearish .. 100 very bullish")
    catalyst: str = Field(description="One-sentence driver of current chatter", examples=["ETF inflows"])
    volume_signal: VolumeSignal = Field(description="Is discussion volume rising, falling or flat")
    scored_at: str = Field(description="ISO-8601 UTC time the score was computed")
    tier: Literal["sentiment"] = "sentiment"
    degraded: Optional[str] = Field(
        None, description="Set when a cached score is served because live scoring is limited"
    )


class PolymarketOdds(BaseModel):
    source: Literal["polymarket"] = "polymarket"
    market: str = Field(description="Matched Polymarket market question")
    yes_price: float = Field(ge=0, le=1, description="Yes outcome price (0..1)")
    implied_prob_pct: float = Field(ge=0, le=100, description="yes_price as a percentage")
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    volume_24h: Optional[float] = None
    url: Optional[str] = None
    match_score: float = Field(description="0..1 word-overlap score between q and the matched market")


class KalshiOdds(BaseModel):
    source: Literal["kalshi"] = "kalshi"
    market: str = Field(description="Matched Kalshi event title (and outcome for multi-outcome events)")
    ticker: Optional[str] = Field(None, description="Kalshi market ticker")
    yes_price: float = Field(ge=0, le=1, description="Yes price (0..1): bid/ask midpoint, else last trade")
    implied_prob_pct: float = Field(ge=0, le=100)
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    volume_24h: Optional[float] = None
    url: Optional[str] = None
    match_score: float


class OddsOut(BaseModel):
    polymarket: Optional[PolymarketOdds] = Field(
        None, description="Null when no open market matches q closely enough"
    )
    kalshi: Optional[KalshiOdds] = Field(
        None, description="Null when no open Kalshi market matches q closely enough"
    )
    fetched_at: str
    error: Optional[str] = Field(None, description="odds_unavailable if Polymarket did not respond")
    kalshi_error: Optional[str] = Field(
        None, description="kalshi_index_warming or kalshi_unavailable"
    )


class BriefOut(BaseModel):
    question: str = Field(examples=[Q_EXAMPLE])
    score: int = Field(ge=-100, le=100)
    catalyst: str
    volume_signal: VolumeSignal
    shift: int = Field(description="score minus previous cached score (0 if none)")
    score_before: int
    summary: str = Field(description="One-line human/agent readable summary")
    scored_at: Optional[str] = None
    odds: Optional[OddsOut] = Field(None, description="Live Polymarket and Kalshi odds for the matched market")
    tier: Literal["brief"] = "brief"
    degraded: Optional[str] = None


class ShiftOut(BaseModel):
    question: str = Field(examples=[Q_EXAMPLE])
    score_now: int = Field(ge=-100, le=100)
    score_before: int = Field(ge=-100, le=100)
    shift: int = Field(description="score_now minus score_before")
    catalyst: str
    scored_at: Optional[str] = None
    prior_scored_at: Optional[str] = None
    note: Optional[Literal["no_prior_score"]] = Field(
        None, description="Present when there is no earlier score to compare"
    )
    degraded: Optional[str] = None


class TopMarket(BaseModel):
    question: str
    score: int = Field(ge=-100, le=100)
    catalyst: str
    volume_signal: VolumeSignal
    scored_at: Optional[str] = None


class TopOut(BaseModel):
    markets: list[TopMarket] = Field(description="Up to 3 most-discussed markets on X")
    scored_at: str
    degraded: Optional[str] = None


class MissingQueryOut(BaseModel):
    error: str = Field(examples=["pass ?q=your+market+question"])


class UnavailableOut(BaseModel):
    error: str = Field(examples=["rate_limited"])
    question: str
    hint: str


class PaymentRequiredOut(BaseModel):
    """x402 v2: payment requirements are in the base64 PAYMENT-REQUIRED header."""

    x402Version: Optional[int] = None
    error: Optional[str] = None
    accepts: Optional[list[dict]] = None


class HealthRoutes(BaseModel):
    free: list[str]
    paid_lite: list[str]
    paid_brief: list[str]


class HealthOut(BaseModel):
    status: Literal["ok"]
    routes: HealthRoutes
    price_lite: str = Field(examples=["$0.01"])
    price_brief: str = Field(examples=["$0.05"])
    price: str
    cache_ttl_sec: int
    network: str = Field(examples=["eip155:8453"])
    test_mode: bool
    odds_index: Optional[dict] = Field(None, description="Kalshi events index size, age and status")


class PricingTier(BaseModel):
    price: str
    routes: list[str]


class PricingLadder(BaseModel):
    free: list[str]
    lite: PricingTier
    full: PricingTier


class PricingOut(BaseModel):
    currency: Literal["USDC"]
    network: str
    ladder: PricingLadder
    price_lite: str
    price_brief: str
    notes: str


class CatalogRoute(BaseModel):
    method: str
    path: str
    price: str
    desc: str
    query: Optional[dict[str, str]] = None


class CatalogDiscovery(BaseModel):
    keywords: list[str]
    bazaar: str


class CatalogOut(BaseModel):
    service: str
    base_url: str
    network: str
    asset: str
    pay_to: str
    discovery: CatalogDiscovery
    free: list[CatalogRoute]
    paid: list[CatalogRoute]
    docs: str
    demo_client: str
    mcp: Optional[str] = None


class SampleOut(BaseModel):
    demo: bool
    note: str
    example_request: str
    example_response: SentimentOut


def paid_responses(model, price: str) -> dict:
    """OpenAPI responses block shared by x402-paid routes."""
    return {
        200: {"model": model, "description": f"Paid result ({price} USDC on Base)"},
        402: {
            "model": PaymentRequiredOut,
            "description": (
                f"Payment required: {price} USDC on Base (eip155:8453) via x402. "
                "Read the base64 PAYMENT-REQUIRED header, pay, and retry with "
                "the PAYMENT-SIGNATURE header."
            ),
        },
        503: {
            "model": UnavailableOut,
            "description": "Payment accepted but scoring temporarily unavailable; retry shortly",
        },
    }

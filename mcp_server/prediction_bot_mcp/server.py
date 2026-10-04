"""MCP server for the Prediction Market X Sentiment API (x402).

Runs locally next to an agent (stdio transport), or hosted by the API itself at
/mcp (streamable HTTP; hosted mode never holds a wallet). Exposes:

Free tools (no wallet, no spend):
    get_daily_scores, get_catalog, get_pricing, get_sample, get_health

Paid tools (USDC on Base via x402):
    get_top_markets, get_sentiment_shift, get_market_sentiment, get_market_brief
    (current prices: the free get_pricing tool)

Paid tools only spend when the *agent operator* configures their own wallet via
PREDICTION_BOT_EVM_PRIVATE_KEY in their MCP client config. Without it, paid
tools return the HTTP 402 payment quote instead of paying. Spending is capped
per call (PREDICTION_BOT_MAX_USD_PER_CALL, default 0.50) and per session
(PREDICTION_BOT_SESSION_BUDGET_USD, default 1.00).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Annotated, Any, Callable, Optional

import httpx
from pydantic import Field

from . import __version__
from .models import (
    Catalog,
    DailyScores,
    Health,
    MarketBrief,
    MarketSentiment,
    Pricing,
    Sample,
    SentimentShift,
    TopMarkets,
)

DEFAULT_BASE = "https://prediction-bot-iggf.onrender.com"
USDC_DECIMALS = 6
DEFAULT_PRICES = {"lite": 0.35, "full": 0.35}
ROUTE_TIER = {"/top": "lite", "/shift": "lite", "/sentiment": "full", "/brief": "full"}
TIMEOUT = 90.0


LOCAL_HOW_TO_PAY = (
    "Set PREDICTION_BOT_EVM_PRIVATE_KEY (your own Base wallet holding USDC) in this MCP "
    "server's env to auto-pay, or call the URL with any x402 client."
)
HOSTED_HOW_TO_PAY = (
    "This hosted server never pays. Call the URL with any x402 client (USDC on Base), or run "
    "the local server (uvx prediction-bot-mcp) with your own wallet key to auto-pay. "
    "The free get_daily_scores tool has today's scores for the markets we track."
)


def _usd(value: str | float | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(str(value).replace("$", "").strip())
    except ValueError:
        return default


class Settings:
    def __init__(self, env: Optional[dict] = None, hosted: bool = False):
        env = os.environ if env is None else env
        self.hosted = hosted
        self.base_url = env.get("PREDICTION_BOT_API_BASE", DEFAULT_BASE).rstrip("/")
        # A hosted server is shared by many users, so it never pays for anyone.
        self.private_key = None if hosted else (env.get("PREDICTION_BOT_EVM_PRIVATE_KEY") or None)
        self.max_usd_per_call = _usd(env.get("PREDICTION_BOT_MAX_USD_PER_CALL"), 0.50)
        self.session_budget_usd = _usd(env.get("PREDICTION_BOT_SESSION_BUDGET_USD"), 1.00)


def decode_payment_required(resp: httpx.Response) -> dict:
    """Pull the x402 quote out of a 402 response (v2 header, else JSON body)."""
    header = resp.headers.get("payment-required")
    if header:
        try:
            return json.loads(base64.b64decode(header).decode("utf-8"))
        except Exception:
            pass
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"body": body}
    except Exception:
        return {"body": resp.text[:2000]}


def _summarize_accepts(quote: dict) -> list[dict]:
    out = []
    for opt in quote.get("accepts") or []:
        if not isinstance(opt, dict):
            continue
        amount = opt.get("amount") or opt.get("maxAmountRequired")
        usd = None
        try:
            usd = int(amount) / 10**USDC_DECIMALS
        except (TypeError, ValueError):
            pass
        out.append(
            {
                "scheme": opt.get("scheme"),
                "network": opt.get("network"),
                "pay_to": opt.get("payTo") or opt.get("pay_to"),
                "asset": opt.get("asset"),
                "amount_atomic": amount,
                "amount_usd": usd,
            }
        )
    return out


class PredictionBotAPI:
    """Thin async client over the HTTP API. `http_factory` is injectable for tests."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        http_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
        paying_http_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    ):
        self.settings = settings or Settings()
        self._http_factory = http_factory or (
            lambda: httpx.AsyncClient(base_url=self.settings.base_url, timeout=TIMEOUT)
        )
        self._paying_http_factory = paying_http_factory
        self.spent_usd = 0.0
        self._prices: Optional[dict] = None

    # --- wallet ---------------------------------------------------------
    @property
    def can_pay(self) -> bool:
        return bool(self.settings.private_key) or self._paying_http_factory is not None

    def _make_paying_client(self) -> httpx.AsyncClient:
        if self._paying_http_factory is not None:
            return self._paying_http_factory()
        # Imported lazily so free tools work without the wallet extras.
        from eth_account import Account
        from x402 import max_amount, prefer_network, x402Client
        from x402.http.clients import x402HttpxClient
        from x402.mechanisms.evm import EthAccountSigner
        from x402.mechanisms.evm.exact.register import register_exact_evm_client

        cap_atomic = int(round(self.settings.max_usd_per_call * 10**USDC_DECIMALS))
        client = x402Client()
        register_exact_evm_client(
            client,
            EthAccountSigner(Account.from_key(self.settings.private_key)),
            policies=[prefer_network("eip155:8453"), max_amount(cap_atomic)],
        )
        return x402HttpxClient(client, base_url=self.settings.base_url, timeout=TIMEOUT)

    # --- free -----------------------------------------------------------
    async def get_free(self, path: str) -> dict:
        async with self._http_factory() as http:
            resp = await http.get(path)
        resp.raise_for_status()
        return resp.json()

    async def prices(self) -> dict:
        if self._prices is None:
            try:
                p = await self.get_free("/pricing")
                self._prices = {
                    "lite": _usd(p.get("price_lite"), DEFAULT_PRICES["lite"]),
                    "full": _usd(p.get("price_brief"), DEFAULT_PRICES["full"]),
                }
            except Exception:
                self._prices = dict(DEFAULT_PRICES)
        return self._prices

    # --- paid -----------------------------------------------------------
    async def get_paid(self, path: str, params: Optional[dict] = None) -> dict:
        tier = ROUTE_TIER[path]
        price = (await self.prices())[tier]

        if not self.can_pay:
            async with self._http_factory() as http:
                resp = await http.get(path, params=params)
            if resp.status_code == 402:
                quote = decode_payment_required(resp)
                return {
                    "payment_required": True,
                    "route": path,
                    "price_usd": price,
                    "accepts": _summarize_accepts(quote),
                    "how_to_pay": HOSTED_HOW_TO_PAY if self.settings.hosted else LOCAL_HOW_TO_PAY,
                    "url": f"{self.settings.base_url}{path}",
                    "params": params or {},
                }
            resp.raise_for_status()
            return resp.json()

        if price > self.settings.max_usd_per_call + 1e-9:
            return {
                "error": "over_per_call_cap",
                "price_usd": price,
                "max_usd_per_call": self.settings.max_usd_per_call,
            }
        if self.spent_usd + price > self.settings.session_budget_usd + 1e-9:
            return {
                "error": "session_budget_exhausted",
                "spent_usd": round(self.spent_usd, 6),
                "session_budget_usd": self.settings.session_budget_usd,
            }

        async with self._make_paying_client() as http:
            resp = await http.get(path, params=params)
        if resp.status_code == 402:
            return {
                "error": "payment_not_accepted",
                "detail": _summarize_accepts(decode_payment_required(resp)),
                "hint": "Check the wallet holds USDC on Base and the price is within your cap.",
            }
        resp.raise_for_status()
        self.spent_usd += price
        data = resp.json()
        if isinstance(data, dict):
            data = {**data, "_paid_usd": price, "_session_spent_usd": round(self.spent_usd, 6)}
        return data


Q_DESCRIPTION = (
    "A Polymarket or Kalshi market question in plain words, e.g. "
    "'Will the Fed cut rates in October 2026'. Up to 200 characters."
)
ICON_URL = f"{DEFAULT_BASE}/icon.png"
# Module level, not inside build_server: this file uses postponed annotations, so
# the SDK resolves tool type hints from module globals.
Q = Annotated[str, Field(description=Q_DESCRIPTION, min_length=1, max_length=200)]


def _annotations(title: str, paid: bool):
    from mcp.types import ToolAnnotations

    if paid:
        # Not read-only: with a wallet configured (local server) the call spends USDC.
        return ToolAnnotations(
            title=title,
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=True,
        )
    return ToolAnnotations(title=title, read_only_hint=True, open_world_hint=True)


def build_server(api: Optional[PredictionBotAPI] = None):
    from mcp.server.mcpserver import MCPServer
    from mcp.types import Icon

    api = api or PredictionBotAPI()
    server = MCPServer(
        name="prediction-bot",
        title="Prediction Market X Sentiment",
        description=(
            "Polymarket and Kalshi prediction-market sentiment from X (Twitter), scored by Grok."
        ),
        version=__version__,
        website_url=f"{DEFAULT_BASE}/about",
        icons=[Icon(src=ICON_URL, mime_type="image/png", sizes=["256x256"])],
        instructions=(
            "Polymarket/Kalshi prediction-market sentiment scored from live X (Twitter) "
            "chatter via Grok. Start with get_daily_scores (free: today's scores for the "
            "markets we track). Other free tools: get_catalog, get_pricing, get_sample, "
            "get_health. Paid tools (get_market_sentiment, get_market_brief, "
            "get_sentiment_shift, get_top_markets) settle in USDC on Base via x402 and "
            "return a payment quote unless the operator configured a wallet."
        ),
    )

    def tool(name: str, title: str, paid: bool = False):
        return server.tool(name=name, title=title, annotations=_annotations(title, paid))

    @tool("get_daily_scores", "Daily market scores (free)")
    async def get_daily_scores() -> DailyScores:
        """Free. Latest daily X (Twitter) sentiment score for each prediction market we track
        (Polymarket), with the change since the previous day, the catalyst and the market's Yes
        price. For a fresh score on any other question use get_market_sentiment."""
        return await api.get_free("/scores")

    @tool("get_catalog", "Route catalog (free)")
    async def get_catalog() -> Catalog:
        """Free. Machine-readable catalog of every route, price, network and pay-to address."""
        return await api.get_free("/catalog")

    @tool("get_pricing", "Current prices (free)")
    async def get_pricing() -> Pricing:
        """Free. Current USDC prices for the paid tools."""
        return await api.get_free("/pricing")

    @tool("get_sample", "Example response (free)")
    async def get_sample() -> Sample:
        """Free. Static example of a sentiment response (not live data) to preview the shape."""
        return await api.get_free("/sample")

    @tool("get_health", "Service status (free)")
    async def get_health() -> Health:
        """Free. Service status, prices and the routes available."""
        return await api.get_free("/health")

    @tool("get_top_markets", "Most-discussed markets on X", paid=True)
    async def get_top_markets() -> TopMarkets:
        """Paid (see get_pricing). The three Polymarket/Kalshi markets most discussed on X right
        now, each with a sentiment score (-100..100), catalyst and volume trend."""
        return await api.get_paid("/top")

    @tool("get_sentiment_shift", "Sentiment change for a market", paid=True)
    async def get_sentiment_shift(q: Q) -> SentimentShift:
        """Paid (see get_pricing). Change in X sentiment for a market question since its previous
        score, with both timestamps and the catalyst."""
        return await api.get_paid("/shift", {"q": q})

    @tool("get_market_sentiment", "Live sentiment for a market", paid=True)
    async def get_market_sentiment(q: Q) -> MarketSentiment:
        """Paid (see get_pricing). Fresh X (Twitter) sentiment for any Polymarket or Kalshi market
        question: score -100..100, the catalyst driving the chatter and the volume trend."""
        return await api.get_paid("/sentiment", {"q": q})

    @tool("get_market_brief", "Market brief with live odds", paid=True)
    async def get_market_brief(q: Q) -> MarketBrief:
        """Paid (see get_pricing). Full brief for a market question: score, catalyst, volume trend,
        change since the previous score, a one-line summary and live Polymarket and Kalshi odds."""
        return await api.get_paid("/brief", {"q": q})

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()

"""MCP server for the Prediction Market X Sentiment API (x402).

Runs locally next to an agent (stdio transport). Exposes:

Free tools (no wallet, no spend):
    catalog, pricing, sample, health

Paid tools (USDC on Base via x402):
    top ($0.01), shift ($0.01), sentiment ($0.05), brief ($0.05)

Paid tools only spend when the *agent operator* configures their own wallet via
PREDICTION_BOT_EVM_PRIVATE_KEY in their MCP client config. Without it, paid
tools return the HTTP 402 payment quote instead of paying. Spending is capped
per call (PREDICTION_BOT_MAX_USD_PER_CALL, default 0.05) and per session
(PREDICTION_BOT_SESSION_BUDGET_USD, default 1.00).
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable, Optional

import httpx

DEFAULT_BASE = "https://prediction-bot-iggf.onrender.com"
USDC_DECIMALS = 6
DEFAULT_PRICES = {"lite": 0.01, "full": 0.05}
ROUTE_TIER = {"/top": "lite", "/shift": "lite", "/sentiment": "full", "/brief": "full"}
TIMEOUT = 90.0


def _usd(value: str | float | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(str(value).replace("$", "").strip())
    except ValueError:
        return default


class Settings:
    def __init__(self, env: Optional[dict] = None):
        env = os.environ if env is None else env
        self.base_url = env.get("PREDICTION_BOT_API_BASE", DEFAULT_BASE).rstrip("/")
        self.private_key = env.get("PREDICTION_BOT_EVM_PRIVATE_KEY") or None
        self.max_usd_per_call = _usd(env.get("PREDICTION_BOT_MAX_USD_PER_CALL"), 0.05)
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
                    "how_to_pay": (
                        "Set PREDICTION_BOT_EVM_PRIVATE_KEY (your own Base wallet holding "
                        "USDC) in this MCP server's env to auto-pay, or call the URL with "
                        "any x402 client."
                    ),
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


def build_server(api: Optional[PredictionBotAPI] = None):
    from mcp.server.mcpserver import MCPServer

    api = api or PredictionBotAPI()
    server = MCPServer(
        name="prediction-bot",
        instructions=(
            "Polymarket/Kalshi prediction-market sentiment scored from live X (Twitter) "
            "chatter via Grok. Start with the free tools (catalog, pricing, sample). "
            "Paid tools settle in USDC on Base via x402: top and shift cost $0.01, "
            "sentiment and brief cost $0.05. Paid tools return a payment quote unless "
            "the operator configured a wallet."
        ),
    )

    @server.tool()
    async def catalog() -> dict:
        """Free. Machine-readable catalog of every route, price, network and pay-to address."""
        return await api.get_free("/catalog")

    @server.tool()
    async def pricing() -> dict:
        """Free. Current USDC price ladder: lite ($0.01) and full ($0.05) tiers."""
        return await api.get_free("/pricing")

    @server.tool()
    async def sample() -> dict:
        """Free. Static example of a sentiment response (not live data) to preview the shape."""
        return await api.get_free("/sample")

    @server.tool()
    async def health() -> dict:
        """Free. Service liveness, price ladder and cache TTL."""
        return await api.get_free("/health")

    @server.tool()
    async def top() -> dict:
        """Paid $0.01. The three most-discussed Polymarket/Kalshi markets on X right now,
        each with a sentiment score (-100..100), catalyst and volume_signal."""
        return await api.get_paid("/top")

    @server.tool()
    async def shift(q: str) -> dict:
        """Paid $0.01. Change in X sentiment for a market question vs the previous
        cached score. q = exact Polymarket/Kalshi market question."""
        return await api.get_paid("/shift", {"q": q})

    @server.tool()
    async def sentiment(q: str) -> dict:
        """Paid $0.05. Live X (Twitter) sentiment for a Polymarket/Kalshi market question:
        score -100..100, catalyst, volume_signal. q = exact market question."""
        return await api.get_paid("/sentiment", {"q": q})

    @server.tool()
    async def brief(q: str) -> dict:
        """Paid $0.05. Agent briefing for a market question: score, catalyst, volume_signal,
        shift vs prior score and a one-line summary. q = exact market question."""
        return await api.get_paid("/brief", {"q": q})

    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()

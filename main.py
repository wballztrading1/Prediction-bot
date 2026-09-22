import os, json, re
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from openai import OpenAI

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

app = FastAPI(title="Prediction Market Sentiment")

XAI_KEY = os.environ PAY_TO = "0xda83f90adeb6c540c5c68f0d0656982603387db0"
PRICE = os.environ.get("PRICE", "$0.01")
NETWORK = "eip155:84532"

client = OpenAI(api_key=XAI_KEY, base_url="https://api.x.ai/v1")

facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(url="https://x402.org/facilitator")
)
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

routes = {
    "GET /sentiment": RouteConfig(
        accepts=[PaymentOption(
            scheme="exact", pay_to=PAY_TO,
            price=PRICE, network=NETWORK,
        )],
        mime_type="application/json",
        description="Sentiment score for a Polymarket or Kalshi market",
    ),
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

CACHE =
TTL = 300

def score_market(question: str) -> dict:
    key = question.strip().lower()
    now = datetime.now(timezone.utc).timestamp()
    hit = CACHE.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]

    prompt = (
        f"Search X for recent posts about this prediction market:\n"
        f"\"{question}\"\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"score": <int -100 to 100>, "catalyst": "<one sentence>", '
        '"volume_signal": "<rising|falling|flat>"}'
    )
    resp = client.responses.create(
        model="grok-4.7",
        input= ,
        tools=[{"type": "x_search"}],
    )
    text = resp.output_text
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {
        "score": 0, "catalyst": "parse error", "volume_signal": "flat"
    }
    data = question
    data["scored_at"] = datetime.now(timezone.utc).isoformat()
    CACHE = (now, data)
    return data

@app.get("/sentiment")
async def sentiment(request: Request):
    q = request.query_params.get("q", "").strip()
    if not q:
        return {"error": "pass ?q=your+market+question"}
    return score_market(q)

@app.get("/health")
async def health():
    return {"status": "ok"}

import os, json, re
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from openai import OpenAI

from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

app = FastAPI(title="Prediction Market Sentiment")

XAI_KEY = os.environ["XAI_API_KEY"]
PAY_TO = os.environ["PAY_TO_ADDRESS"]
PRICE = os.environ.get("PRICE", "$0.01")
NETWORK = "eip155:8453"
FACILITATOR_URL = os.environ.get("FACILITATOR_URL", "https://facilitator.xpay.sh")

client = OpenAI(api_key=XAI_KEY, base_url="https://api.x.ai/v1")

facilitator = HTTPFacilitatorClient(
    FacilitatorConfig(url=FACILITATOR_URL)
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
        service_name="Pred Sentiment",
        tags=["sentiment", "prediction", "crypto"],
        extensions=declare_discovery_extension(
            input={"q": "Will Bitcoin hit 150k in 2026"},
            input_schema={
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "Prediction market question",
                    }
                },
                "required": ["q"],
            },
            output=OutputConfig(
                example={
                    "score": -88,
                    "catalyst": "Market prices a low chance of 150k",
                    "volume_signal": "falling",
                    "question": "Will Bitcoin hit 150k in 2026",
                    "scored_at": "2026-09-22T19:20:47Z",
                }
            ),
        ),
    ),
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

CACHE = {}
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
        input=[{"role": "user", "content": prompt}],
        tools=[{"type": "x_search"}],
    )
    text = resp.output_text
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else {
        "score": 0, "catalyst": "parse error", "volume_signal": "flat"
    }
    data["question"] = question
    data["scored_at"] = datetime.now(timezone.utc).isoformat()
    CACHE[key] = (now, data)
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

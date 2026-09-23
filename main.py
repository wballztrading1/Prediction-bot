import os, json, re, time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai import OpenAI

from cdp.x402 import create_facilitator_config
from x402.extensions.bazaar import (
    OutputConfig,
    bazaar_resource_server_extension,
    declare_discovery_extension,
)
from x402.http import HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

app = FastAPI(title="Prediction Market Sentiment")

XAI_KEY = os.environ["XAI_API_KEY"]
PAY_TO = os.environ["PAY_TO_ADDRESS"]
PRICE = os.environ.get("PRICE", "$0.01")
NETWORK = "eip155:8453"
GROK_COST = float(os.environ.get("GROK_COST_USD", "0.02"))
CALLER_CAP_USD = float(os.environ.get("CALLER_CAP_USD", "0.40"))
CALLER_CAP = int(os.environ.get("CALLER_GROK_PER_HOUR", "20"))
GLOBAL_CAP = int(os.environ.get("GLOBAL_GROK_PER_HOUR", "60"))

client = OpenAI(api_key=XAI_KEY, base_url="https://api.x.ai/v1")

server = x402ResourceServer(HTTPFacilitatorClient(create_facilitator_config()))
server.register(NETWORK, ExactEvmServerScheme())
server.register_extension(bazaar_resource_server_extension)

def pay_route(description, example, input_schema=None, input_example=None):
    ext_kw = dict(output=OutputConfig(example=example))
    if input_schema:
        ext_kw["input"] = input_example or {}
        ext_kw["input_schema"] = input_schema
    return RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO, price=PRICE, network=NETWORK)],
        mime_type="application/json",
        description=description,
        extensions=declare_discovery_extension(**ext_kw),
    )

q_schema = {
    "properties": {
        "q": {"type": "string", "description": "Prediction market question from Polymarket or Kalshi"}
    },
    "required": ["q"],
}

routes = {
    "GET /sentiment": pay_route(
        "Sentiment score for a Polymarket or Kalshi market question",
        {"score": 12, "catalyst": "ETF inflows", "volume_signal": "rising",
         "question": "Will Bitcoin hit 150k in 2026", "scored_at": "2026-09-22T00:00:00+00:00"},
        q_schema, {"q": "Will Bitcoin hit 150k in 2026"},
    ),
    "GET /shift": pay_route(
        "Sentiment now vs last cached score for a prediction market question",
        {"question": "Will Bitcoin hit 150k in 2026", "score_now": 12, "score_before": -4,
         "shift": 16, "catalyst": "ETF inflows", "scored_at": "2026-09-22T00:00:00+00:00"},
        q_schema, {"q": "Will Bitcoin hit 150k in 2026"},
    ),
    "GET /top": pay_route(
        "Three prediction markets with the largest current X sentiment",
        {"markets": [{"question": "Will Bitcoin hit 150k in 2026", "score": 12,
                      "catalyst": "ETF inflows", "volume_signal": "rising"}],
         "scored_at": "2026-09-22T00:00:00+00:00"},
    ),
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

CACHE = {}
TTL = 300
WINDOW = 3600
usage = defaultdict(list)
blocked = {}

def caller_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"

def prune(bucket):
    cutoff = time.time() - WINDOW
    usage[bucket] = [t for t in usage[bucket] if t > cutoff]

def allow_grok(request: Request):
    cid = caller_id(request)
    if cid in blocked and time.time() < blocked[cid]:
        return False, "circuit_open"
    prune(cid)
    prune("__global__")
    if len(usage[cid]) >= CALLER_CAP or len(usage["__global__"]) >= GLOBAL_CAP:
        return False, "rate_limited"
    spent = len(usage[cid]) * GROK_COST
    if spent + GROK_COST > CALLER_CAP_USD:
        blocked[cid] = time.time() + WINDOW
        print(f"ALERT circuit_open caller={cid} spent={spent:.2f}")
        return False, "circuit_open"
    return True, "ok"

def mark_grok(request: Request):
    now = time.time()
    usage[caller_id(request)].append(now)
    usage["__global__"].append(now)

def grok_json(prompt: str):
    resp = client.responses.create(
        model="grok-4.7",
        input=[{"role": "user", "content": prompt}],
        tools=[{"type": "x_search"}],
    )
    text = resp.output_text
    m = re.search(r"[\{\[].*[\}\]]", text, re.S)
    return json.loads(m.group(0)) if m else {}

def score_market(question: str, request: Request):
    key = question.strip().lower()
    now = datetime.now(timezone.utc).timestamp()
    hit = CACHE.get(key)
    if hit and now - hit[0] < TTL:
        return hit[1]

    ok, reason = allow_grok(request)
    if not ok:
        if hit:
            data = dict(hit[1])
            data["degraded"] = reason
            return data
        return JSONResponse({"error": reason}, status_code=429)

    prompt = (
        f"Search X for recent posts about this prediction market:\n\"{question}\"\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"score": <int -100 to 100>, "catalyst": "<one sentence>", '
        '"volume_signal": "<rising|falling|flat>"}'
    )
    data = grok_json(prompt)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("score", 0)
    data.setdefault("catalyst", "parse error")
    data.setdefault("volume_signal", "flat")
    data["question"] = question
    data["scored_at"] = datetime.now(timezone.utc).isoformat()
    CACHE[key] = (now, data)
    mark_grok(request)
    return data

@app.get("/sentiment")
async def sentiment(request: Request):
    q = request.query_params.get("q", "").strip()
    if not q:
        return {"error": "pass ?q=your+market+question"}
    return score_market(q, request)

@app.get("/shift")
async def shift(request: Request):
    q = request.query_params.get("q", "").strip()
    if not q:
        return {"error": "pass ?q=your+market+question"}
    key = q.lower()
    before = CACHE.get(key)
    now_data = score_market(q, request)
    if isinstance(now_data, JSONResponse):
        return now_data
    prev = before[1]["score"] if before else now_data["score"]
    return {
        "question": q,
        "score_now": now_data["score"],
        "score_before": prev,
        "shift": now_data["score"] - prev,
        "catalyst": now_data.get("catalyst", ""),
        "scored_at": now_data.get("scored_at"),
        "degraded": now_data.get("degraded"),
    }

@app.get("/top")
async def top(request: Request):
    hit = CACHE.get("__top__")
    now = datetime.now(timezone.utc).timestamp()
    if hit and now - hit[0] < TTL:
        return hit[1]
    ok, reason = allow_grok(request)
    if not ok:
        if hit:
            data = dict(hit[1])
            data["degraded"] = reason
            return data
        return JSONResponse({"error": reason}, status_code=429)
    prompt = (
        "Search X for the three most discussed Polymarket or Kalshi markets right now. "
        "Return ONLY valid JSON, no markdown:\n"
        '{"markets":[{"question":"...","score":<int -100 to 100>,'
        '"catalyst":"<one sentence>","volume_signal":"<rising|falling|flat>"}]}'
    )
    data = grok_json(prompt)
    if not isinstance(data, dict) or "markets" not in data:
        data = {"markets": []}
    data["scored_at"] = datetime.now(timezone.utc).isoformat()
    CACHE["__top__"] = (now, data)
    mark_grok(request)
    return data

@app.get("/health")
async def health():
    return {"status": "ok", "routes": ["/sentiment", "/shift", "/top"]}

import os
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from openai import OpenAI

from landing import about_html, llms_txt
from schemas import (
    Q_DESCRIPTION,
    Q_EXAMPLE,
    BriefOut,
    CatalogOut,
    HealthOut,
    MissingQueryOut,
    PricingOut,
    SampleOut,
    SentimentOut,
    ShiftOut,
    TopOut,
    paid_responses,
)

# --- config -----------------------------------------------------------------
TEST_MODE = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")
XAI_KEY = os.environ.get("XAI_API_KEY", "test" if TEST_MODE else "")
if not TEST_MODE and not XAI_KEY:
    raise RuntimeError("XAI_API_KEY is required")
PAY_TO = os.environ.get("PAY_TO_ADDRESS", "0x0000000000000000000000000000000000000001")
PRICE_LITE = os.environ.get("PRICE_LITE", "$0.01")
PRICE_BRIEF = os.environ.get("PRICE_BRIEF", os.environ.get("PRICE", "$0.05"))
PRICE = PRICE_BRIEF  # backward compatible
NETWORK = "eip155:8453"
GROK_COST = float(os.environ.get("GROK_COST_USD", "0.02"))
CALLER_CAP_USD = float(os.environ.get("CALLER_CAP_USD", "0.40"))
CALLER_CAP = int(os.environ.get("CALLER_GROK_PER_HOUR", "20"))
GLOBAL_CAP = int(os.environ.get("GLOBAL_GROK_PER_HOUR", "60"))
PUBLIC_BASE = os.environ.get(
    "PUBLIC_BASE_URL", "https://prediction-bot-iggf.onrender.com"
).rstrip("/")

_lite_usd = float(PRICE_LITE.replace("$", "").strip() or "0")
_brief_usd = float(PRICE_BRIEF.replace("$", "").strip() or "0")
if _brief_usd < GROK_COST:
    print(
        f"ALERT PRICE_BRIEF {_brief_usd} < GROK_COST {GROK_COST}: "
        "each cache miss loses money. Raise PRICE_BRIEF or lower GROK_COST_USD."
    )
if _lite_usd < GROK_COST:
    print(
        f"ALERT PRICE_LITE {_lite_usd} < GROK_COST {GROK_COST}: "
        "lite path relies on cache; monitor margins."
    )

app = FastAPI(
    title="Prediction Market X Sentiment (x402)",
    description=(
        "Agent-native Polymarket/Kalshi sentiment from live X chatter. "
        "Pay USDC on Base via HTTP 402. Free: /, /health, /sample, /catalog, /pricing. "
        "Lite $0.01: /top, /shift. Full $0.05: /sentiment, /brief."
    ),
    version="1.2.0",
    servers=[{"url": PUBLIC_BASE}],
    openapi_tags=[
        {"name": "free", "description": "Discovery routes, no payment"},
        {"name": "paid-lite", "description": f"x402, {PRICE_LITE} USDC on Base"},
        {"name": "paid-full", "description": f"x402, {PRICE_BRIEF} USDC on Base"},
    ],
)

Q_PARAM = Query("", description=Q_DESCRIPTION, examples=[Q_EXAMPLE])

client = OpenAI(api_key=XAI_KEY or "test", base_url="https://api.x.ai/v1")

# Payment / Bazaar wiring (skipped in TEST_MODE so unit tests need no secrets)
routes = {}
if not TEST_MODE:
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

    server = x402ResourceServer(HTTPFacilitatorClient(create_facilitator_config()))
    server.register(NETWORK, ExactEvmServerScheme())
    server.register_extension(bazaar_resource_server_extension)

    def pay_route(description, example, price, input_schema=None, input_example=None):
        ext_kw = dict(output=OutputConfig(example=example))
        if input_schema:
            ext_kw["input"] = input_example or {}
            ext_kw["input_schema"] = input_schema
        return RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact", pay_to=PAY_TO, price=price, network=NETWORK
                )
            ],
            mime_type="application/json",
            description=description,
            extensions=declare_discovery_extension(**ext_kw),
        )

    q_schema = {
        "properties": {
            "q": {
                "type": "string",
                "description": (
                    "Exact Polymarket or Kalshi market question text "
                    "(e.g. Will Bitcoin hit 150k in 2026)"
                ),
            }
        },
        "required": ["q"],
    }

    SENTIMENT_EXAMPLE = {
        "score": 12,
        "catalyst": "ETF inflows",
        "volume_signal": "rising",
        "question": "Will Bitcoin hit 150k in 2026",
        "scored_at": "2026-09-22T00:00:00+00:00",
        "tier": "sentiment",
    }
    BRIEF_EXAMPLE = {
        "question": "Will Bitcoin hit 150k in 2026",
        "score": 12,
        "catalyst": "ETF inflows",
        "volume_signal": "rising",
        "shift": 16,
        "score_before": -4,
        "summary": "X chatter turned more bullish after ETF inflow headlines.",
        "scored_at": "2026-09-22T00:00:00+00:00",
        "tier": "brief",
    }
    SHIFT_EXAMPLE = {
        "question": "Will Bitcoin hit 150k in 2026",
        "score_now": 12,
        "score_before": -4,
        "shift": 16,
        "catalyst": "ETF inflows",
        "scored_at": "2026-09-22T00:00:00+00:00",
    }
    TOP_EXAMPLE = {
        "markets": [
            {
                "question": "Will Bitcoin hit 150k in 2026",
                "score": 12,
                "catalyst": "ETF inflows",
                "volume_signal": "rising",
            }
        ],
        "scored_at": "2026-09-22T00:00:00+00:00",
    }

    routes = {
        "GET /sentiment": pay_route(
            (
                "Polymarket/Kalshi X (Twitter) sentiment score for agents — "
                "Grok live search returns score -100..100, catalyst, and volume_signal. "
                "Full Grok X-sentiment at $0.05."
            ),
            SENTIMENT_EXAMPLE,
            PRICE_BRIEF,
            q_schema,
            {"q": "Will Bitcoin hit 150k in 2026"},
        ),
        "GET /brief": pay_route(
            (
                "Prediction-market briefing for AI agents: X sentiment score, "
                "catalyst, volume_signal, shift vs prior cache, and a one-line summary. "
                "Polymarket and Kalshi questions. Full brief at $0.05."
            ),
            BRIEF_EXAMPLE,
            PRICE_BRIEF,
            q_schema,
            {"q": "Will Bitcoin hit 150k in 2026"},
        ),
        "GET /shift": pay_route(
            (
                "Sentiment shift detector for Polymarket/Kalshi: current X score "
                "minus last cached score — catch narrative flips between agent polls. "
                "Lite discovery price $0.01 (aligns with Bazaar indexes)."
            ),
            SHIFT_EXAMPLE,
            PRICE_LITE,
            q_schema,
            {"q": "Will Bitcoin hit 150k in 2026"},
        ),
        "GET /top": pay_route(
            (
                "Top 3 Polymarket/Kalshi markets by live X (Twitter) discussion "
                "intensity with sentiment scores — agent discovery scan at $0.01 "
                "(aligns with Bazaar /top index pricing)."
            ),
            TOP_EXAMPLE,
            PRICE_LITE,
        ),
    }
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

# CACHE[key] = (unix_ts, payload)
# PREV[key] = payload displaced on last refresh (for /shift)
CACHE = {}
PREV = {}
TTL = 300
WINDOW = 3600
usage = defaultdict(list)
blocked = {}

SAMPLE_PAYLOAD = {
    "demo": True,
    "note": (
        "Free sample — not live Grok. Discovery /top+/shift $0.01; "
        "full /sentiment+/brief $0.05."
    ),
    "example_request": f"{PUBLIC_BASE}/sentiment?q=Will%20Bitcoin%20hit%20150k%20in%202026",
    "example_response": {
        "score": 12,
        "catalyst": "ETF inflows",
        "volume_signal": "rising",
        "question": "Will Bitcoin hit 150k in 2026",
        "scored_at": "2026-09-22T00:00:00+00:00",
        "tier": "sentiment",
    },
}


def catalog_body() -> dict:
    return {
        "service": "prediction-market-x-sentiment",
        "base_url": PUBLIC_BASE,
        "network": NETWORK,
        "asset": "USDC",
        "pay_to": PAY_TO,
        "discovery": {
            "keywords": [
                "polymarket",
                "kalshi",
                "prediction market",
                "sentiment",
                "x twitter",
                "grok",
                "x402",
                "agent",
            ],
            "bazaar": "Indexed via CDP facilitator when paid routes settle",
        },
        "free": [
            {"method": "GET", "path": "/", "price": "$0", "desc": "Service index for agents"},
            {"method": "GET", "path": "/health", "price": "$0", "desc": "Liveness + price ladder"},
            {"method": "GET", "path": "/sample", "price": "$0", "desc": "Static example JSON (no Grok)"},
            {"method": "GET", "path": "/catalog", "price": "$0", "desc": "Machine-readable route catalog"},
            {"method": "GET", "path": "/pricing", "price": "$0", "desc": "Explicit price ladder"},
            {"method": "GET", "path": "/about", "price": "$0", "desc": "Human-readable landing page"},
            {"method": "GET", "path": "/llms.txt", "price": "$0", "desc": "Plain-text summary for LLM agents"},
        ],
        "paid": [
            {
                "method": "GET",
                "path": "/top",
                "price": PRICE_LITE,
                "desc": "Three hottest markets on X — lite discovery $0.01",
            },
            {
                "method": "GET",
                "path": "/shift",
                "price": PRICE_LITE,
                "query": {"q": "market question"},
                "desc": "Delta vs prior cached score — lite discovery $0.01",
            },
            {
                "method": "GET",
                "path": "/sentiment",
                "price": PRICE_BRIEF,
                "query": {"q": "market question"},
                "desc": "Full Grok X sentiment score -100..100",
            },
            {
                "method": "GET",
                "path": "/brief",
                "price": PRICE_BRIEF,
                "query": {"q": "market question"},
                "desc": "Score + shift + one-line summary",
            },
        ],
        "docs": f"{PUBLIC_BASE}/docs",
        "demo_client": "See demo/pay_once.py in the GitHub repo",
        "mcp": (
            "uvx --from git+https://github.com/wballztrading1/Prediction-bot"
            "#subdirectory=mcp_server prediction-bot-mcp"
        ),
    }


def caller_id(request: Request) -> str:
    for header in ("cf-connecting-ip", "x-real-ip"):
        val = request.headers.get(header)
        if val:
            return val.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def prune(bucket):
    cutoff = time.time() - WINDOW
    usage[bucket] = [t for t in usage[bucket] if t > cutoff]


def allow_grok(request: Request):
    if TEST_MODE:
        return True, "ok"
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
    if TEST_MODE:
        return
    now = time.time()
    usage[caller_id(request)].append(now)
    usage["__global__"].append(now)


def normalize_score_payload(data: dict, question: Optional[str] = None) -> dict:
    if not isinstance(data, dict):
        data = {}
    out = dict(data)
    try:
        score = int(out.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    out["score"] = max(-100, min(100, score))
    catalyst = out.get("catalyst")
    out["catalyst"] = catalyst if isinstance(catalyst, str) and catalyst.strip() else "n/a"
    if out.get("volume_signal") not in ("rising", "falling", "flat"):
        out["volume_signal"] = "flat"
    if question is not None:
        out["question"] = question
    if "scored_at" not in out:
        out["scored_at"] = datetime.now(timezone.utc).isoformat()
    return out


def grok_json(prompt: str):
    if TEST_MODE:
        return {
            "score": 7,
            "catalyst": "unit-test fixture",
            "volume_signal": "flat",
            "markets": [
                {
                    "question": "Will Bitcoin hit 150k in 2026",
                    "score": 7,
                    "catalyst": "unit-test fixture",
                    "volume_signal": "flat",
                }
            ],
        }, None
    try:
        resp = client.responses.create(
            model="grok-4.7",
            input=[{"role": "user", "content": prompt}],
            tools=[{"type": "x_search"}],
        )
    except Exception as e:
        print(f"ALERT grok_api_error {type(e).__name__}: {e}")
        return None, "grok_error"

    text = getattr(resp, "output_text", None) or ""
    if not text and getattr(resp, "output", None):
        try:
            parts = []
            for item in resp.output:
                for block in getattr(item, "content", []) or []:
                    t = getattr(block, "text", None)
                    if t:
                        parts.append(t)
            text = "\n".join(parts)
        except Exception:
            text = ""

    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        print("ALERT grok_no_json")
        return None, "no_json"
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        print("ALERT grok_bad_json")
        return None, "bad_json"
    if not isinstance(parsed, dict):
        return None, "bad_json"
    return parsed, None


def commit_score(key: str, data: dict, now: float):
    old = CACHE.get(key)
    if old:
        PREV[key] = old[1]
    CACHE[key] = (now, data)


def paid_unavailable(question: str, reason: str):
    return JSONResponse(
        {
            "error": reason,
            "question": question,
            "hint": "Payment was accepted but scoring is temporarily unavailable. Retry shortly.",
        },
        status_code=503,
    )


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
        return paid_unavailable(question, reason)

    prompt = (
        f'Search X for recent posts about this prediction market:\n"{question}"\n\n'
        "Return ONLY valid JSON, no markdown:\n"
        '{"score": <int -100 to 100>, "catalyst": "<one sentence>", '
        '"volume_signal": "<rising|falling|flat>"}'
    )
    raw, err = grok_json(prompt)
    mark_grok(request)

    if err or raw is None:
        if hit:
            data = dict(hit[1])
            data["degraded"] = err or "grok_error"
            return data
        return paid_unavailable(question, err or "grok_error")

    data = normalize_score_payload(raw, question=question)
    data["scored_at"] = datetime.now(timezone.utc).isoformat()
    commit_score(key, data, now)
    return data


def build_shift_payload(q: str, now_data: dict) -> dict:
    key = q.strip().lower()
    prev = PREV.get(key)
    if not prev:
        return {
            "question": q,
            "score_now": now_data["score"],
            "score_before": now_data["score"],
            "shift": 0,
            "catalyst": now_data.get("catalyst", ""),
            "scored_at": now_data.get("scored_at"),
            "note": "no_prior_score",
            "degraded": now_data.get("degraded"),
        }
    return {
        "question": q,
        "score_now": now_data["score"],
        "score_before": prev["score"],
        "shift": now_data["score"] - prev["score"],
        "catalyst": now_data.get("catalyst", ""),
        "scored_at": now_data.get("scored_at"),
        "prior_scored_at": prev.get("scored_at"),
        "degraded": now_data.get("degraded"),
    }


def build_brief(q: str, now_data: dict) -> dict:
    shift = build_shift_payload(q, now_data)
    catalyst = now_data.get("catalyst") or "n/a"
    if shift["shift"] > 0:
        direction = "more bullish"
    elif shift["shift"] < 0:
        direction = "more bearish"
    else:
        direction = "unchanged"
    summary = (
        f"X sentiment score {now_data['score']} ({direction} vs prior "
        f"{shift['score_before']}; shift {shift['shift']:+d}). Catalyst: {catalyst}"
    )
    return {
        "question": q,
        "score": now_data["score"],
        "catalyst": catalyst,
        "volume_signal": now_data.get("volume_signal", "flat"),
        "shift": shift["shift"],
        "score_before": shift["score_before"],
        "summary": summary,
        "scored_at": now_data.get("scored_at"),
        "degraded": now_data.get("degraded"),
        "tier": "brief",
    }


@app.get("/", tags=["free"], summary="Service index for agents", responses={200: {"model": CatalogOut}})
async def root():
    return catalog_body()


@app.get("/catalog", tags=["free"], summary="Machine-readable route catalog", responses={200: {"model": CatalogOut}})
async def catalog():
    return catalog_body()


@app.get("/pricing", tags=["free"], summary="USDC price ladder", responses={200: {"model": PricingOut}})
async def pricing():
    """Explicit price ladder for agents and humans."""
    return {
        "currency": "USDC",
        "network": NETWORK,
        "ladder": {
            "free": ["/", "/health", "/sample", "/catalog", "/pricing", "/docs"],
            "lite": {"price": PRICE_LITE, "routes": ["/top", "/shift"]},
            "full": {"price": PRICE_BRIEF, "routes": ["/sentiment", "/brief"]},
        },
        "price_lite": PRICE_LITE,
        "price_brief": PRICE_BRIEF,
        "notes": (
            "Lite /top+/shift align with Bazaar discovery indexes at $0.01; "
            "full Grok X-sentiment /sentiment+/brief at $0.05."
        ),
    }


@app.get("/sample", tags=["free"], summary="Static example response (no Grok)", responses={200: {"model": SampleOut}})
async def sample():
    return SAMPLE_PAYLOAD


@app.get("/about", tags=["free"], summary="Human-readable landing page", response_class=HTMLResponse)
async def about():
    return about_html(PUBLIC_BASE, PRICE_LITE, PRICE_BRIEF, PAY_TO, NETWORK, TTL)


@app.get("/llms.txt", tags=["free"], summary="Plain-text summary for LLM agents", response_class=PlainTextResponse)
async def llms():
    return llms_txt(PUBLIC_BASE, PRICE_LITE, PRICE_BRIEF, NETWORK, TTL)


@app.get("/health", tags=["free"], summary="Liveness and price ladder", responses={200: {"model": HealthOut}})
async def health():
    return {
        "status": "ok",
        "routes": {
            "free": ["/", "/health", "/sample", "/catalog", "/pricing", "/docs"],
            "paid_lite": ["/top", "/shift"],
            "paid_brief": ["/sentiment", "/brief"],
        },
        "price_lite": PRICE_LITE,
        "price_brief": PRICE_BRIEF,
        "price": PRICE_BRIEF,
        "cache_ttl_sec": TTL,
        "network": NETWORK,
        "test_mode": TEST_MODE,
    }


@app.get(
    "/sentiment",
    tags=["paid-full"],
    summary="X sentiment score for a Polymarket/Kalshi market",
    responses=paid_responses(Union[SentimentOut, MissingQueryOut], PRICE_BRIEF),
)
async def sentiment(request: Request, q: str = Q_PARAM):
    q = q.strip()
    if not q:
        return {"error": "pass ?q=your+market+question"}
    data = score_market(q, request)
    if isinstance(data, JSONResponse):
        return data
    out = dict(data)
    out["tier"] = "sentiment"
    return out


@app.get(
    "/brief",
    tags=["paid-full"],
    summary="Score + shift + one-line summary for a market",
    responses=paid_responses(Union[BriefOut, MissingQueryOut], PRICE_BRIEF),
)
async def brief(request: Request, q: str = Q_PARAM):
    q = q.strip()
    if not q:
        return {"error": "pass ?q=your+market+question"}
    data = score_market(q, request)
    if isinstance(data, JSONResponse):
        return data
    return build_brief(q, data)


@app.get(
    "/shift",
    tags=["paid-lite"],
    summary="Sentiment change vs previous cached score",
    responses=paid_responses(Union[ShiftOut, MissingQueryOut], PRICE_LITE),
)
async def shift(request: Request, q: str = Q_PARAM):
    q = q.strip()
    if not q:
        return {"error": "pass ?q=your+market+question"}
    now_data = score_market(q, request)
    if isinstance(now_data, JSONResponse):
        return now_data
    return build_shift_payload(q, now_data)


@app.get(
    "/top",
    tags=["paid-lite"],
    summary="Three most-discussed markets on X with scores",
    responses=paid_responses(TopOut, PRICE_LITE),
)
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
        return paid_unavailable("top", reason)

    prompt = (
        "Search X for the three most discussed Polymarket or Kalshi markets right now. "
        "Return ONLY valid JSON, no markdown:\n"
        '{"markets":[{"question":"...","score":<int -100 to 100>,'
        '"catalyst":"<one sentence>","volume_signal":"<rising|falling|flat>"}]}'
    )
    raw, err = grok_json(prompt)
    mark_grok(request)

    if err or raw is None:
        if hit:
            data = dict(hit[1])
            data["degraded"] = err or "grok_error"
            return data
        return paid_unavailable("top", err or "grok_error")

    markets = raw.get("markets") if isinstance(raw, dict) else None
    if not isinstance(markets, list):
        markets = []
    cleaned = []
    for m in markets[:3]:
        if isinstance(m, dict):
            cleaned.append(normalize_score_payload(m))
    data = {
        "markets": cleaned,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    CACHE["__top__"] = (now, data)
    return data

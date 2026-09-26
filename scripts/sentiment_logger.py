"""Daily sentiment-vs-odds logger for the 4-week signal test.

Once a day, for each tracked Polymarket market: record the live Yes price and
score X sentiment with Grok (same prompt as the API). Rows are appended to
data/sentiment_log.csv so we can later check whether sentiment moved before
the odds did.

Cost control: at most MAX_GROK_CALLS_PER_MONTH Grok calls per calendar month
(counted from the CSV). Closed markets are never scored. Read-only otherwise:
no payments, no changes to the live API.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = Path(os.environ.get("SENTIMENT_LOG_PATH", ROOT / "data" / "sentiment_log.csv"))
MAX_GROK_CALLS_PER_MONTH = int(os.environ.get("MAX_GROK_CALLS_PER_MONTH", "160"))
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4.7")
GAMMA_MARKET_URL = "https://gamma-api.polymarket.com/markets/"
NL = chr(10)

# Polymarket market id -> short label. Chosen 2026-09-26: liquid, uncertain, close late Oct / early Nov.
MARKETS = [
    ("2589813", "Fed +25bps Oct 2026"),
    ("4641065", "US-Iran ceasefire through Oct 31"),
    ("562828", "Balance of Power: D Senate, D House"),
    ("2100981", "Likud most seats, Israel 2026"),
    ("1892495", "Minnesota Lynx win 2026 WNBA Finals"),
]

FIELDS = [
    "date_utc", "market_id", "label", "question", "yes_price", "best_bid", "best_ask",
    "volume_24h", "closed", "grok_called", "score", "catalyst", "volume_signal", "error",
]


def _num(value) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def yes_price(market: dict) -> Optional[float]:
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        prices = json.loads(market.get("outcomePrices") or "[]")
    except (TypeError, ValueError):
        return None
    for outcome, price in zip(outcomes, prices):
        if str(outcome).strip().lower() == "yes":
            return _num(price)
    return None


def fetch_market(market_id: str) -> dict:
    import httpx

    resp = httpx.get(GAMMA_MARKET_URL + market_id, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_json_object(text: str) -> Optional[dict]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def grok_score(question: str) -> dict:
    """Same prompt as the live API's score_market()."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1")
    prompt = (
        "Search X for recent posts about this prediction market:" + NL
        + '"' + question + '"' + NL + NL
        + "Return ONLY valid JSON, no markdown:" + NL
        + '{"score": <int -100 to 100>, "catalyst": "<one sentence>", '
        + '"volume_signal": "<rising|falling|flat>"}'
    )
    resp = client.responses.create(
        model=GROK_MODEL,
        input=[{"role": "user", "content": prompt}],
        tools=[{"type": "x_search"}],
    )
    text = getattr(resp, "output_text", None) or ""
    if not text:
        parts = []
        for item in getattr(resp, "output", None) or []:
            for block in getattr(item, "content", None) or []:
                if getattr(block, "text", None):
                    parts.append(block.text)
        text = NL.join(parts)
    parsed = parse_json_object(text)
    if parsed is None:
        raise ValueError("no_json")
    return parsed


def normalize(raw: dict) -> dict:
    try:
        score = max(-100, min(100, int(raw.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    catalyst = raw.get("catalyst")
    volume = raw.get("volume_signal")
    return {
        "score": score,
        "catalyst": catalyst.strip() if isinstance(catalyst, str) else "",
        "volume_signal": volume if volume in ("rising", "falling", "flat") else "flat",
    }


def calls_this_month(path: Path, now: datetime) -> int:
    if not path.exists():
        return 0
    month = now.strftime("%Y-%m")
    with path.open(newline="", encoding="utf-8") as f:
        return sum(
            1 for row in csv.DictReader(f)
            if row.get("date_utc", "").startswith(month) and row.get("grok_called") == "1"
        )


def run(
    now: Optional[datetime] = None,
    path: Path = LOG_PATH,
    fetch: Callable[[str], dict] = fetch_market,
    score: Callable[[str], dict] = grok_score,
    max_calls: int = MAX_GROK_CALLS_PER_MONTH,
) -> list:
    now = now or datetime.now(timezone.utc)
    used = calls_this_month(path, now)
    rows = []
    for market_id, label in MARKETS:
        row = {k: "" for k in FIELDS}
        row.update(date_utc=now.strftime("%Y-%m-%dT%H:%MZ"), market_id=market_id, label=label, grok_called="0")
        try:
            m = fetch(market_id)
            row.update(
                question=m.get("question") or "",
                yes_price=yes_price(m),
                best_bid=_num(m.get("bestBid")),
                best_ask=_num(m.get("bestAsk")),
                volume_24h=_num(m.get("volume24hr")),
                closed="1" if m.get("closed") else "0",
            )
        except Exception as e:
            row["error"] = f"market_fetch_{type(e).__name__}"
            rows.append(row)
            continue
        if row["closed"] == "1":
            row["error"] = "market_closed"
        elif used >= max_calls:
            row["error"] = "monthly_grok_cap_reached"
        else:
            used += 1
            row["grok_called"] = "1"
            try:
                row.update(normalize(score(row["question"])))
            except Exception as e:
                row["error"] = f"grok_{type(e).__name__}"
        rows.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    if not os.environ.get("XAI_API_KEY"):
        print("XAI_API_KEY secret is not set; nothing to do.")
        sys.exit(1)
    out = run()
    for r in out:
        print(r["label"], "| yes", r["yes_price"], "| score", r["score"], "|", r["error"] or "ok")

"""Free tier: the latest daily scores from the signal-test logger.

The logger (scripts/sentiment_logger.py, GitHub Actions, once a day) already pays
for one Grok score per tracked market and commits it to data/sentiment_log.csv.
This module turns that file into a free /scores response, so serving it costs
nothing extra. The file is read from GitHub (fresh after each logger run) with a
local fallback, and cached for SCORES_TTL seconds.
"""

from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

LOCAL_CSV = Path(__file__).resolve().parent / "data" / "sentiment_log.csv"
REMOTE_CSV = os.environ.get(
    "SCORES_CSV_URL",
    "https://raw.githubusercontent.com/wballztrading1/Prediction-bot/main/data/sentiment_log.csv",
)
SCORES_TTL = int(os.environ.get("SCORES_TTL_SEC", "1800"))
STALE_AFTER_HOURS = 36

NOTE = (
    "Free daily snapshot from our tracking run (one X-sentiment score per market per day, "
    "scored by Grok from recent X posts). For a fresh score on any Polymarket or Kalshi "
    "question, use the paid /sentiment or /brief routes."
)


def _parse_time(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def latest_scores(csv_text: str, now: Optional[datetime] = None) -> dict:
    """Latest scored row per market, with the change since that market's previous score.

    Markets whose most recent row is closed are left out (they stopped trading).
    """
    now = now or datetime.now(timezone.utc)
    by_market: dict[str, list[dict]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        mid = (row.get("market_id") or "").strip()
        when = _parse_time(row.get("date_utc", ""))
        if not mid or when is None:
            continue
        by_market.setdefault(mid, []).append({**row, "_when": when})

    markets = []
    for mid, rows in by_market.items():
        rows.sort(key=lambda r: r["_when"])
        if (rows[-1].get("closed") or "").strip() == "1":
            continue
        scored = [r for r in rows if _to_int(r.get("score")) is not None]
        if not scored:
            continue
        last = scored[-1]
        prev = scored[-2] if len(scored) > 1 else None
        score = _to_int(last["score"])
        before = _to_int(prev["score"]) if prev else None
        age_h = (now - last["_when"]).total_seconds() / 3600
        markets.append(
            {
                "market_id": mid,
                "label": last.get("label") or "",
                "question": last.get("question") or "",
                "score": score,
                "score_before": before,
                "shift": (score - before) if before is not None else None,
                "catalyst": last.get("catalyst") or "",
                "volume_signal": last.get("volume_signal") or None,
                "polymarket_yes_price": _to_float(last.get("yes_price")),
                "scored_at": last["_when"].isoformat(),
                "prior_scored_at": prev["_when"].isoformat() if prev else None,
                "stale": age_h > STALE_AFTER_HOURS,
                "source": "polymarket",
            }
        )

    markets.sort(key=lambda m: m["scored_at"], reverse=True)
    as_of = markets[0]["scored_at"] if markets else None
    return {"markets": markets, "count": len(markets), "as_of": as_of, "note": NOTE}


class ScoresSource:
    """Cached loader. `fetch` returns the CSV text or raises; injectable for tests."""

    def __init__(self, fetch: Optional[Callable[[], str]] = None, ttl: int = SCORES_TTL):
        self._fetch = fetch
        self._ttl = ttl
        self._at = 0.0
        self._body: Optional[dict] = None

    def _read(self) -> tuple[str, str]:
        if self._fetch is not None:
            try:
                return self._fetch(), "remote"
            except Exception:
                pass
        return LOCAL_CSV.read_text(encoding="utf-8"), "bundled"

    def get(self) -> dict:
        if self._body is not None and time.time() - self._at < self._ttl:
            return self._body
        text, origin = self._read()
        body = latest_scores(text)
        body["data_origin"] = origin
        self._body, self._at = body, time.time()
        return body


def github_fetch(url: str = REMOTE_CSV, timeout: float = 10.0) -> str:
    import httpx

    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text

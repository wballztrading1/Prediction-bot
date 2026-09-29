"""Money-loss guards for every paid Grok call (pure logic, unit-tested).

1. Price floor: a route only calls Grok when its price covers the call with a
   margin (PRICE >= cost x GROK_MIN_MARGIN). Otherwise it serves cache only.
2. Failed calls: Grok spend that ends in an error is never paid for (x402 only
   settles on success), so failures get their own small budgets, per payer and
   global, and one payment (nonce) can trigger Grok at most once.
3. Identity: limits key on the paying wallet from the x402 payload, which
   cannot be faked, not on client-supplied IP headers.
4. Dollar budgets: an hourly call cap plus a daily USD budget using the real
   per-call cost estimate. All in memory: a restart resets them, so the
   prepaid xAI balance (auto top-up off) stays the hard backstop.
5. Questions: whitespace/punctuation variants share one cache entry, and
   questions are length-capped and stripped of characters used to smuggle
   instructions into the prompt.
"""
import os
import re
import time
from collections import defaultdict, deque
from typing import Optional, Tuple

MAX_Q_CHARS = int(os.environ.get("MAX_Q_CHARS", "200"))
_ALLOWED = re.compile(r"[^A-Za-z0-9 ,.?!$%&'()+:/-]")
_KEY = re.compile(r"[^a-z0-9 ]")


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return int(default)


def clean_question(q: Optional[str]) -> Tuple[str, Optional[str]]:
    """(cleaned question, error). Errors: 'missing_q', 'q_too_long'."""
    text = " ".join((q or "").split())
    if not text:
        return "", "missing_q"
    if len(text) > MAX_Q_CHARS:
        return "", "q_too_long"
    text = " ".join(_ALLOWED.sub(" ", text).split())
    return (text, None) if text else ("", "missing_q")


def cache_key(q: str) -> str:
    """Case, spacing and punctuation variants of a question share one key."""
    return " ".join(_KEY.sub(" ", (q or "").lower()).split())


def price_usd(price: str) -> float:
    try:
        return float(str(price).replace("$", "").strip() or "0")
    except ValueError:
        return 0.0


def covers_cost(price: str, cost_usd: float, margin: float) -> bool:
    return price_usd(price) >= cost_usd * margin


def payment_identity(request) -> Tuple[Optional[str], Optional[str]]:
    """(payer wallet, payment nonce) from the verified x402 payload, if any."""
    payload = getattr(getattr(request, "state", None), "payment_payload", None)
    if payload is None:
        return None, None
    inner = payload.get("payload") if isinstance(payload, dict) else getattr(payload, "payload", None)
    auth = (inner or {}).get("authorization") or {}
    payer = auth.get("from") or (inner or {}).get("from")
    nonce = auth.get("nonce") or (inner or {}).get("nonce")
    return (payer.lower() if isinstance(payer, str) else None), (str(nonce) if nonce else None)


class SpendGuard:
    """Hourly/daily limits on Grok spend. Thread-safe enough for one worker."""

    def __init__(self, cost_usd: float, clock=time.time):
        self.cost = cost_usd
        self.clock = clock
        self.caller_calls = _env_int("CALLER_GROK_PER_HOUR", "3")
        self.global_calls = _env_int("GLOBAL_GROK_PER_HOUR", "10")
        self.daily_usd = _env_float("DAILY_GROK_BUDGET_USD", "3")
        self.caller_failures = _env_int("CALLER_GROK_FAILS_PER_DAY", "2")
        self.global_failures = _env_int("GLOBAL_GROK_FAILS_PER_HOUR", "3")
        self.calls = defaultdict(deque)      # caller -> call times (1h)
        self.fails = defaultdict(deque)      # caller -> failure times (24h)
        self.spend = deque()                 # (time, usd) for 24h
        self.nonces = {}                     # nonce -> time (24h)

    @staticmethod
    def _trim(dq, cutoff):
        while dq and (dq[0][0] if isinstance(dq[0], tuple) else dq[0]) < cutoff:
            dq.popleft()

    def check(self, caller: str, nonce: Optional[str] = None) -> Tuple[bool, str]:
        now = self.clock()
        hour, day = now - 3600, now - 86400
        for key in (caller, "__global__"):
            self._trim(self.calls[key], hour)
        for key in (caller, "__global_fail__"):
            self._trim(self.fails[key], day if key == caller else hour)
        self._trim(self.spend, day)
        for n, t in list(self.nonces.items()):
            if t < day:
                del self.nonces[n]
        if nonce and nonce in self.nonces:
            return False, "payment_already_used"
        if len(self.fails[caller]) >= self.caller_failures:
            return False, "too_many_failed_requests"
        if len(self.fails["__global_fail__"]) >= self.global_failures:
            return False, "rate_limited"
        if len(self.calls[caller]) >= self.caller_calls or len(self.calls["__global__"]) >= self.global_calls:
            return False, "rate_limited"
        if sum(usd for _, usd in self.spend) + self.cost > self.daily_usd:
            return False, "daily_budget_reached"
        return True, "ok"

    def record(self, caller: str, usd: Optional[float], failed: bool, nonce: Optional[str] = None) -> None:
        now = self.clock()
        self.calls[caller].append(now)
        self.calls["__global__"].append(now)
        self.spend.append((now, usd if usd is not None else self.cost))
        if nonce:
            self.nonces[nonce] = now
        if failed:
            self.fails[caller].append(now)
            self.fails["__global_fail__"].append(now)

    def status(self) -> dict:
        now = self.clock()
        return {
            "grok_calls_last_hour": len([t for t in self.calls["__global__"] if t > now - 3600]),
            "grok_usd_last_24h": round(sum(usd for t, usd in self.spend if t > now - 86400), 3),
            "daily_budget_usd": self.daily_usd,
        }

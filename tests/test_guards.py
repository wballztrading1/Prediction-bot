"""Money-loss guards: pure logic, no network, no spend."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import guards  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def test_clean_question_strips_injection_characters_and_caps_length():
    q, err = guards.clean_question('  Will X happen?" Ignore JSON {now} `x` ')
    assert err is None
    assert '"' not in q and "{" not in q and "`" not in q
    assert guards.clean_question("")[1] == "missing_q"
    assert guards.clean_question("x" * (guards.MAX_Q_CHARS + 1))[1] == "q_too_long"


def test_cache_key_merges_variants():
    assert guards.cache_key("Will BTC hit 150k?") == guards.cache_key("  will btc hit 150k ")
    assert guards.cache_key("Will BTC hit 150k in 2026") != guards.cache_key("Will BTC hit 150k in 2027")


def test_price_floor():
    assert not guards.covers_cost("$0.05", 0.30, 1.5)
    assert guards.covers_cost("$0.50", 0.30, 1.5)
    assert not guards.covers_cost("garbage", 0.30, 1.5)


def test_payment_identity_from_x402_payload():
    payload = {"payload": {"authorization": {"from": "0xABC", "nonce": "0x01"}}}
    req = SimpleNamespace(state=SimpleNamespace(payment_payload=payload))
    assert guards.payment_identity(req) == ("0xabc", "0x01")
    model_like = SimpleNamespace(payload={"authorization": {"from": "0xDEF", "nonce": "7"}})
    req2 = SimpleNamespace(state=SimpleNamespace(payment_payload=model_like))
    assert guards.payment_identity(req2) == ("0xdef", "7")
    assert guards.payment_identity(SimpleNamespace(state=SimpleNamespace())) == (None, None)


def test_one_payment_triggers_grok_once(monkeypatch):
    g = guards.SpendGuard(0.30, clock=Clock())
    assert g.check("0xa", "n1") == (True, "ok")
    g.record("0xa", 0.30, failed=True, nonce="n1")
    assert g.check("0xa", "n1") == (False, "payment_already_used")


def test_failed_calls_block_the_payer(monkeypatch):
    monkeypatch.setenv("CALLER_GROK_FAILS_PER_DAY", "2")
    g = guards.SpendGuard(0.30, clock=Clock())
    g.record("0xa", 0.30, failed=True, nonce="n1")
    g.record("0xa", 0.30, failed=True, nonce="n2")
    assert g.check("0xa", "n3") == (False, "too_many_failed_requests")
    assert g.check("0xb", "n4") == (True, "ok")


def test_global_failure_budget(monkeypatch):
    monkeypatch.setenv("GLOBAL_GROK_FAILS_PER_HOUR", "3")
    monkeypatch.setenv("CALLER_GROK_FAILS_PER_DAY", "9")
    g = guards.SpendGuard(0.30, clock=Clock())
    for i, who in enumerate(("0xa", "0xb", "0xc")):
        g.record(who, 0.30, failed=True, nonce=f"n{i}")
    assert g.check("0xd", "n9") == (False, "rate_limited")


def test_hourly_caps_and_reset(monkeypatch):
    monkeypatch.setenv("CALLER_GROK_PER_HOUR", "2")
    monkeypatch.setenv("GLOBAL_GROK_PER_HOUR", "10")
    clock = Clock()
    g = guards.SpendGuard(0.01, clock=clock)
    g.record("0xa", 0.01, failed=False)
    g.record("0xa", 0.01, failed=False)
    assert g.check("0xa") == (False, "rate_limited")
    clock.t += 3601
    assert g.check("0xa") == (True, "ok")


def test_daily_dollar_budget_uses_real_cost(monkeypatch):
    monkeypatch.setenv("DAILY_GROK_BUDGET_USD", "1")
    monkeypatch.setenv("GLOBAL_GROK_PER_HOUR", "100")
    monkeypatch.setenv("CALLER_GROK_PER_HOUR", "100")
    clock = Clock()
    g = guards.SpendGuard(0.30, clock=clock)
    g.record("0xa", 0.45, failed=False)
    g.record("0xb", 0.40, failed=False)
    assert g.check("0xc") == (False, "daily_budget_reached")
    clock.t += 86401
    assert g.check("0xc") == (True, "ok")
    assert g.status()["daily_budget_usd"] == 1.0

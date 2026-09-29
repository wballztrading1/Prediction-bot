"""Shared Grok settings and cost estimate. No network, no spend."""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grok_cost  # noqa: E402


def test_defaults_search_recent_posts_only(monkeypatch):
    for name in ("GROK_MODEL", "GROK_SEARCH_DAYS", "GROK_MAX_TURNS"):
        monkeypatch.delenv(name, raising=False)
    kwargs = grok_cost.request_kwargs("hi")
    assert kwargs["model"] == "grok-4.3"
    assert kwargs["tools"][0]["type"] == "x_search"
    assert "from_date" in kwargs["tools"][0]
    assert kwargs["extra_body"] == {"max_turns": 2}


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GROK_MODEL", "grok-4.3")
    monkeypatch.setenv("GROK_SEARCH_DAYS", "0")
    monkeypatch.setenv("GROK_MAX_TURNS", "1")
    kwargs = grok_cost.request_kwargs("hi")
    assert kwargs["model"] == "grok-4.3"
    assert kwargs["tools"] == [{"type": "x_search"}]
    assert kwargs["extra_body"] == {"max_turns": 1}


def test_bad_env_values_fall_back(monkeypatch):
    monkeypatch.setenv("GROK_SEARCH_DAYS", "lots")
    monkeypatch.setenv("GROK_MAX_TURNS", "many")
    assert grok_cost.search_days() == 3
    assert grok_cost.max_turns() == 2


def test_max_turns_zero_means_xai_default(monkeypatch):
    monkeypatch.setenv("GROK_MAX_TURNS", "0")
    assert grok_cost.max_turns() is None
    assert "extra_body" not in grok_cost.request_kwargs("hi")


def test_from_date_window():
    tool = grok_cost.x_search_tool(days=3, today=date(2026, 9, 29))
    assert tool == {"type": "x_search", "from_date": "2026-09-26"}


def test_usage_summary_and_cost_match_observed_call():
    # Sep 28 logger call: 67,544 prompt tokens, 422 completion, grok-4.7.
    usage = SimpleNamespace(
        input_tokens=67544,
        output_tokens=422,
        input_tokens_details=SimpleNamespace(cached_tokens=0),
        model_extra={"server_side_tool_usage_details": {"x_posts_fetched": 30, "x_users_fetched": 0}},
    )
    summary = grok_cost.usage_summary(SimpleNamespace(usage=usage))
    assert summary == {"input_tokens": 67544, "cached_tokens": 0, "output_tokens": 422, "x_posts": 30, "x_users": 0}
    cost = grok_cost.estimate_cost(summary, "grok-4.7")
    assert 0.28 < cost < 0.30  # 0.135 tokens + 0.0025 output + 0.15 posts
    assert grok_cost.estimate_cost(summary, "grok-4.3") < cost


def test_usage_summary_tolerates_missing_fields():
    assert grok_cost.usage_summary(SimpleNamespace()) == {
        "input_tokens": 0, "cached_tokens": 0, "output_tokens": 0, "x_posts": 0, "x_users": 0,
    }

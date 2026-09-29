"""Apify Actor: pure logic and packaging. No Apify SDK, no network, no spend."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACTOR = ROOT / "apify_actor"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ACTOR))

from src import core  # noqa: E402
import sentiment_logger  # noqa: E402


class FakeResponses:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts.pop(0)
        if isinstance(text, Exception):
            raise text
        return SimpleNamespace(output_text=text, output=None)


def fake_client(*texts):
    return SimpleNamespace(responses=FakeResponses(texts))


def test_prompt_matches_signal_test_logger():
    q = "Will X happen?"
    assert core.build_prompt(q) == sentiment_logger.build_prompt(q)
    assert core.PROMPT_VERSION == sentiment_logger.PROMPT_VERSION


def test_clean_questions_dedupes_trims_and_caps():
    raw = ["  Will A?  ", "will a?", "", None, 5, "Will  B?"] + [f"Q{i}?" for i in range(40)]
    out = core.clean_questions(raw)
    assert out[:2] == ["Will A?", "Will B?"]
    assert len(out) == core.MAX_QUESTIONS
    assert core.clean_questions("Single?") == ["Single?"]
    assert core.clean_questions(None) == []


def test_grok_score_uses_x_search_and_normalizes():
    client = fake_client('Sure: {"score": 180, "catalyst": " ETF flows ", "volume_signal": "surging"}')
    out = core.grok_score("Will X happen?", client)
    assert out == {"score": 100, "catalyst": "ETF flows", "volume_signal": "flat"}
    call = client.responses.calls[0]
    assert call["tools"][0]["type"] == "x_search"
    assert "from_date" in call["tools"][0]  # recent posts only (cost control)
    assert "Ignore posts that only discuss betting odds" in call["input"][0]["content"]


def test_safe_score_retries_then_reports_error():
    client = fake_client(TimeoutError(), '{"score": -20, "catalyst": "c", "volume_signal": "rising"}')
    scored, err = core.safe_score("Q?", client)
    assert err is None and scored["score"] == -20

    scored, err = core.safe_score("Q?", fake_client("no json here", "still none"))
    assert scored is None and err == "scoring_failed_ValueError"


def test_result_item_flattens_odds():
    odds_block = {
        "polymarket": {"market": "Will X?", "implied_prob_pct": 64.5},
        "kalshi": None,
        "fetched_at": "t",
    }
    item = core.result_item("Will X?", {"score": 5, "catalyst": "c", "volume_signal": "flat"}, odds_block, None)
    assert item["polymarket_yes_pct"] == 64.5
    assert item["kalshi_yes_pct"] is None and item["kalshi_market"] is None
    assert item["odds"] == odds_block and item["error"] is None

    failed = core.result_item("Will X?", None, None, "scoring_failed_TimeoutError")
    assert failed["score"] is None and failed["odds"] is None
    assert failed["error"] == "scoring_failed_TimeoutError"


def test_actor_packaging_is_consistent():
    spec = json.loads((ACTOR / ".actor" / "actor.json").read_text())
    assert spec["actorSpecification"] == 1
    assert (ACTOR / ".actor" / spec["dockerfile"]).resolve() == (ACTOR / "Dockerfile").resolve()
    assert (ACTOR / ".actor" / spec["dockerContextDir"]).resolve() == ROOT
    assert (ACTOR / ".actor" / spec["readme"]).resolve().exists()
    props = spec["input"]["properties"]
    assert spec["input"]["required"] == ["questions"]
    assert props["questions"]["maxItems"] == core.MAX_QUESTIONS
    fields = spec["storages"]["dataset"]["views"]["overview"]["transformation"]["fields"]
    sample = core.result_item("Q?", None, None, None)
    assert set(fields) <= set(sample)

    dockerfile = (ACTOR / "Dockerfile").read_text()
    for path in ("apify_actor/requirements.txt", "odds.py", "grok_cost.py", "apify_actor/src"):
        assert f"COPY {path} " in dockerfile
        assert (ROOT / path).exists()
    assert 'CMD ["python3", "-m", "src"]' in dockerfile


def test_entry_point_charges_only_scored_rows():
    src = (ACTOR / "src" / "__main__.py").read_text()
    assert 'EVENT = "market-scored"' in src
    assert "push_data(item, charged_event_name=EVENT)" in src
    assert "os.environ.get(\"XAI_API_KEY\")" in src


@pytest.mark.parametrize("text", ["", "[]", "{not json}"])
def test_parse_json_object_rejects_bad_output(text):
    assert core.parse_json_object(text) is None

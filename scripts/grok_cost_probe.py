"""One-off cost probe: score the same markets under a few Grok settings and
report real token/post counts, estimated cost and the scores themselves.

Run from GitHub Actions (workflow "grok-cost-probe"). About 6 Grok calls;
expected total well under $1. Writes a Markdown table to the job summary.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import grok_cost  # noqa: E402
from sentiment_logger import build_prompt, normalize, parse_json_object  # noqa: E402

QUESTIONS = [
    "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
    "US x Iran ceasefire continues through October 31?",
]

# (label, model, search days, max turns)
CONFIGS = [
    ("4.7, 3 days, 1 round", "grok-4.7", 3, 1),
    ("4.3, 3 days, 1 round", "grok-4.3", 3, 1),
    ("4.3, 3 days, 2 rounds", "grok-4.3", 3, 2),
]


def run_one(client, question, model_id, days, turns):
    kwargs = grok_cost.request_kwargs(build_prompt(question), model_id=model_id, days=days, turns=turns)
    resp = client.responses.create(**kwargs)
    text = getattr(resp, "output_text", None) or ""
    parsed = parse_json_object(text) or {}
    used = grok_cost.usage_summary(resp)
    return normalize(parsed) if parsed else None, used, grok_cost.estimate_cost(used, model_id)


def main():
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["XAI_API_KEY"], base_url="https://api.x.ai/v1", timeout=180)
    lines = [
        "| Setting | Market | Score | Est. cost | Input tokens | Posts | Catalyst |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label, model_id, days, turns in CONFIGS:
        for q in QUESTIONS:
            try:
                scored, used, usd = run_one(client, q, model_id, days, turns)
                score = scored["score"] if scored else "no JSON"
                catalyst = (scored or {}).get("catalyst", "")[:90]
                row = f"| {label} | {q[:40]} | {score} | ${usd:.3f} | {used['input_tokens']:,} | {used['x_posts']} | {catalyst} |"
            except Exception as e:  # noqa: BLE001 - one bad setting shouldn't stop the probe
                row = f"| {label} | {q[:40]} | error: {type(e).__name__}: {str(e)[:80]} | | | | |"
            print(row, flush=True)
            lines.append(row)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Grok cost probe\n\nBaseline before this probe: about $0.30 per call (grok-4.7, no limits).\n\n")
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if not os.environ.get("XAI_API_KEY"):
        print("XAI_API_KEY secret is not set; nothing to do.")
        sys.exit(1)
    main()

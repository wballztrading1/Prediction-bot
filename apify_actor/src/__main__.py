"""Apify Actor entry point: `python -m src`.

Input: up to 25 prediction-market questions. Output: one dataset row per
question with an X sentiment score (Grok live search), the catalyst, and live
Polymarket and Kalshi odds. Pay-per-event: one "market-scored" charge per row
that was scored successfully; failed rows are free.

The Grok key comes from the XAI_API_KEY secret environment variable set in the
Actor's settings by its owner. Buyers never need their own key.
"""
import asyncio
import math
import os
from concurrent.futures import ThreadPoolExecutor

from apify import Actor

import odds

from .core import clean_questions, make_client, result_item, safe_score

EVENT = "market-scored"
GROK_WORKERS = 3
KALSHI_WAIT_SEC = 240


def allowed_count(wanted: int) -> int:
    """How many rows the buyer's max-charge limit allows (all of them if not pay-per-event)."""
    try:
        limit = Actor.get_charging_manager().calculate_max_event_charge_count_within_limit(EVENT)
    except Exception:  # noqa: BLE001 - not pay-per-event, or local run
        return wanted
    if limit is None or (isinstance(limit, float) and math.isinf(limit)):
        return wanted
    return max(0, min(wanted, int(limit)))


def odds_for(question: str, include_kalshi: bool) -> dict:
    if include_kalshi:
        return odds.market_odds(question)
    return odds.market_odds(question, kalshi=lambda _q: (None, None))


async def wait_for_kalshi() -> None:
    waited = 0
    while odds.kalshi_index_status()["kalshi_building"] and waited < KALSHI_WAIT_SEC:
        await asyncio.sleep(2)
        waited += 2


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        questions = clean_questions(actor_input.get("questions"))
        include_odds = actor_input.get("includeOdds", True) is not False
        include_kalshi = include_odds and actor_input.get("includeKalshi", True) is not False

        if not questions:
            await Actor.fail(status_message="Add at least one market question.")
            return
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            await Actor.fail(status_message="Scoring is not configured yet. Please try again later.")
            return

        allowed = allowed_count(len(questions))
        if allowed < len(questions):
            Actor.log.warning(f"Max charge limit allows {allowed} of {len(questions)} questions; scoring the first {allowed}.")
            questions = questions[:allowed]
        if not questions:
            await Actor.exit(status_message="Your max charge limit allows 0 results.")
            return

        if include_kalshi:
            odds.ensure_kalshi_index(background=True)  # builds while Grok scores

        await Actor.set_status_message(f"Scoring {len(questions)} market(s) on X...")
        client = make_client(api_key)
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=GROK_WORKERS) as pool:
            scores = await asyncio.gather(
                *(loop.run_in_executor(pool, safe_score, q, client) for q in questions)
            )

        odds_blocks = {}
        if include_odds:
            if include_kalshi:
                await Actor.set_status_message("Matching live Polymarket and Kalshi odds...")
                await wait_for_kalshi()
            for q in questions:
                odds_blocks[q] = await loop.run_in_executor(None, odds_for, q, include_kalshi)

        scored_ok = 0
        for q, (scored, err) in zip(questions, scores):
            item = result_item(q, scored, odds_blocks.get(q), err)
            if scored is not None:
                await Actor.push_data(item, charged_event_name=EVENT)
                scored_ok += 1
            else:
                await Actor.push_data(item)

        await Actor.set_status_message(f"Done: {scored_ok} of {len(questions)} market(s) scored.")


asyncio.run(main())

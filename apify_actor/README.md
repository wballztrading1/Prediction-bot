# Prediction Market Sentiment: X chatter vs. Polymarket and Kalshi odds

See what people on X are saying about any prediction market, next to what the market is pricing. Give it market questions; get back one row per market with:

- **X sentiment score** from -100 (very negative about the event happening) to +100 (very positive), scored by Grok with live X search
- **Catalyst**: one sentence on what the conversation is about right now
- **Chatter volume**: rising, falling or flat
- **Live odds**: the closest open **Polymarket** and **Kalshi** markets, with their current Yes price, bid/ask and 24-hour volume

## Why it's different

- **Sentiment about the event, not the price.** Most "prediction market sentiment" just echoes the odds back at you ("Polymarket has this at 60%"). This Actor tells Grok to ignore posts about betting odds and market prices, so the score reflects what people think about the event itself. That makes the gap between sentiment and odds meaningful.
- **Two venues in one call.** Polymarket and Kalshi matched automatically, including the year and price levels in your question (2026 won't match a 2027 market).
- **Pay only for results.** Markets that fail to score are not charged.

## Input

| Field | What it does |
| --- | --- |
| `questions` | Up to 25 market questions. Use the market's own wording for the best match. |
| `includeOdds` | Add live Polymarket and Kalshi odds (default on). |
| `includeKalshi` | Kalshi matching adds about 2 minutes per run; turn off for faster Polymarket-only runs. |

```json
{
  "questions": [
    "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
    "US x Iran ceasefire continues through October 31?"
  ]
}
```

## Output

```json
{
  "question": "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
  "score": 62,
  "catalyst": "Sticky inflation and officials calling another hike reasonable keep an October rise in focus.",
  "volume_signal": "rising",
  "polymarket_yes_pct": 64.5,
  "kalshi_yes_pct": 63.0,
  "polymarket_market": "Will the Fed increase interest rates by 25 bps after the October 2026 meeting?",
  "kalshi_market": "Fed decision in October 2026: Hike 25bps",
  "odds": { "polymarket": { "...": "..." }, "kalshi": { "...": "..." }, "fetched_at": "..." },
  "scored_at": "2026-09-28T14:17:00+00:00",
  "prompt_version": "v2",
  "error": null
}
```

`odds.polymarket` or `odds.kalshi` is `null` when no open market matches your question closely enough. The example values are illustrative.

## Use it from an AI agent

This Actor is available to AI agents through Apify's MCP server. Give your agent a market question; it gets back a sentiment score, catalyst and live odds in one tool call.

## Pricing

Pay per market scored. There is no charge for markets that fail to score, and a run stops at your maximum charge limit.

## Good to know

- Sentiment is a reading of public conversation, not a forecast. **This is not financial or betting advice.**
- Scores come from an AI model reading recent posts on X and can vary between runs.
- Odds are live public prices at the time of the run.

Also available as a pay-per-call API with x402 (USDC on Base): [prediction-bot-iggf.onrender.com](https://prediction-bot-iggf.onrender.com/about).

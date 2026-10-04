# Prediction Market X Sentiment — MCP server

Gives any MCP-capable agent (Claude, Cursor, VS Code and others) **sentiment for Polymarket and Kalshi markets from X (Twitter)**, scored by Grok. Free daily scores out of the box; paid live scoring on any question settles in **USDC on Base via x402**. No account, no API key.

<!-- mcp-name: io.github.wballztrading1/prediction-bot -->

| Tool | Price | What it returns |
|------|-------|-----------------|
| `get_daily_scores` | free | Today's X-sentiment score for each market we track, with the change since yesterday |
| `get_catalog`, `get_pricing`, `get_sample`, `get_health` | free | Routes, prices, example output, status |
| `get_top_markets` | $0.35 | The 3 most-discussed markets on X right now, each scored |
| `get_sentiment_shift(q)` | $0.35 | Change in sentiment since the previous score |
| `get_market_sentiment(q)` | $0.35 | Fresh score -100..100, catalyst and volume trend for any market question |
| `get_market_brief(q)` | $0.35 | Score, change, one-line summary and live Polymarket + Kalshi odds |

Prices can change; the free `get_pricing` tool always has the current ones.

## Option 1: hosted, nothing to install

Add this URL as a remote MCP server (streamable HTTP):

```
https://prediction-bot-iggf.onrender.com/mcp
```

For example, in a client that takes a JSON config:

```json
{
  "mcpServers": {
    "prediction-bot": { "type": "http", "url": "https://prediction-bot-iggf.onrender.com/mcp" }
  }
}
```

Free tools work straight away. The hosted server never pays for anyone: paid tools return the x402 price quote (price, network, pay-to) so your own x402 client can pay, or use option 2.

## Option 2: local, with optional auto-pay

Requires [uv](https://docs.astral.sh/uv/):

```json
{
  "mcpServers": {
    "prediction-bot": {
      "command": "uvx",
      "args": ["prediction-bot-mcp"],
      "env": {
        "PREDICTION_BOT_EVM_PRIVATE_KEY": "<optional: your own Base wallet key>",
        "PREDICTION_BOT_MAX_USD_PER_CALL": "0.50",
        "PREDICTION_BOT_SESSION_BUDGET_USD": "1.00"
      }
    }
  }
}
```

**Without a wallet key**, free tools work and paid tools return the x402 payment quote instead of paying.

**With a wallet key**, paid tools pay automatically. The server never pays more than `PREDICTION_BOT_MAX_USD_PER_CALL` per call or `PREDICTION_BOT_SESSION_BUDGET_USD` per session. Use a dedicated low-balance wallet. The key stays on your machine and is only used to sign USDC payments.

| Env var | Default | Purpose |
|---------|---------|---------|
| `PREDICTION_BOT_API_BASE` | `https://prediction-bot-iggf.onrender.com` | API base URL |
| `PREDICTION_BOT_EVM_PRIVATE_KEY` | unset | Enables auto-pay |
| `PREDICTION_BOT_MAX_USD_PER_CALL` | `0.50` | Hard cap per paid call |
| `PREDICTION_BOT_SESSION_BUDGET_USD` | `1.00` | Cap per server session |

## About the scores

Scores run from -100 (very bearish on the question) to +100 (very bullish), based on recent X posts about the market. They reflect public discussion, not a forecast, and are not financial advice.

Source: https://github.com/wballztrading1/Prediction-bot

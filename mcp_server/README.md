# prediction-bot MCP server

Gives any MCP-capable agent (Claude, Cursor, etc.) live **Polymarket / Kalshi sentiment from X (Twitter)**, scored by Grok. Paid calls settle in **USDC on Base via x402**.

| Tool | Price | What it returns |
|------|-------|-----------------|
| `catalog`, `pricing`, `sample`, `health` | free | Routes, prices, example output, liveness |
| `top` | $0.01 | 3 most-discussed markets on X with scores |
| `shift(q)` | $0.01 | Sentiment change vs the prior score |
| `sentiment(q)` | $0.05 | Score -100..100, catalyst, volume signal |
| `brief(q)` | $0.05 | Score + shift + one-line summary |

## Install

Requires [uv](https://docs.astral.sh/uv/). Add to your MCP client config:

```json
{
  "mcpServers": {
    "prediction-bot": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/wballztrading1/Prediction-bot#subdirectory=mcp_server",
        "prediction-bot-mcp"
      ],
      "env": {
        "PREDICTION_BOT_EVM_PRIVATE_KEY": "<optional: your own Base wallet key>",
        "PREDICTION_BOT_MAX_USD_PER_CALL": "0.05",
        "PREDICTION_BOT_SESSION_BUDGET_USD": "1.00"
      }
    }
  }
}
```

**Without a wallet key**, free tools work and paid tools return the x402 payment quote (price, network, pay-to) instead of paying.

**With a wallet key**, paid tools pay automatically. The server never pays more than `PREDICTION_BOT_MAX_USD_PER_CALL` per call or `PREDICTION_BOT_SESSION_BUDGET_USD` per session. Use a dedicated low-balance wallet. The key stays on your machine and is only used to sign USDC payments.

| Env var | Default | Purpose |
|---------|---------|---------|
| `PREDICTION_BOT_API_BASE` | `https://prediction-bot-iggf.onrender.com` | API base URL |
| `PREDICTION_BOT_EVM_PRIVATE_KEY` | unset | Enables auto-pay |
| `PREDICTION_BOT_MAX_USD_PER_CALL` | `0.05` | Hard cap per paid call |
| `PREDICTION_BOT_SESSION_BUDGET_USD` | `1.00` | Cap per server session |

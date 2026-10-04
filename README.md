# Prediction Market X Sentiment (x402)

Agent-native Polymarket/Kalshi sentiment from live X chatter. Settles in USDC on Base via HTTP 402.

**Live:** https://prediction-bot-iggf.onrender.com · [About](https://prediction-bot-iggf.onrender.com/about) · [llms.txt](https://prediction-bot-iggf.onrender.com/llms.txt) · [API docs](https://prediction-bot-iggf.onrender.com/docs)

## Price ladder

| Route | Price | Notes |
|-------|-------|-------|
| `GET /scores` | free | Latest daily X-sentiment score for each tracked market |
| `GET /`, `/health`, `/sample`, `/catalog`, `/pricing` | free | Discovery / probe |
| `GET /top` | **$0.35** | Top 3 markets by X buzz |
| `GET /shift?q=` | **$0.35** | Change since the previous score |
| `GET /sentiment?q=` | **$0.35** | Fresh Grok X-sentiment score (-100..100) for any question |
| `GET /brief?q=` | **$0.35** | Score + shift + summary + live Polymarket/Kalshi odds |

Current prices are always at `/pricing`.

## Quick probe

```bash
curl -s https://prediction-bot-iggf.onrender.com/health
curl -s https://prediction-bot-iggf.onrender.com/catalog
curl -s https://prediction-bot-iggf.onrender.com/pricing
python demo/pay_once.py   # shows free routes + unpaid 402
```

## For agents: MCP server

Add prediction-market sentiment to any MCP client (Claude, Cursor, VS Code and others). Free tools, including today's scores, work without a wallet; paid tools settle in USDC on Base via x402.

**Hosted, nothing to install:** add `https://prediction-bot-iggf.onrender.com/mcp` as a remote (streamable HTTP) MCP server.

**Local, with optional auto-pay from your own wallet** (per-call and per-session spend caps):

```json
{
  "mcpServers": {
    "prediction-bot": {
      "command": "uvx",
      "args": ["prediction-bot-mcp"]
    }
  }
}
```

Details, wallet setup and caps: [`mcp_server/README.md`](mcp_server/README.md).

## Env (Render)

- `XAI_API_KEY` — required
- `PAY_TO_ADDRESS` — USDC receive address on Base
- `PRICE_LITE` — default `$0.01` (applied to `/top`, `/shift`)
- `PRICE_BRIEF` / `PRICE` — default `$0.05` (applied to `/sentiment`, `/brief`)
- `PUBLIC_BASE_URL` — public service URL for catalog links
- Optional caps: `GROK_COST_USD`, `CALLER_CAP_USD`, `CALLER_GROK_PER_HOUR`, `GLOBAL_GROK_PER_HOUR`

## Tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
TEST_MODE=1 pytest -q
```

Nothing ships without a green test run.

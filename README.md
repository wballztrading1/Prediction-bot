# Prediction Market X Sentiment (x402)

Agent-native Polymarket/Kalshi sentiment from live X chatter. Settles in USDC on Base via HTTP 402.

**Live:** https://prediction-bot-iggf.onrender.com

## Price ladder

| Route | Price | Notes |
|-------|-------|-------|
| `GET /`, `/health`, `/sample`, `/catalog` | free | Discovery / probe |
| `GET /sentiment?q=` | **$0.01** | Lite score (-100..100) |
| `GET /brief?q=` | **$0.05** | Score + shift + summary |
| `GET /shift?q=` | **$0.05** | Delta vs prior cache |
| `GET /top` | **$0.05** | Top 3 markets by X buzz |

## Quick probe

```bash
curl -s https://prediction-bot-iggf.onrender.com/health
curl -s https://prediction-bot-iggf.onrender.com/catalog
python demo/pay_once.py   # shows free routes + unpaid 402
```

## Env (Render)

- `XAI_API_KEY` — required
- `PAY_TO_ADDRESS` — USDC receive address on Base
- `PRICE_LITE` — default `$0.01`
- `PRICE_BRIEF` / `PRICE` — default `$0.05`
- `PUBLIC_BASE_URL` — public service URL for catalog links
- Optional caps: `GROK_COST_USD`, `CALLER_CAP_USD`, `CALLER_GROK_PER_HOUR`, `GLOBAL_GROK_PER_HOUR`

## Tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
TEST_MODE=1 pytest -q
```

Nothing ships without a green test run.

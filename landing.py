"""Human landing page (/about) and agent summary (/llms.txt).

Plain templates with {{NAME}} placeholders so CSS braces need no escaping.
"""

MCP_CMD = (
    "uvx --from git+https://github.com/wballztrading1/Prediction-bot"
    "#subdirectory=mcp_server prediction-bot-mcp"
)
REPO = "https://github.com/wballztrading1/Prediction-bot"


def _fill(template: str, values: dict) -> str:
    for key, val in values.items():
        template = template.replace("{{" + key + "}}", str(val))
    return template


ABOUT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prediction Market X Sentiment API</title>
<meta name="description" content="Pay-per-call Polymarket and Kalshi sentiment from live X chatter, scored by Grok. USDC on Base via x402. Built for AI agents.">
<style>
:root { --bg:#fbfbf9; --fg:#1c1c1a; --muted:#5f5e58; --line:#e3e2dc; --card:#ffffff; --accent:#1f6f5c; --code:#f1f0ea; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141413; --fg:#ecebe6; --muted:#a3a29b; --line:#2e2e2b; --card:#1c1c1a; --accent:#5cc5a7; --code:#23231f; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
main { max-width:760px; margin:0 auto; padding:48px 16px 64px; }
h1 { font-size:2rem; line-height:1.2; margin:0 0 12px; }
h2 { font-size:1.15rem; margin:40px 0 12px; }
p { margin:0 0 12px; }
.lede { color:var(--muted); font-size:1.08rem; }
a { color:var(--accent); }
table { width:100%; border-collapse:collapse; margin:8px 0; font-size:.95rem; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; }
pre { background:var(--code); border:1px solid var(--line); border-radius:8px; padding:12px 14px; overflow-x:auto; font-size:.85rem; margin:8px 0 12px; }
code { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
.tag { display:inline-block; font-size:.78rem; padding:2px 8px; border-radius:99px; border:1px solid var(--line); color:var(--muted); margin-right:6px; }
.links a { margin-right:16px; }
ol li { margin-bottom:6px; }
footer { margin-top:48px; color:var(--muted); font-size:.85rem; }
</style>
</head>
<body>
<main>
<p><span class="tag">x402</span><span class="tag">USDC on Base</span><span class="tag">MCP</span></p>
<h1>Prediction Market X Sentiment</h1>
<p class="lede">Live sentiment for Polymarket and Kalshi markets, scored from X (Twitter) chatter by Grok. Pay per call in USDC on Base. No account, no API key.</p>
<p class="links"><a href="/catalog">Catalog</a><a href="/docs">API docs</a><a href="/llms.txt">llms.txt</a><a href="{{REPO}}">GitHub</a></p>

<h2>Prices</h2>
<table>
<tr><th>Route</th><th>Price</th><th>Returns</th></tr>
<tr><td><code>/catalog</code>, <code>/pricing</code>, <code>/sample</code>, <code>/health</code></td><td>free</td><td>Routes, prices, example output, status</td></tr>
<tr><td><code>/top</code></td><td>{{PRICE_LITE}}</td><td>3 most-discussed markets on X, each scored</td></tr>
<tr><td><code>/shift?q=</code></td><td>{{PRICE_LITE}}</td><td>Change in sentiment since the last score</td></tr>
<tr><td><code>/sentiment?q=</code></td><td>{{PRICE_BRIEF}}</td><td>Score from -100 to 100, catalyst, volume signal</td></tr>
<tr><td><code>/brief?q=</code></td><td>{{PRICE_BRIEF}}</td><td>Score, shift and a one-line summary</td></tr>
</table>
<p>Scores are cached for {{TTL}} seconds per market question.</p>

<h2>Use it from an agent (MCP)</h2>
<p>Add this to your MCP client config (Claude, Cursor and others). Free tools work straight away. Paid tools return a price quote unless you give the server your own wallet, with spend caps per call and per session.</p>
<pre><code>{
  "mcpServers": {
    "prediction-bot": {
      "command": "uvx",
      "args": ["--from", "git+{{REPO}}#subdirectory=mcp_server", "prediction-bot-mcp"]
    }
  }
}</code></pre>

<h2>Use it over HTTP</h2>
<ol>
<li>Call a paid route, e.g. <code>GET {{BASE}}/brief?q=Will+Bitcoin+hit+150k+in+2026</code></li>
<li>You get <strong>HTTP 402</strong>. The base64 <code>PAYMENT-REQUIRED</code> header lists the price, network (<code>{{NETWORK}}</code>) and pay-to address.</li>
<li>Sign a USDC payment with any x402 client and retry with the <code>PAYMENT-SIGNATURE</code> header. You get the JSON result.</li>
</ol>
<pre><code>curl -s {{BASE}}/catalog
curl -s -i "{{BASE}}/brief?q=Will+Bitcoin+hit+150k+in+2026"   # 402 + payment details</code></pre>

<h2>Example response</h2>
<pre><code>{
  "question": "Will Bitcoin hit 150k in 2026",
  "score": 12,
  "catalyst": "ETF inflows",
  "volume_signal": "rising",
  "shift": 16,
  "score_before": -4,
  "summary": "X sentiment score 12 (more bullish vs prior -4; shift +16). Catalyst: ETF inflows",
  "tier": "brief"
}</code></pre>

<footer>
<p>Payments settle to <code>{{PAY_TO}}</code> on Base. Sentiment reflects public X discussion and is not financial advice.</p>
</footer>
</main>
</body>
</html>
"""


LLMS_TXT = """# Prediction Market X Sentiment API

> Pay-per-call sentiment for Polymarket and Kalshi markets, scored from live X (Twitter) chatter by Grok. Payments are USDC on Base ({{NETWORK}}) via the x402 protocol (HTTP 402). No account or API key.

Base URL: {{BASE}}

## Free routes
- [Catalog]({{BASE}}/catalog): every route, price, network and pay-to address (JSON)
- [Pricing]({{BASE}}/pricing): price ladder (JSON)
- [Sample]({{BASE}}/sample): static example response, no live data (JSON)
- [Health]({{BASE}}/health): status and prices (JSON)
- [OpenAPI]({{BASE}}/openapi.json): full schemas for every route

## Paid routes (x402)
- GET /top ({{PRICE_LITE}}): 3 most-discussed Polymarket/Kalshi markets on X, each with score, catalyst, volume_signal
- GET /shift?q=QUESTION ({{PRICE_LITE}}): score change vs the previous cached score
- GET /sentiment?q=QUESTION ({{PRICE_BRIEF}}): score -100..100, catalyst, volume_signal
- GET /brief?q=QUESTION ({{PRICE_BRIEF}}): score, catalyst, volume_signal, shift and one-line summary

q is the exact market question, e.g. "Will Bitcoin hit 150k in 2026". Scores are cached {{TTL}}s per question.

## How to pay
1. Request a paid route; the server answers 402 with a base64 PAYMENT-REQUIRED header (price, network, asset, pay-to).
2. Sign the USDC payment with an x402 client and retry with the PAYMENT-SIGNATURE header.

## MCP
Install as an MCP server: {{MCP_CMD}}
Source and docs: {{REPO}}
"""


def about_html(base: str, price_lite: str, price_brief: str, pay_to: str, network: str, ttl: int) -> str:
    return _fill(
        ABOUT_HTML,
        {
            "BASE": base,
            "PRICE_LITE": price_lite,
            "PRICE_BRIEF": price_brief,
            "PAY_TO": pay_to,
            "NETWORK": network,
            "TTL": ttl,
            "REPO": REPO,
        },
    )


def llms_txt(base: str, price_lite: str, price_brief: str, network: str, ttl: int) -> str:
    return _fill(
        LLMS_TXT,
        {
            "BASE": base,
            "PRICE_LITE": price_lite,
            "PRICE_BRIEF": price_brief,
            "NETWORK": network,
            "TTL": ttl,
            "MCP_CMD": MCP_CMD,
            "REPO": REPO,
        },
    )

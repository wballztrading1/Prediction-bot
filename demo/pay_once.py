#!/usr/bin/env python3
"""Hit free discovery routes, then show unpaid /top returns HTTP 402.

Live settlement needs an x402-capable wallet client (CDP / x402 fetch).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("API_BASE", "https://prediction-bot-iggf.onrender.com").rstrip("/")


def get(path: str):
    url = BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": "prediction-bot-demo/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return e.code, parsed


def main() -> int:
    print(f"base={BASE}")
    for path in ("/health", "/catalog", "/pricing", "/sample"):
        code, data = get(path)
        print(f"\nGET {path} -> {code}")
        print(json.dumps(data, indent=2)[:800] if not isinstance(data, str) else data[:800])

    code, data = get("/top")
    print(f"\nGET /top (unpaid expect 402) -> {code}")
    print(json.dumps(data, indent=2)[:1200] if not isinstance(data, str) else data[:1200])
    if code != 402:
        print("WARN: expected HTTP 402 for unpaid /top", file=sys.stderr)
        return 1
    print(
        "\nNext: retry with an x402 payment header. "
        "Lite /top+/shift are $0.01; full /sentiment+/brief are $0.05."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

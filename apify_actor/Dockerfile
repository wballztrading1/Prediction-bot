# Build context is the repo root (see dockerContextDir in .actor/actor.json),
# so the Actor reuses the live API's odds.py instead of a copy.
FROM apify/actor-python:3.12

# Match every open Kalshi event (about 75 pages), as on the live API.
ENV KALSHI_MAX_PAGES=100

COPY apify_actor/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY odds.py ./odds.py
COPY grok_cost.py ./grok_cost.py
COPY apify_actor/src ./src

CMD ["python3", "-m", "src"]

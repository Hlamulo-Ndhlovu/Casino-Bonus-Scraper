#!/usr/bin/env python3
"""Casino bonus scraper.

Pulls the first 3 casino offers from one public comparison page, uses a
language model to turn the free-text bonus terms into structured fields,
and writes them to bonuses.json.

Run:  python scrape.py
Needs: GEMINI_API_KEY in the environment (free key from aistudio.google.com).
"""

import json
import os
import re
import sys
import time
import urllib.robotparser
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.gambling.com/uk/online-casinos/bonus"
USER_AGENT = "bonus-screening-task/1.0 (small personal project; contact via repo)"
LIMIT = 3
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OUTPUT = "bonuses.json"


# --------------------------------------------------------------------------
# Fetching (polite: robots.txt checked, no bypassing of blocks)
# --------------------------------------------------------------------------
def allowed_by_robots(url: str) -> bool:
    parts = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{parts.scheme}://{parts.netloc}/robots.txt")
    rp.read()
    return rp.can_fetch(USER_AGENT, url)


def fetch(url: str) -> str:
    if not allowed_by_robots(url):
        sys.exit(f"robots.txt disallows fetching {url}. Switch source.")
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if resp.status_code in (401, 403, 429) or "captcha" in resp.text[:5000].lower():
        sys.exit(
            f"Source blocked us (HTTP {resp.status_code}). "
            "Not attempting to bypass; switch source."
        )
    resp.raise_for_status()
    return resp.text


# --------------------------------------------------------------------------
# Parsing: find offer rows without relying on fragile CSS class names.
# Each ranked offer has an anchor to /go/uk/<slug>/offer/<id> whose tracking
# params include ctalocation=bonus-offer; its list item also holds the terms.
# --------------------------------------------------------------------------
def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_offers(html: str, limit: int = LIMIT) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    offers, seen = [], set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/go/uk/" not in href or "ctalocation=bonus-offer" not in href:
            continue
        m = re.search(r"/go/uk/([^/]+)/offer/", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue

        container = a.find_parent("li") or a.parent
        img = container.find("img", alt=True)
        name = clean(img["alt"]) if img and img["alt"] else slug.replace("-", " ").title()

        offer_text = clean(a.get_text(" "))
        # Everything in the row that is not the offer headline: the T&C fine print.
        full_text = clean(container.get_text(" "))
        terms = full_text.replace(offer_text, "", 1)
        idx = terms.find("18+")
        terms = clean(terms[idx:]) if idx != -1 else terms

        review = container.find("a", href=re.compile(r"/online-casinos/reviews/"))
        review_url = review["href"] if review else SOURCE_URL

        seen.add(slug)
        offers.append(
            {
                "casino": name,
                "offer_text": offer_text,
                "terms_text": terms[:1500],
                "review_url": review_url,
            }
        )
        if len(offers) == limit:
            break
    return offers


# --------------------------------------------------------------------------
# LLM step: free text -> structured fields
# --------------------------------------------------------------------------
PROMPT = """You extract structured data from online casino welcome-bonus text.

Casino: {casino}
Offer headline: {offer_text}
Terms (fine print): {terms_text}

Return ONLY a JSON object with exactly these keys:
- "welcome_bonus": string. Short human-readable summary of the offer, e.g. "100% up to £50 + 125 free spins".
- "wagering_multiplier": number or null. The wagering requirement as a multiplier (10x -> 10; no wagering -> 0). Use null if the text does not state one. Do not guess.
- "minimum_deposit": string or null. Minimum deposit with currency, e.g. "£10". Use null if not stated. Do not guess.

Only use information present in the text above."""


def call_llm(prompt: str) -> str:
    resp = requests.post(
        GEMINI_URL.format(model=MODEL),
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def extract_fields(offer: dict) -> dict:
    prompt = PROMPT.format(**offer)
    last_err = None
    for attempt in range(3):
        try:
            raw = call_llm(prompt)
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            return validate(data)
        except Exception as e:  # retry on API hiccups or malformed output
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"LLM extraction failed for {offer['casino']}: {last_err}")


def validate(d: dict) -> dict:
    wm = d.get("wagering_multiplier")
    if wm is not None and not isinstance(wm, (int, float)):
        raise ValueError(f"wagering_multiplier must be a number or null, got {wm!r}")
    for k in ("welcome_bonus", "minimum_deposit"):
        v = d.get(k)
        if v is not None and not isinstance(v, str):
            raise ValueError(f"{k} must be a string or null, got {v!r}")
    if not d.get("welcome_bonus"):
        raise ValueError("welcome_bonus missing")
    return {
        "welcome_bonus": d["welcome_bonus"],
        "wagering_multiplier": wm,
        "minimum_deposit": d.get("minimum_deposit"),
    }


# --------------------------------------------------------------------------
def main() -> None:
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("Set GEMINI_API_KEY first (see README).")

    print(f"Fetching {SOURCE_URL}")
    html = fetch(SOURCE_URL)
    offers = parse_offers(html)
    if len(offers) < LIMIT:
        sys.exit(
            f"Found only {len(offers)} offers; the page layout may have changed."
        )

    results = []
    for o in offers:
        print(f"  extracting: {o['casino']}")
        fields = extract_fields(o)
        results.append(
            {
                "casino": o["casino"],
                **fields,
                "source_url": SOURCE_URL,
            }
        )

    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": SOURCE_URL,
        "casinos": results,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUTPUT} ({len(results)} casinos)")


if __name__ == "__main__":
    main()

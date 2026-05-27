"""Track flight prices via SerpAPI Google Flights, log history, alert on threshold."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

SERPAPI_BASE = "https://serpapi.com/search"
CONFIG_PATH = Path("config.yml")
HISTORY_PATH = Path("history.json")
ALERT_LABEL = "flight-alert"


def search_flights(api_key: str, route: dict) -> dict:
    params = {
        "engine": "google_flights",
        "api_key": api_key,
        "departure_id": route["origin"],
        "arrival_id": route["destination"],
        "outbound_date": route["depart_date"],
        "currency": route.get("currency", "TWD"),
        "hl": "zh-tw",
        "adults": route.get("adults", 1),
    }
    if route.get("return_date"):
        params["return_date"] = route["return_date"]
        params["type"] = 1  # round trip
    else:
        params["type"] = 2  # one way
    if route.get("non_stop", True):
        params["stops"] = 1  # non-stop only

    r = requests.get(SERPAPI_BASE, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def lowest_price(payload: dict, airline_code: str | None) -> float | None:
    candidates = (payload.get("best_flights") or []) + (payload.get("other_flights") or [])
    prices: list[float] = []
    for offer in candidates:
        price = offer.get("price")
        if price is None:
            continue
        if airline_code:
            airlines = {seg.get("airline_code") for seg in (offer.get("flights") or [])}
            if airline_code not in airlines:
                continue
        prices.append(float(price))
    if prices:
        return min(prices)
    insights_low = (payload.get("price_insights") or {}).get("lowest_price")
    return float(insights_low) if insights_low is not None else None


def append_history(route_name: str, price: float, currency: str) -> None:
    history: list[dict] = []
    if HISTORY_PATH.exists():
        history = json.loads(HISTORY_PATH.read_text())
    history.append(
        {
            "route": route_name,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "price": price,
            "currency": currency,
        }
    )
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n")


def open_alert_issue_if_new(repo: str, token: str, route: dict, price: float) -> str | None:
    """Open an issue when price drops below threshold, skipping if one is already open for this route."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    existing = requests.get(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        params={"state": "open", "labels": ALERT_LABEL, "per_page": 100},
        timeout=30,
    )
    existing.raise_for_status()
    for issue in existing.json():
        if route["name"] in issue.get("title", ""):
            return None

    currency = route.get("currency", "TWD")
    body = (
        f"航線：**{route['name']}**\n\n"
        f"| 項目 | 內容 |\n"
        f"|---|---|\n"
        f"| 路線 | {route['origin']} → {route['destination']} |\n"
        f"| 去程 | {route['depart_date']} |\n"
        f"| 回程 | {route.get('return_date', '單程')} |\n"
        f"| 直達 | {route.get('non_stop', True)} |\n"
        f"| 航空 | {route.get('airline', '不限')} |\n"
        f"| 門檻 | {currency} {route['threshold']:,.0f} |\n"
        f"| **目前最低** | **{currency} {price:,.0f}** |\n"
        f"| 檢查時間 (UTC) | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |\n\n"
        f"已跌破門檻。\n\n"
        f"關掉這個 issue 後，下次再跌破才會再開新的。"
    )
    title = f"票價警報: {route['name']} 跌到 {currency} {price:,.0f}"
    r = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        json={"title": title, "body": body, "labels": [ALERT_LABEL]},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["html_url"]


def main() -> int:
    config = yaml.safe_load(CONFIG_PATH.read_text())
    routes = config.get("routes", [])
    if not routes:
        print("config.yml has no routes")
        return 1

    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        print("SERPAPI_KEY env var is required")
        return 1

    gh_token = os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GITHUB_REPOSITORY")

    failures = 0
    for route in routes:
        name = route["name"]
        print(f"== {name} ==", flush=True)
        try:
            payload = search_flights(api_key, route)
        except requests.HTTPError as e:
            print(f"  API error: {e.response.status_code} {e.response.text[:200]}", flush=True)
            failures += 1
            continue

        if payload.get("error"):
            print(f"  SerpAPI error: {payload['error']}", flush=True)
            failures += 1
            continue

        price = lowest_price(payload, route.get("airline"))
        if price is None:
            print("  no offers returned", flush=True)
            continue

        currency = route.get("currency", "TWD")
        print(f"  lowest: {currency} {price:,.0f}", flush=True)
        append_history(name, price, currency)

        threshold = route.get("threshold")
        if threshold and price <= threshold:
            if gh_token and gh_repo:
                url = open_alert_issue_if_new(gh_repo, gh_token, route, price)
                if url:
                    print(f"  ALERT issue opened: {url}", flush=True)
                else:
                    print("  below threshold but an open alert issue already exists", flush=True)
            else:
                print(f"  below threshold ({threshold}) but no GITHUB_TOKEN — skipping issue", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

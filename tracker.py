"""Query Amadeus for flight prices, log history, alert on threshold."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

AMADEUS_BASE = os.environ.get("AMADEUS_BASE", "https://api.amadeus.com")
CONFIG_PATH = Path("config.yml")
HISTORY_PATH = Path("history.json")
ALERT_LABEL = "flight-alert"


def get_token(key: str, secret: str) -> str:
    r = requests.post(
        f"{AMADEUS_BASE}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": key,
            "client_secret": secret,
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search_flights(token: str, route: dict) -> list[dict]:
    params = {
        "originLocationCode": route["origin"],
        "destinationLocationCode": route["destination"],
        "departureDate": route["depart_date"],
        "adults": route.get("adults", 1),
        "currencyCode": route.get("currency", "TWD"),
        "max": 20,
    }
    if route.get("return_date"):
        params["returnDate"] = route["return_date"]
    if route.get("non_stop", True):
        params["nonStop"] = "true"
    if route.get("airline"):
        params["includedAirlineCodes"] = route["airline"]

    r = requests.get(
        f"{AMADEUS_BASE}/v2/shopping/flight-offers",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("data", [])


def lowest_price(offers: list[dict]) -> float | None:
    if not offers:
        return None
    return min(float(o["price"]["grandTotal"]) for o in offers)


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

    key = os.environ.get("AMADEUS_KEY")
    secret = os.environ.get("AMADEUS_SECRET")
    if not key or not secret:
        print("AMADEUS_KEY / AMADEUS_SECRET env vars are required")
        return 1
    token = get_token(key, secret)

    gh_token = os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GITHUB_REPOSITORY")

    failures = 0
    for route in routes:
        name = route["name"]
        print(f"== {name} ==", flush=True)
        try:
            offers = search_flights(token, route)
        except requests.HTTPError as e:
            print(f"  API error: {e.response.status_code} {e.response.text[:200]}", flush=True)
            failures += 1
            continue

        price = lowest_price(offers)
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

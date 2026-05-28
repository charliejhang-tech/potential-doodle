"""Track flight prices via SerpAPI Google Flights, log history, alert on thresholds."""

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
WATCH_LABEL = "flight-watch"


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


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    return json.loads(HISTORY_PATH.read_text())


def historical_low(history: list[dict], route_name: str) -> float | None:
    prices = [h["price"] for h in history if h.get("route") == route_name]
    return min(prices) if prices else None


def append_history(history: list[dict], route_name: str, price: float, currency: str) -> None:
    history.append(
        {
            "route": route_name,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "price": price,
            "currency": currency,
        }
    )
    HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n")


def open_issue_if_new(
    repo: str,
    token: str,
    route: dict,
    price: float,
    kind: str,
    prev_low: float | None,
    is_new_low: bool,
) -> str | None:
    """Open an issue for the given alert kind, skipping if one of that kind is already open for this route."""
    label = ALERT_LABEL if kind == "alert" else WATCH_LABEL
    title_prefix = "票價警報" if kind == "alert" else "票價留意"
    suggestion = "已跌破警報門檻，建議下單。" if kind == "alert" else "進入觀察價位，建議開始留意。"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    existing = requests.get(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        params={"state": "open", "labels": label, "per_page": 100},
        timeout=30,
    )
    existing.raise_for_status()
    for issue in existing.json():
        if route["name"] in issue.get("title", ""):
            return None

    currency = route.get("currency", "TWD")
    new_low_badge = "🎯 " if is_new_low else ""
    threshold_field = (
        route.get("threshold") if kind == "alert" else route.get("watch_threshold")
    )
    body = (
        f"航線：**{route['name']}**\n\n"
        f"| 項目 | 內容 |\n"
        f"|---|---|\n"
        f"| 路線 | {route['origin']} → {route['destination']} |\n"
        f"| 去程 | {route['depart_date']} |\n"
        f"| 回程 | {route.get('return_date', '單程')} |\n"
        f"| 直達 | {route.get('non_stop', True)} |\n"
        f"| 航空 | {route.get('airline', '不限')} |\n"
        f"| 門檻 | {currency} {threshold_field:,.0f} |\n"
        f"| **目前最低** | **{currency} {price:,.0f}**"
        f"{' 🎯 史上新低' if is_new_low else ''} |\n"
        f"| 過去最低 | {f'{currency} {prev_low:,.0f}' if prev_low is not None else '（無紀錄）'} |\n"
        f"| 檢查時間 (UTC) | {datetime.now(timezone.utc).isoformat(timespec='seconds')} |\n\n"
        f"{suggestion}\n\n"
        f"關掉這個 issue 後，下次再跌破才會再開新的。"
    )
    title = f"{new_low_badge}{title_prefix}: {route['name']} 跌到 {currency} {price:,.0f}"
    r = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers=headers,
        json={"title": title, "body": body, "labels": [label]},
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
    history = load_history()

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
        prev_low = historical_low(history, name)
        is_new_low = prev_low is None or price < prev_low
        new_low_marker = " 🎯 NEW LOW" if is_new_low else ""
        print(f"  lowest: {currency} {price:,.0f}{new_low_marker}", flush=True)
        append_history(history, name, price, currency)

        threshold = route.get("threshold")
        watch = route.get("watch_threshold")
        kind: str | None = None
        if threshold and price <= threshold:
            kind = "alert"
        elif watch and price <= watch:
            kind = "watch"

        if kind is None:
            continue
        if not (gh_token and gh_repo):
            print(f"  would alert ({kind}) but no GITHUB_TOKEN — skipping issue", flush=True)
            continue

        url = open_issue_if_new(gh_repo, gh_token, route, price, kind, prev_low, is_new_low)
        if url:
            print(f"  {kind.upper()} issue opened: {url}", flush=True)
        else:
            print(f"  {kind} threshold hit but an open {kind} issue already exists", flush=True)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

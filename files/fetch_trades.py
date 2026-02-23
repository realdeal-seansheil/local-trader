"""
Polymarket Trade Fetcher for distinct-baguette
Pulls all historical trades via Polymarket Data API.

Run: python fetch_trades.py
Output: data/trades_raw.json, data/positions_raw.json, data/activity_raw.json
"""

import requests
import json
import time
import os
from datetime import datetime

WALLET_ADDRESS = "0xe00740bce98a594e26861838885ab310ec3b548c"
DATA_API = "https://data-api.polymarket.com"
DATA_DIR = "data"

os.makedirs(DATA_DIR, exist_ok=True)


def fetch_trades(user: str, limit=1000, offset=0) -> list:
    resp = requests.get(f"{DATA_API}/trades", params={
        "user": user, "limit": limit, "offset": offset, "takerOnly": "false"
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_trades(user: str) -> list:
    all_trades, offset, limit = [], 0, 1000
    while True:
        print(f"  Fetching trades offset={offset}...")
        trades = fetch_trades(user, limit=limit, offset=offset)
        if not trades:
            break
        all_trades.extend(trades)
        print(f"    Got {len(trades)} (total: {len(all_trades)})")
        if len(trades) < limit:
            break
        offset += limit
        time.sleep(0.5)
    return all_trades


def fetch_activity(user: str, limit=1000, offset=0) -> list:
    resp = requests.get(f"{DATA_API}/activity", params={
        "user": user, "limit": limit, "offset": offset
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_activity(user: str) -> list:
    all_activity, offset, limit = [], 0, 1000
    while True:
        print(f"  Fetching activity offset={offset}...")
        activity = fetch_activity(user, limit=limit, offset=offset)
        if not activity:
            break
        all_activity.extend(activity)
        print(f"    Got {len(activity)} (total: {len(all_activity)})")
        if len(activity) < limit:
            break
        offset += limit
        time.sleep(0.5)
    return all_activity


def fetch_positions(user: str) -> list:
    resp = requests.get(f"{DATA_API}/positions", params={"user": user}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_closed_positions(user: str, limit=1000, offset=0) -> list:
    resp = requests.get(f"{DATA_API}/closed-positions", params={
        "user": user, "limit": limit, "offset": offset
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all_closed_positions(user: str) -> list:
    all_positions, offset, limit = [], 0, 1000
    while True:
        print(f"  Fetching closed positions offset={offset}...")
        positions = fetch_closed_positions(user, limit=limit, offset=offset)
        if not positions:
            break
        all_positions.extend(positions)
        print(f"    Got {len(positions)} (total: {len(all_positions)})")
        if len(positions) < limit:
            break
        offset += limit
        time.sleep(0.5)
    return all_positions


def save_json(data, filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved {path} ({len(data) if isinstance(data, list) else 'obj'} records)")


if __name__ == "__main__":
    print(f"=== Fetching data for {WALLET_ADDRESS} ===\n")

    print("[1/4] Trades...")
    trades = fetch_all_trades(WALLET_ADDRESS)
    save_json(trades, "trades_raw.json")

    print("\n[2/4] Activity (trades + splits + merges + redeems)...")
    activity = fetch_all_activity(WALLET_ADDRESS)
    save_json(activity, "activity_raw.json")

    print("\n[3/4] Current positions...")
    try:
        positions = fetch_positions(WALLET_ADDRESS)
        save_json(positions, "positions_raw.json")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n[4/4] Closed positions...")
    closed = fetch_all_closed_positions(WALLET_ADDRESS)
    save_json(closed, "closed_positions_raw.json")

    print(f"\n=== Done! Raw data saved to {DATA_DIR}/ ===")
    print(f"Total trades: {len(trades)}")
    print(f"Total activity: {len(activity)}")
    print(f"Closed positions: {len(closed)}")

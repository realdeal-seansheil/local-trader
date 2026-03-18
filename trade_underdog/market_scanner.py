"""
Market Scanner — Shared utilities for 15-min crypto market scanning.
Fetches markets, parses orderbooks, computes elapsed time.
Adapted from trade_maker/market_scanner.py for underdog strategies.
"""

import calendar
from datetime import datetime

from .config import (
    CRYPTO_SERIES,
    SKIP_HOURS,
    OVERNIGHT_START_HOUR,
    OVERNIGHT_END_HOUR,
)


def compute_elapsed(close_time):
    """
    Compute seconds elapsed since market open (900s window).
    Returns float seconds or None if unparseable.
    """
    if not close_time:
        return None
    try:
        ct = close_time
        if ct.endswith("Z"):
            ct = ct[:-1] + "+00:00"
        close_dt = datetime.fromisoformat(ct)
        close_utc = calendar.timegm(close_dt.timetuple())
        now_utc = calendar.timegm(datetime.utcnow().timetuple())
        return round(900 - (close_utc - now_utc), 1)
    except Exception:
        return None


def parse_orderbook(ob_data):
    """
    Parse Kalshi orderbook response into structured dict.
    Handles both formats:
      - Legacy authenticated: {"orderbook": {"yes": [[price_cents, qty], ...], "no": [...]}}
      - Public / v3 API:      {"orderbook_fp": {"yes_dollars": [["0.55", "100"], ...], "no_dollars": [...]}}
    Returns dict with yes/no bid/ask/depth or None on failure.
    """
    # Try new dollar-string format first (orderbook_fp)
    ob_fp = ob_data.get("orderbook_fp", {})
    if ob_fp:
        yes_raw = ob_fp.get("yes_dollars", [])
        no_raw = ob_fp.get("no_dollars", [])

        if not yes_raw and not no_raw:
            return None

        # Convert dollar strings to [cents, quantity] pairs
        yes_bids = [[round(float(b[0]) * 100), int(float(b[1]))] for b in yes_raw if len(b) >= 2]
        no_bids = [[round(float(b[0]) * 100), int(float(b[1]))] for b in no_raw if len(b) >= 2]
    else:
        # Legacy cent format
        ob = ob_data.get("orderbook", {})
        yes_bids = ob.get("yes", [])
        no_bids = ob.get("no", [])

    if not yes_bids and not no_bids:
        return None

    best_yes_bid = max(b[0] for b in yes_bids) if yes_bids else 0
    best_no_bid = max(b[0] for b in no_bids) if no_bids else 0

    # Ask prices: yes_ask ≈ 100 - best_no_bid, no_ask ≈ 100 - best_yes_bid
    yes_ask = (100 - best_no_bid) if best_no_bid > 0 else (best_yes_bid + 1 if best_yes_bid > 0 else 50)
    no_ask = (100 - best_yes_bid) if best_yes_bid > 0 else (best_no_bid + 1 if best_no_bid > 0 else 50)

    # Depth at best bid (within 2c)
    yes_depth = sum(b[1] for b in yes_bids if b[0] >= best_yes_bid - 2) if yes_bids else 0
    no_depth = sum(b[1] for b in no_bids if b[0] >= best_no_bid - 2) if no_bids else 0

    return {
        "yes_bid": best_yes_bid,
        "no_bid": best_no_bid,
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "yes_depth": yes_depth,
        "no_depth": no_depth,
        "combined_ask": yes_ask + no_ask,
    }


def fetch_all_snapshots(client):
    """
    Scan all 4 crypto series and return market snapshots with orderbook data.
    No window filtering — the executor routes to the correct strategy.

    Returns list of dicts:
        {series, ticker, close_time, elapsed_s, ob, title}
    """
    snapshots = []

    for series in CRYPTO_SERIES:
        try:
            result = client.get_markets(status="open", limit=1, series_ticker=series)
            markets = result.get("markets", [])
        except Exception:
            continue

        if not markets:
            continue

        market = markets[0]
        ticker = market.get("ticker", "")
        close_time = market.get("close_time")

        elapsed_s = compute_elapsed(close_time)
        if elapsed_s is None:
            continue

        # Fetch orderbook
        try:
            ob_data = client.get_orderbook(ticker)
        except Exception:
            continue

        ob = parse_orderbook(ob_data)
        if ob is None:
            continue

        snapshots.append({
            "series": series,
            "ticker": ticker,
            "title": market.get("title", ""),
            "close_time": close_time,
            "elapsed_s": elapsed_s,
            "ob": ob,
        })

    return snapshots


def is_skip_hour():
    """Check if current hour is in the nuclear skip set."""
    return datetime.now().hour in SKIP_HOURS


def is_overnight():
    """Check if current hour is in overnight (thin liquidity) period."""
    current_hour = datetime.now().hour
    return current_hour >= OVERNIGHT_START_HOUR or current_hour < OVERNIGHT_END_HOUR

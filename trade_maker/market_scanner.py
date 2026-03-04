"""
Market Scanner — 15-Min Crypto Favorite-Bias Scanner.
Scans KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M for markets where
the favorite side is priced at 85-97c (longshot at 3-15c),
indicating a favorite-longshot bias edge.

Uses elapsed-time gating to only evaluate markets in the entry window.
"""

import math
import time
import calendar
from datetime import datetime

from .config import (
    CRYPTO_SERIES,
    MIN_FAVORITE_PRICE,
    MAX_FAVORITE_PRICE,
    MIN_ORDERBOOK_DEPTH,
    MIN_EDGE_CENTS,
    MAKER_FEE_COEFFICIENT,
    CONTRACTS_PER_MARKET,
    MAKER_ENTRY_SECONDS,
    MAKER_ENTRY_WINDOW,
    SKIP_HOURS,
    OVERNIGHT_MIN_BID,
    OVERNIGHT_START_HOUR,
    OVERNIGHT_END_HOUR,
)


def calculate_maker_fee(count, price_cents):
    """Kalshi maker fee: ceil(coefficient * C * P * (1-P)) in cents."""
    p = price_cents / 100.0
    raw = MAKER_FEE_COEFFICIENT * count * p * (1 - p) * 100
    return math.ceil(raw) if raw > 0 else 0


def estimate_edge(longshot_price_cents):
    """
    Estimate the favorite-longshot bias edge based on the cheap side's price.

    Academic data (Kalshi-specific, from CEPR/Becker studies):
    - Contracts at 1c: actual win rate ~0.4% (implied 1%) → ~60% overpriced
    - Contracts at 5c: actual ~3% (implied 5%) → ~40% overpriced
    - Contracts at 10c: actual ~8% (implied 10%) → ~20% overpriced
    - Contracts at 15c: actual ~13% (implied 15%) → ~13% overpriced

    Returns estimated edge in percentage points (e.g., 2.0 means 2pp edge).
    """
    if longshot_price_cents <= 1:
        return 0.6   # ~0.6% actual vs 1% implied
    elif longshot_price_cents <= 3:
        return 2.0
    elif longshot_price_cents <= 5:
        return 2.0
    elif longshot_price_cents <= 7:
        return 1.5
    elif longshot_price_cents <= 10:
        return 1.5
    elif longshot_price_cents <= 12:
        return 1.0
    elif longshot_price_cents <= 15:
        return 0.7
    else:
        return 0.0


def compute_elapsed(close_time):
    """
    Compute seconds elapsed since market open (900s window).
    Returns float seconds or None if unparseable.
    Pattern copied from straddle_executor._compute_elapsed().
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


def is_in_entry_window(elapsed_s):
    """Check if elapsed time falls within the maker entry window."""
    entry_start = MAKER_ENTRY_SECONDS - MAKER_ENTRY_WINDOW // 2
    entry_end = MAKER_ENTRY_SECONDS + MAKER_ENTRY_WINDOW // 2
    return entry_start <= elapsed_s <= entry_end


def is_skip_hour():
    """Check if current hour is in the nuclear skip set."""
    return datetime.now().hour in SKIP_HOURS


def get_effective_min_bid():
    """Return the effective minimum favorite bid, accounting for overnight hours."""
    current_hour = datetime.now().hour
    is_overnight = current_hour >= OVERNIGHT_START_HOUR or current_hour < OVERNIGHT_END_HOUR
    return OVERNIGHT_MIN_BID if is_overnight else MIN_FAVORITE_PRICE


def scan_crypto_markets(client):
    """
    Scan 4 crypto 15-min series for favorite-bias maker opportunities.

    For each series:
    1. Fetch the current open market (limit=1)
    2. Compute elapsed time
    3. Only evaluate if in entry window (T=270s to T=330s)
    4. Fetch orderbook, identify favorite/longshot, check thresholds
    5. Apply skip-hour and overnight filters

    Returns (opportunities, scan_metadata).
    """
    opportunities = []
    scan_meta = {
        "series_scanned": 0,
        "series_in_window": 0,
        "series_skipped_hour": 0,
        "series_no_market": 0,
        "series_no_signal": 0,
    }

    skip_hour = is_skip_hour()
    effective_min_bid = get_effective_min_bid()

    for series in CRYPTO_SERIES:
        scan_meta["series_scanned"] += 1

        try:
            result = client.get_markets(
                status="open", limit=1, series_ticker=series
            )
            markets = result.get("markets", [])
        except Exception:
            continue

        if not markets:
            scan_meta["series_no_market"] += 1
            continue

        market = markets[0]
        ticker = market.get("ticker", "")
        close_time = market.get("close_time")

        # Compute elapsed time
        elapsed_s = compute_elapsed(close_time)
        if elapsed_s is None:
            continue

        # Only evaluate if in entry window
        if not is_in_entry_window(elapsed_s):
            continue

        scan_meta["series_in_window"] += 1

        # Skip hour check
        if skip_hour:
            scan_meta["series_skipped_hour"] += 1
            continue

        # Fetch orderbook
        try:
            ob_data = client.get_orderbook(ticker)
        except Exception:
            continue

        opp = _evaluate_crypto_market(
            market, ob_data, elapsed_s, effective_min_bid
        )

        if opp:
            opp["series"] = series
            opp["elapsed_s"] = elapsed_s
            opportunities.append(opp)
        else:
            scan_meta["series_no_signal"] += 1

    return opportunities, scan_meta


def _evaluate_crypto_market(market, ob_data, elapsed_s, effective_min_bid):
    """
    Evaluate a single 15-min crypto market for favorite-bias opportunity.

    Identifies the favorite/longshot sides from orderbook bids,
    estimates edge from academic favorite-longshot bias data,
    and returns an opportunity dict if criteria are met.
    """
    ticker = market.get("ticker", "")

    ob = ob_data.get("orderbook", {})
    yes_bids = ob.get("yes", [])
    no_bids = ob.get("no", [])

    if not yes_bids and not no_bids:
        return None

    best_yes_bid = max(b[0] for b in yes_bids) if yes_bids else 0
    best_no_bid = max(b[0] for b in no_bids) if no_bids else 0

    # Identify favorite/longshot from bid levels
    if best_no_bid >= effective_min_bid:
        favorite_side = "no"
        favorite_price = best_no_bid
        longshot_price = best_yes_bid if best_yes_bid > 0 else 1
        depth = sum(b[1] for b in no_bids if b[0] >= best_no_bid - 2)
    elif best_yes_bid >= effective_min_bid:
        favorite_side = "yes"
        favorite_price = best_yes_bid
        longshot_price = best_no_bid if best_no_bid > 0 else 1
        depth = sum(b[1] for b in yes_bids if b[0] >= best_yes_bid - 2)
    else:
        return None  # No clear favorite at threshold

    # Clamp longshot price
    if longshot_price <= 0:
        longshot_price = 1
    if longshot_price > 15:
        return None  # Not extreme enough for bias edge

    # Price bounds
    if favorite_price < effective_min_bid or favorite_price > MAX_FAVORITE_PRICE:
        return None

    # Depth check
    if depth < MIN_ORDERBOOK_DEPTH:
        return None

    # Edge estimation
    edge_pp = estimate_edge(longshot_price)
    if edge_pp <= 0:
        return None

    # EV calculation
    implied_win_rate = favorite_price / 100.0
    actual_win_rate = implied_win_rate + edge_pp / 100.0
    win_payout = 100 - favorite_price
    loss_cost = favorite_price
    fee = calculate_maker_fee(1, favorite_price)
    ev_per_contract = actual_win_rate * win_payout - (1 - actual_win_rate) * loss_cost - fee

    if ev_per_contract <= MIN_EDGE_CENTS:
        return None

    return {
        "ticker": ticker,
        "title": market.get("title", ""),
        "favorite_side": favorite_side,
        "favorite_price": favorite_price,
        "longshot_price": longshot_price,
        "depth": depth,
        "edge_estimate_pp": round(edge_pp, 2),
        "edge_cents": round(ev_per_contract, 2),
        "contracts": CONTRACTS_PER_MARKET,
        "close_time": market.get("close_time", ""),
        "scan_time": datetime.now().isoformat(),
    }

"""
Market Scanner — 15-Min Crypto Momentum Scanner (mirrors taker strategy).
Scans KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M for momentum entries.
At T=420s (7 min), buys whichever side leads (bid >= 75c).
Places virtual limit orders at the bid price (maker positioning).

Tests whether the taker's 93% WR momentum signal works with 4x lower maker fees.
"""

import math
import time
import calendar
from datetime import datetime

from .config import (
    CRYPTO_SERIES,
    MIN_FAVORITE_PRICE,
    MIN_ORDERBOOK_DEPTH,
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
    """Check if elapsed time falls within the momentum entry window."""
    entry_start = MAKER_ENTRY_SECONDS - MAKER_ENTRY_WINDOW // 2
    entry_end = MAKER_ENTRY_SECONDS + MAKER_ENTRY_WINDOW // 2
    return entry_start <= elapsed_s <= entry_end


def is_skip_hour():
    """Check if current hour is in the nuclear skip set."""
    return datetime.now().hour in SKIP_HOURS


def get_effective_min_bid():
    """Return the effective minimum bid, accounting for overnight hours."""
    current_hour = datetime.now().hour
    is_overnight = current_hour >= OVERNIGHT_START_HOUR or current_hour < OVERNIGHT_END_HOUR
    return OVERNIGHT_MIN_BID if is_overnight else MIN_FAVORITE_PRICE


def scan_crypto_markets(client):
    """
    Scan 4 crypto 15-min series for momentum maker opportunities.

    Mirrors the taker's momentum strategy:
    1. Fetch the current open market (limit=1)
    2. Compute elapsed time
    3. Only evaluate if in entry window (T=405s to T=435s)
    4. Fetch orderbook, identify leader side, check thresholds
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

        opp = _evaluate_momentum(
            market, ob_data, elapsed_s, effective_min_bid
        )

        if opp:
            opp["series"] = series
            opp["elapsed_s"] = elapsed_s
            opportunities.append(opp)
        else:
            scan_meta["series_no_signal"] += 1

    return opportunities, scan_meta


def _evaluate_momentum(market, ob_data, elapsed_s, effective_min_bid):
    """
    Evaluate a single 15-min crypto market for momentum signal.

    Mirrors the taker's logic:
    1. Parse orderbook → yes_bid, no_bid
    2. leader_bid = max(yes_bid, no_bid) — signal strength
    3. buy_side = whichever side has higher bid
    4. buy_price = leader_bid (our limit order rests at the bid)
    5. Check leader_bid >= effective_min_bid

    Returns opportunity dict or None.
    """
    ticker = market.get("ticker", "")

    ob = ob_data.get("orderbook", {})
    yes_bids = ob.get("yes", [])
    no_bids = ob.get("no", [])

    if not yes_bids and not no_bids:
        return None

    best_yes_bid = max(b[0] for b in yes_bids) if yes_bids else 0
    best_no_bid = max(b[0] for b in no_bids) if no_bids else 0

    # Leader = whichever side has higher bid (momentum signal)
    leader_bid = max(best_yes_bid, best_no_bid)

    if leader_bid < effective_min_bid:
        return None

    # Determine buy side and compute depth
    if best_yes_bid >= best_no_bid:
        buy_side = "yes"
        depth = sum(b[1] for b in yes_bids if b[0] >= best_yes_bid - 2)
        # Ask price on YES side: look at NO bids to infer
        # yes_ask ≈ 100 - best_no_bid (if no NO bids, use leader_bid + 1)
        buy_ask = (100 - best_no_bid) if best_no_bid > 0 else leader_bid + 1
    else:
        buy_side = "no"
        depth = sum(b[1] for b in no_bids if b[0] >= best_no_bid - 2)
        # Ask price on NO side: 100 - best_yes_bid
        buy_ask = (100 - best_yes_bid) if best_yes_bid > 0 else leader_bid + 1

    # Depth check
    if depth < MIN_ORDERBOOK_DEPTH:
        return None

    return {
        "ticker": ticker,
        "title": market.get("title", ""),
        "buy_side": buy_side,
        "buy_price": leader_bid,       # our limit order price (at the bid)
        "buy_ask": buy_ask,            # what taker would pay (for Bayesian comparison)
        "leader_bid": leader_bid,      # signal strength
        "depth": depth,
        "contracts": CONTRACTS_PER_MARKET,
        "close_time": market.get("close_time", ""),
        "scan_time": datetime.now().isoformat(),
    }

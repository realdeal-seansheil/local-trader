"""
Market Scanner — Scans Kalshi markets for favorite-bias opportunities.
Identifies markets where one side is priced at extreme levels (1-15c),
indicating a potential favorite-longshot bias edge on the opposite side.

Uses targeted series scanning to avoid the API's parlay/multi-variate
market flood (93%+ of generic results are illiquid KXMVE parlays).
"""

import math
import time
from datetime import datetime

from .config import (
    MIN_FAVORITE_PRICE,
    MAX_FAVORITE_PRICE,
    MIN_ORDERBOOK_DEPTH,
    MIN_EDGE_CENTS,
    MAKER_FEE_COEFFICIENT,
    CONTRACTS_PER_MARKET,
)

# Known liquid series on Kalshi — these have real orderbook activity.
# Updated periodically as new series launch.
TARGET_SERIES = [
    # Sports — season/championship futures (lots of extreme prices)
    "KXNBA", "KXNBAPLAYOFF", "KXNBA1HWINNER", "KXNBA1HTOTAL",
    "KXNHL", "KXMLB", "KXUFC",
    "KXNCAAFSPREAD", "KXNCAAHOCKEYGAME",
    "KXPGAR3LEAD",
    # Crypto — 15min/hourly/daily bracket markets
    "KXBTC", "KXETH", "KXSOL", "KXXRP",
    # Financials / indices
    "KXINX", "INXD", "INXW",
    # Economics
    "KXCPI", "KXGDP", "KXNONFARM", "KXUNEMPLOY",
    # Politics / elections
    "KXNEWPOPE",
    # Weather
    "KXHIGHTEMP",
]

# Max markets to fetch per series (pagination)
MAX_PER_SERIES = 200


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


def categorize_market(market):
    """Infer market category from ticker/title for diversification tracking."""
    ticker = market.get("ticker", "").upper()
    title = (market.get("title") or "").lower()

    if any(k in ticker for k in ["KXBTC", "KXETH", "KXSOL", "KXXRP", "BTC", "ETH"]):
        return "crypto"
    if any(k in ticker for k in ["INX", "NASDAQ", "SPX", "SPY"]):
        return "finance"
    if any(k in ticker for k in ["NFL", "NBA", "MLB", "NHL", "UFC", "PGA", "NCAA"]):
        return "sports"
    if any(w in title for w in ["temperature", "weather", "rain", "snow", "hurricane"]):
        return "weather"
    if any(w in title for w in ["president", "election", "senate", "congress", "governor", "pope"]):
        return "politics"
    if any(w in title for w in ["cpi", "inflation", "fed", "unemployment", "gdp", "nonfarm"]):
        return "economics"
    return "other"


def scan_markets(client):
    """
    Scan targeted Kalshi series for favorite-bias opportunities.

    Two-pass approach:
    1. Fetch markets by series (avoids parlay flood), pre-filter by price/volume
    2. Fetch orderbooks only for candidates with extreme pricing

    Returns list of opportunity dicts sorted by estimated edge (best first).
    """
    # Pass 1: Fetch markets by series, pre-filter by metadata
    candidates = []
    total_scanned = 0
    series_hits = {}

    for series in TARGET_SERIES:
        try:
            result = client.get_markets(
                status="open", limit=MAX_PER_SERIES, series_ticker=series
            )
        except Exception as e:
            continue

        markets = result.get("markets", [])
        series_count = 0

        for market in markets:
            total_scanned += 1
            ticker = market.get("ticker", "")

            # Skip multi-variate / parlay markets that sneak through
            if "KXMVE" in ticker.upper():
                continue

            last_price = market.get("last_price", 0)
            volume = market.get("volume", 0)

            # Must have some activity
            if last_price == 0 and volume == 0:
                continue

            # Only interested in extreme prices (longshot territory)
            if 15 < last_price < 85:
                continue

            candidates.append(market)
            series_count += 1

        if series_count > 0:
            series_hits[series] = series_count

        time.sleep(0.15)  # Light rate limiting between series

    # Pass 2: Fetch orderbooks only for candidates
    opportunities = []
    for i, market in enumerate(candidates):
        opp = _evaluate_market(client, market)
        if opp:
            opportunities.append(opp)
        # Rate limit orderbook calls
        if i % 10 == 9:
            time.sleep(0.3)

    # Sort by edge (best first)
    opportunities.sort(key=lambda x: x["edge_cents"], reverse=True)

    return opportunities, total_scanned, series_hits


def _evaluate_market(client, market):
    """
    Evaluate a single market for favorite-bias opportunity.

    On Kalshi, the orderbook has YES bids and NO bids. Both tend to be at
    low levels (1-15c) for extreme-priced markets. We identify the longshot
    side from last_price and bid levels, then compute the hypothetical maker
    entry price for the favorite side.

    Key insight: buying the favorite (e.g., NO) as a maker means placing
    a NO bid. The taker price = 100 - best_longshot_bid. As a maker, we
    get ~1-2c better by resting an order.
    """
    ticker = market.get("ticker", "")
    last_price = market.get("last_price", 0)

    try:
        ob_data = client.get_orderbook(ticker)
    except Exception:
        return None

    ob = ob_data.get("orderbook", {})
    yes_bids = ob.get("yes", [])
    no_bids = ob.get("no", [])

    if not yes_bids and not no_bids:
        return None

    # Best bids on each side
    best_yes_bid = max(b[0] for b in yes_bids) if yes_bids else 0
    best_no_bid = max(b[0] for b in no_bids) if no_bids else 0

    # Identify the longshot side using last_price and bid levels
    # last_price <= 15 → YES is cheap (longshot YES, favorite NO)
    # last_price >= 85 → YES is expensive (favorite YES, longshot NO)
    if last_price <= 15:
        longshot_side = "yes"
        favorite_side = "no"
        # Use best NO bid as primary signal for favorite price (more reliable than YES bid)
        if best_no_bid >= MIN_FAVORITE_PRICE:
            # Direct NO bid exists — use it as our maker entry price
            favorite_price = best_no_bid
            longshot_price = best_yes_bid if best_yes_bid > 0 else last_price
        elif best_yes_bid > 0:
            # Infer from YES bid: buying NO at 100 - yes_bid (taker), -1 for maker
            longshot_price = best_yes_bid
            favorite_price = 100 - best_yes_bid - 1
        else:
            longshot_price = last_price
            favorite_price = 100 - last_price - 1
        # Depth: contracts on the longshot bid side (our potential counter-parties)
        depth = sum(b[1] for b in yes_bids if b[0] >= best_yes_bid - 2) if yes_bids else 0
        # Also count NO bid depth if available (people willing to buy NO = fellow favorites)
        if best_no_bid >= MIN_FAVORITE_PRICE:
            depth = max(depth, sum(b[1] for b in no_bids if b[0] >= best_no_bid - 2))
    elif last_price >= 85:
        longshot_side = "no"
        favorite_side = "yes"
        if best_yes_bid >= MIN_FAVORITE_PRICE:
            favorite_price = best_yes_bid
            longshot_price = best_no_bid if best_no_bid > 0 else (100 - last_price)
        elif best_no_bid > 0:
            longshot_price = best_no_bid
            favorite_price = 100 - best_no_bid - 1
        else:
            longshot_price = 100 - last_price
            favorite_price = last_price - 1
        depth = sum(b[1] for b in no_bids if b[0] >= best_no_bid - 2) if no_bids else 0
        if best_yes_bid >= MIN_FAVORITE_PRICE:
            depth = max(depth, sum(b[1] for b in yes_bids if b[0] >= best_yes_bid - 2))
    else:
        return None  # Mid-range, no clear longshot

    # Clamp longshot price for edge estimation
    if longshot_price <= 0:
        longshot_price = 1
    if longshot_price > 15:
        return None  # Not extreme enough

    # Check favorite price bounds
    if favorite_price < MIN_FAVORITE_PRICE or favorite_price > MAX_FAVORITE_PRICE:
        return None

    # Check depth
    if depth < MIN_ORDERBOOK_DEPTH:
        return None

    # Estimate edge
    edge_pp = estimate_edge(longshot_price)
    if edge_pp <= 0:
        return None

    # EV calculation:
    # Buy favorite at favorite_price c. Risk = favorite_price. Win = 100 - favorite_price.
    # Actual win rate = implied + edge from longshot bias.
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
        "category": categorize_market(market),
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

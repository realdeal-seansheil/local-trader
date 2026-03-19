"""
Spot Price Feed — Binance US REST API for BTC/ETH/SOL/XRP spot prices.

Polls every cycle, tracks window-open prices, computes spot delta and
detects divergence between Kalshi leader direction and actual spot movement.
"""

import time
from collections import deque

import requests

from .config import (
    BINANCE_BASE_URL,
    SPOT_FEED_ENABLED,
    SPOT_DIVERGENCE_THRESHOLD,
)

# Map Kalshi series to Binance symbols
SERIES_TO_SYMBOL = {
    "KXBTC15M": "BTCUSDT",
    "KXETH15M": "ETHUSDT",
    "KXSOL15M": "SOLUSDT",
    "KXXRP15M": "XRPUSDT",
}

# Max price history entries (~400 = 20min at 3s interval)
_MAX_HISTORY = 400


class SpotFeed:
    def __init__(self):
        self._session = requests.Session()
        self._session.timeout = 3
        self._window_open_prices = {}   # (series, close_time) -> price
        self._price_history = {}        # series -> deque of (ts, price)
        self._latest_prices = {}        # series -> float

    def update(self, snapshots, context=None):
        """
        Fetch spot prices and compute enrichment for each series.
        Returns {series: {spot_price, spot_delta_pct, spot_direction, leader_divergent}}
        """
        if not SPOT_FEED_ENABLED:
            return {}

        result = {}
        now = time.time()

        # Determine unique series in this batch
        series_set = {s["series"] for s in snapshots}

        for series in series_set:
            symbol = SERIES_TO_SYMBOL.get(series)
            if not symbol:
                continue

            price = self._fetch_price(symbol)
            if price is None:
                result[series] = {}
                continue

            self._latest_prices[series] = price

            # Maintain price history
            if series not in self._price_history:
                self._price_history[series] = deque(maxlen=_MAX_HISTORY)
            self._price_history[series].append((now, price))

            # Find close_time for this series from snapshots
            close_time = None
            leader_side = None
            for snap in snapshots:
                if snap["series"] == series:
                    close_time = snap.get("close_time")
                    ob = snap.get("ob", {})
                    if ob.get("yes_bid", 0) >= ob.get("no_bid", 0):
                        leader_side = "yes"  # market thinks price goes UP
                    else:
                        leader_side = "no"   # market thinks price goes DOWN
                    break

            # Track window-open price
            window_key = (series, close_time)
            if window_key not in self._window_open_prices:
                self._window_open_prices[window_key] = price

            open_price = self._window_open_prices[window_key]

            # Compute delta
            if open_price > 0:
                spot_delta_pct = (price - open_price) / open_price * 100
            else:
                spot_delta_pct = 0.0

            # Direction
            if spot_delta_pct > SPOT_DIVERGENCE_THRESHOLD:
                spot_direction = "up"
            elif spot_delta_pct < -SPOT_DIVERGENCE_THRESHOLD:
                spot_direction = "down"
            else:
                spot_direction = "flat"

            # Divergence: Kalshi leader says one thing, spot says another
            leader_divergent = False
            if leader_side and spot_direction != "flat":
                if leader_side == "yes" and spot_direction == "down":
                    leader_divergent = True
                elif leader_side == "no" and spot_direction == "up":
                    leader_divergent = True

            result[series] = {
                "spot_price": round(price, 4),
                "spot_open": round(open_price, 4),
                "spot_delta_pct": round(spot_delta_pct, 4),
                "spot_direction": spot_direction,
                "leader_divergent": leader_divergent,
            }

        # Prune old window-open entries
        self._prune_old_windows(snapshots)

        return result

    def get_price_history(self, series):
        """Expose history for vol_regime to consume."""
        return list(self._price_history.get(series, []))

    def get_latest_price(self, series):
        """Get most recent spot price for a series."""
        return self._latest_prices.get(series)

    def _fetch_price(self, symbol):
        """Single Binance REST call. Returns float price or None on failure."""
        try:
            url = f"{BINANCE_BASE_URL}/ticker/price?symbol={symbol}"
            resp = self._session.get(url, timeout=3)
            if resp.status_code == 200:
                return float(resp.json()["price"])
        except Exception:
            pass
        return None

    def _prune_old_windows(self, snapshots):
        """Remove window-open prices for closed markets."""
        active_keys = set()
        for snap in snapshots:
            active_keys.add((snap["series"], snap.get("close_time")))

        stale = [k for k in self._window_open_prices if k not in active_keys]
        for k in stale:
            del self._window_open_prices[k]

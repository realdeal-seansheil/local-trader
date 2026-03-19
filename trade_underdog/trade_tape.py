"""
Trade Tape Velocity — Compute trade frequency and volume acceleration
from Kalshi's trades API.

Caches trade fetches with a short TTL so _check_fills() can reuse them.
"""

import time
from datetime import datetime, timezone

from .config import TRADE_TAPE_ENABLED


class TradeTapeVelocity:
    CACHE_TTL = 2.5  # seconds, slightly under 3s loop interval
    WINDOWS = [30, 60, 120]  # seconds

    def __init__(self, client):
        self._client = client
        self._trade_cache = {}  # ticker -> (fetch_time, trades_list)

    def update(self, snapshots, context=None):
        """
        Fetch recent trades per ticker and compute velocity metrics.
        Returns {ticker: {trades_30s, trades_60s, trades_120s,
                         velocity_30s, velocity_60s, velocity_120s,
                         acceleration}}
        """
        if not TRADE_TAPE_ENABLED:
            return {}

        result = {}
        now = time.time()
        now_utc = datetime.now(timezone.utc)

        for snap in snapshots:
            ticker = snap["ticker"]
            trades = self._fetch_trades(ticker)
            if trades is None:
                result[ticker] = {}
                continue

            # Parse trade timestamps and bucket into windows
            window_counts = {w: 0 for w in self.WINDOWS}

            for trade in trades:
                created = trade.get("created_time", "")
                if not created:
                    continue
                try:
                    ct = created
                    if ct.endswith("Z"):
                        ct = ct[:-1] + "+00:00"
                    trade_dt = datetime.fromisoformat(ct)
                    age_s = (now_utc - trade_dt).total_seconds()

                    for w in self.WINDOWS:
                        if age_s <= w:
                            window_counts[w] += 1
                except Exception:
                    continue

            # Compute velocity (trades per minute) for each window
            velocities = {}
            for w in self.WINDOWS:
                minutes = w / 60.0
                velocities[w] = window_counts[w] / minutes if minutes > 0 else 0

            # Acceleration: short-term velocity vs long-term velocity
            acceleration = velocities.get(30, 0) - velocities.get(120, 0)

            result[ticker] = {
                "trades_30s": window_counts.get(30, 0),
                "trades_60s": window_counts.get(60, 0),
                "trades_120s": window_counts.get(120, 0),
                "velocity_30s": round(velocities.get(30, 0), 2),
                "velocity_60s": round(velocities.get(60, 0), 2),
                "velocity_120s": round(velocities.get(120, 0), 2),
                "acceleration": round(acceleration, 2),
            }

        return result

    def get_cached_trades(self, ticker):
        """
        Return cached trades if still fresh, else None.
        Used by _check_fills() to avoid duplicate API calls.
        """
        entry = self._trade_cache.get(ticker)
        if entry and (time.time() - entry[0]) < self.CACHE_TTL:
            return entry[1]
        return None

    def _fetch_trades(self, ticker):
        """Fetch trades with caching."""
        now = time.time()

        # Check cache
        entry = self._trade_cache.get(ticker)
        if entry and (now - entry[0]) < self.CACHE_TTL:
            return entry[1]

        # Fresh fetch
        try:
            data = self._client.get_trades(ticker=ticker, limit=50)
            trades = data.get("trades", [])
            self._trade_cache[ticker] = (now, trades)
            return trades
        except Exception:
            return None

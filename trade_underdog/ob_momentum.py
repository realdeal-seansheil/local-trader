"""
Orderbook Momentum — Track bid/depth changes over a rolling window.

Zero additional API calls. Computes bid_delta, bid_velocity, depth_delta
from the existing OB snapshots collected every 3s.
"""

import time
from collections import deque

from .config import OB_MOMENTUM_WINDOW


class OBMomentum:
    def __init__(self, window_size=None):
        self._window_size = window_size or OB_MOMENTUM_WINDOW
        self._history = {}  # ticker -> deque of (ts, yes_bid, no_bid, yes_depth, no_depth)

    def update(self, snapshots, context=None):
        """
        Track OB changes per ticker.
        Returns {ticker: {bid_delta, bid_velocity, depth_delta, leader_stable, yes_bid_trend, no_bid_trend}}
        """
        result = {}
        now = time.time()

        for snap in snapshots:
            ticker = snap["ticker"]
            ob = snap.get("ob", {})

            yes_bid = ob.get("yes_bid", 0)
            no_bid = ob.get("no_bid", 0)
            yes_depth = ob.get("yes_depth", 0)
            no_depth = ob.get("no_depth", 0)

            # Initialize or append
            if ticker not in self._history:
                self._history[ticker] = deque(maxlen=self._window_size)
            self._history[ticker].append((now, yes_bid, no_bid, yes_depth, no_depth))

            buf = self._history[ticker]

            if len(buf) < 3:
                result[ticker] = {
                    "bid_delta": 0,
                    "bid_velocity": 0.0,
                    "depth_delta": 0,
                    "leader_stable": True,
                    "yes_bid_trend": 0,
                    "no_bid_trend": 0,
                }
                continue

            # Current and oldest entries
            oldest = buf[0]
            time_span = now - oldest[0]
            if time_span < 0.1:
                time_span = 0.1

            # Leader bid: whichever side is higher
            current_leader = max(yes_bid, no_bid)
            oldest_leader = max(oldest[1], oldest[2])

            bid_delta = current_leader - oldest_leader
            bid_velocity = bid_delta / time_span  # cents per second

            # Depth delta (leader side)
            if yes_bid >= no_bid:
                current_depth = yes_depth
                oldest_depth = oldest[3]
            else:
                current_depth = no_depth
                oldest_depth = oldest[4]
            depth_delta = current_depth - oldest_depth

            # Leader stable = hasn't moved more than 2c in the window
            leader_stable = abs(bid_delta) <= 2

            # Per-side trends
            yes_bid_trend = yes_bid - oldest[1]
            no_bid_trend = no_bid - oldest[2]

            result[ticker] = {
                "bid_delta": bid_delta,
                "bid_velocity": round(bid_velocity, 3),
                "depth_delta": depth_delta,
                "leader_stable": leader_stable,
                "yes_bid_trend": yes_bid_trend,
                "no_bid_trend": no_bid_trend,
            }

        # Prune tickers no longer in snapshots
        active_tickers = {s["ticker"] for s in snapshots}
        stale = [t for t in self._history if t not in active_tickers]
        for t in stale:
            del self._history[t]

        return result

"""
Signal Logger — Strategy 6: Underdog Opportunity Observation.
Logs all instances where the cheap side is below the threshold,
building a dataset for future Bayesian calibration.
No trading — pure data collection.
"""

import os
import json
from datetime import datetime

from .config import DATA_DIR, SIGNAL_OBS_THRESHOLD


SIGNAL_LOG = os.path.join(DATA_DIR, "underdog_signals.jsonl")


class SignalLogger:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._logged_tickers = {}  # ticker -> last_logged_elapsed (avoid spam)

    def log_from_snapshots(self, snapshots):
        """
        Evaluate each snapshot for underdog opportunities and log them.
        Logs when either side's ask is below SIGNAL_OBS_THRESHOLD (30c).

        Args:
            snapshots: list of {series, ticker, elapsed_s, ob, close_time, ...}
        """
        ts = datetime.now()
        hour = ts.hour

        for snap in snapshots:
            ob = snap["ob"]
            ticker = snap["ticker"]
            elapsed_s = snap["elapsed_s"]

            # Determine which side is the underdog (cheaper to buy)
            yes_ask = ob["yes_ask"]
            no_ask = ob["no_ask"]

            # Check if either side qualifies as an underdog opportunity
            if yes_ask < SIGNAL_OBS_THRESHOLD:
                underdog_side = "yes"
                underdog_ask = yes_ask
                favorite_bid = ob["no_bid"]
                underdog_depth = ob["yes_depth"]
            elif no_ask < SIGNAL_OBS_THRESHOLD:
                underdog_side = "no"
                underdog_ask = no_ask
                favorite_bid = ob["yes_bid"]
                underdog_depth = ob["no_depth"]
            else:
                continue  # No underdog opportunity

            # Throttle: only log once per 30s per ticker to avoid spam
            last_logged = self._logged_tickers.get(ticker, -999)
            if elapsed_s - last_logged < 30:
                continue
            self._logged_tickers[ticker] = elapsed_s

            entry = {
                "ts": ts.isoformat(),
                "ticker": ticker,
                "series": snap["series"],
                "close_time": snap["close_time"],
                "elapsed_s": elapsed_s,
                "underdog_side": underdog_side,
                "underdog_ask": underdog_ask,
                "favorite_bid": favorite_bid,
                "underdog_depth": underdog_depth,
                "hour": hour,
                "combined_ask": ob["combined_ask"],
                "settlement_result": None,  # Backfilled after settlement
            }

            with open(SIGNAL_LOG, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")

    def cleanup_tickers(self, active_tickers):
        """Remove old tickers from throttle cache."""
        to_remove = [t for t in self._logged_tickers if t not in active_tickers]
        for t in to_remove:
            del self._logged_tickers[t]

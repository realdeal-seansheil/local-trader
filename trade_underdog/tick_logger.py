"""
Tick Logger — Full T=0 to T=900 passive tick collection.
Captures orderbook snapshots for all 15-min crypto markets throughout
their entire lifecycle, filling the gap in existing straddle data
(which only starts at ~T=357s).
"""

import os
import json
from datetime import datetime

from .config import DATA_DIR


class TickLogger:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._file_handles = {}

    def log_from_snapshots(self, snapshots):
        """
        Log tick data from pre-fetched market snapshots.
        One JSONL line per snapshot per series.

        Args:
            snapshots: list of {series, ticker, elapsed_s, ob, ...}
        """
        ts = datetime.now().isoformat()

        for snap in snapshots:
            ob = snap["ob"]
            entry = {
                "ts": ts,
                "ticker": snap["ticker"],
                "series": snap["series"],
                "elapsed_s": snap["elapsed_s"],
                "yes_bid": ob["yes_bid"],
                "no_bid": ob["no_bid"],
                "yes_ask": ob["yes_ask"],
                "no_ask": ob["no_ask"],
                "combined_ask": ob["combined_ask"],
                "yes_depth": ob["yes_depth"],
                "no_depth": ob["no_depth"],
            }

            log_path = os.path.join(DATA_DIR, f"underdog_ticks_{snap['ticker']}.jsonl")
            with open(log_path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")

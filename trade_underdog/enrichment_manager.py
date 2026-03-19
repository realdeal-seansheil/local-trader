"""
Enrichment Manager — Orchestrates all 5 signal enrichment sources.

Runs after fetch_all_snapshots(), attaches enrichment data to each snapshot
dict before strategy scans consume them.
"""

import time

from .spot_feed import SpotFeed
from .ob_momentum import OBMomentum
from .cross_series import CrossSeriesCorrelation
from .trade_tape import TradeTapeVelocity
from .vol_regime import VolatilityRegime


class EnrichmentManager:
    def __init__(self, client):
        self.spot_feed = SpotFeed()
        self.ob_momentum = OBMomentum()
        self.cross_series = CrossSeriesCorrelation()
        self.trade_tape = TradeTapeVelocity(client)
        self.vol_regime = VolatilityRegime(self.spot_feed)

        # Timing instrumentation
        self._last_enrich_ms = 0

    def enrich(self, snapshots):
        """
        Run all enrichments in order, attach results to snapshot dicts.
        Returns the mutated snapshots list.
        """
        if not snapshots:
            return snapshots

        start = time.time()

        # 1. Spot feed (must run first — vol_regime depends on it)
        spot_data = self.spot_feed.update(snapshots)

        # 2. OB Momentum (independent, no API calls)
        momentum_data = self.ob_momentum.update(snapshots)

        # 3. Cross-series correlation (independent, no API calls)
        cross_data = self.cross_series.update(snapshots)
        cross_context = cross_data.get("cross", {})

        # 4. Trade tape velocity (independent, API calls with caching)
        tape_data = self.trade_tape.update(snapshots)

        # 5. Volatility regime (depends on spot_feed having run)
        vol_data = self.vol_regime.update(snapshots)

        # Merge onto snapshots
        for snap in snapshots:
            series = snap["series"]
            ticker = snap["ticker"]

            snap["spot"] = spot_data.get(series, {})
            snap["momentum"] = momentum_data.get(ticker, {})
            snap["cross_series"] = cross_context
            snap["tape"] = tape_data.get(ticker, {})
            snap["vol_regime"] = vol_data.get(series, {})

        self._last_enrich_ms = round((time.time() - start) * 1000)

        return snapshots

    def get_trade_cache(self, ticker):
        """Expose trade tape cache for fill detection reuse."""
        return self.trade_tape.get_cached_trades(ticker)

    def get_enrich_latency_ms(self):
        """Return last enrichment cycle latency in ms."""
        return self._last_enrich_ms

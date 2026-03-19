"""
Volatility Regime Detection — Classify current market volatility from
spot price returns over a rolling 20-min window.

Depends on SpotFeed having run first (reads its price history).
"""

from .config import VOL_LOW_THRESHOLD, VOL_HIGH_THRESHOLD


class VolatilityRegime:
    # Minimum data points needed (~2 min at 3s interval = 40 points)
    MIN_HISTORY = 40

    def __init__(self, spot_feed):
        self._spot_feed = spot_feed

    def update(self, snapshots, context=None):
        """
        Classify volatility regime per series from spot price history.
        Returns {series: {regime, spot_vol_20m, regime_action}}
        """
        result = {}
        series_set = {s["series"] for s in snapshots}

        for series in series_set:
            history = self._spot_feed.get_price_history(series)

            if len(history) < self.MIN_HISTORY:
                result[series] = {
                    "regime": "unknown",
                    "spot_vol_20m": 0.0,
                    "regime_action": "normal",
                }
                continue

            # Compute 20-min absolute return
            oldest_price = history[0][1]
            latest_price = history[-1][1]

            if oldest_price > 0:
                abs_return_pct = abs(latest_price - oldest_price) / oldest_price * 100
            else:
                abs_return_pct = 0.0

            # Also compute intra-window volatility (std of returns)
            # Use price changes between consecutive snapshots
            returns = []
            for i in range(1, len(history)):
                prev_price = history[i - 1][1]
                curr_price = history[i][1]
                if prev_price > 0:
                    ret = (curr_price - prev_price) / prev_price * 100
                    returns.append(ret)

            if returns:
                mean_ret = sum(returns) / len(returns)
                variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std_dev = variance ** 0.5
            else:
                std_dev = 0.0

            # Classify regime using absolute return as primary signal
            if abs_return_pct < VOL_LOW_THRESHOLD:
                regime = "low_vol"
                regime_action = "skip_early"  # not enough movement for early entries
            elif abs_return_pct > VOL_HIGH_THRESHOLD:
                regime = "high_vol"
                regime_action = "skip_fade"  # momentum too strong, fades get crushed
            else:
                regime = "normal"
                regime_action = "normal"

            result[series] = {
                "regime": regime,
                "spot_vol_20m": round(abs_return_pct, 4),
                "spot_std_dev": round(std_dev, 6),
                "regime_action": regime_action,
            }

        return result

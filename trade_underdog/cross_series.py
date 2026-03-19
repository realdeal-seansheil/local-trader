"""
Cross-Series Correlation — Compare leader directions across all 4 crypto series.

Stateless computation. Zero API calls. Detects whether BTC/ETH/SOL/XRP
agree on direction (broad-based move) or diverge (weaker signal).
"""

from .config import CROSS_SERIES_MIN_AGREEMENT


class CrossSeriesCorrelation:
    def __init__(self):
        pass  # stateless

    def update(self, snapshots, context=None):
        """
        Compare leader directions across all series in this cycle.
        Returns {"cross": {agreement_count, agreement_pct, all_same_direction,
                          leader_directions, bid_spread_range, majority_direction}}
        """
        if not snapshots:
            return {"cross": {}}

        # Determine leader direction and bid per series
        leader_directions = {}  # series -> "yes" or "no"
        leader_bids = {}        # series -> int

        for snap in snapshots:
            series = snap["series"]
            ob = snap.get("ob", {})
            yes_bid = ob.get("yes_bid", 0)
            no_bid = ob.get("no_bid", 0)

            if yes_bid >= no_bid:
                leader_directions[series] = "yes"
                leader_bids[series] = yes_bid
            else:
                leader_directions[series] = "no"
                leader_bids[series] = no_bid

        if not leader_directions:
            return {"cross": {}}

        # Count agreement
        yes_count = sum(1 for d in leader_directions.values() if d == "yes")
        no_count = sum(1 for d in leader_directions.values() if d == "no")
        total = len(leader_directions)

        majority_direction = "yes" if yes_count >= no_count else "no"
        agreement_count = max(yes_count, no_count)
        agreement_pct = agreement_count / total if total > 0 else 0

        # Bid spread range
        bids = list(leader_bids.values())
        bid_spread_range = max(bids) - min(bids) if bids else 0

        return {
            "cross": {
                "agreement_count": agreement_count,
                "agreement_pct": round(agreement_pct, 2),
                "all_same_direction": agreement_count == total,
                "majority_direction": majority_direction,
                "leader_directions": leader_directions,
                "bid_spread_range": bid_spread_range,
                "min_agreement_met": agreement_count >= CROSS_SERIES_MIN_AGREEMENT,
            }
        }

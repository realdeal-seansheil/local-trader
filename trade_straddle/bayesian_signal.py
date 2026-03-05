"""
Bayesian Signal Engine for momentum entry evaluation.

Computes P(win | leader_bid, series, hour) using empirical Bayes
on historical trade data. Applies Kelly criterion for position sizing.

Features conditioned on:
  - price_bin: 5-cent buckets of entry price (dominant signal)
  - series: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M (secondary)
  - hour: 0-23 (hour of entry in local time) (secondary)

Approach: price-bin win rate is the primary posterior estimate.
Series and hour provide dampened additive adjustments to avoid
the naive Bayes independence assumption destroying signal at
extreme price points (e.g., 95c+ where price is 99% predictive).

No external dependencies — stdlib only.
"""

import json
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple


@dataclass
class SignalResult:
    """Output of the Bayesian signal evaluation."""
    posterior: float                  # P(win) given all features [0, 1]
    confidence: int                  # min historical trades in any feature bin
    kelly_fraction: float            # raw Kelly fraction (negative = don't bet)
    recommended_contracts: int       # Kelly-sized position (0 = skip)
    ev_per_contract_cents: float     # expected value per contract in cents
    bankroll_cents: int              # bankroll used for sizing
    features: dict                   # feature values used
    breakdown: dict                  # per-feature likelihood ratios
    old_decision: dict               # what static logic would have done


# Minimum samples before trusting a bin's raw win rate
_SMOOTHING_N = 10


class BayesianSignal:
    """
    Empirical Bayes signal engine for momentum entries.

    On init, loads straddle_history.jsonl and builds lookup tables
    for P(win | feature) across three conditioning dimensions.
    """

    def __init__(self, data_dir, config, kalshi_client=None):
        """
        Args:
            data_dir: path to trade_straddle/data/
            config: dict with keys:
                kelly_multiplier, bankroll_cents, min_contracts, max_contracts,
                max_bankroll_pct, min_confidence, fee_rate,
                conviction_tiers, min_bid, overnight_min_bid,
                use_live_balance, balance_cache_seconds
            kalshi_client: KalshiClient instance for live balance calls
        """
        self.data_dir = data_dir
        self.config = config
        self.client = kalshi_client

        # Kelly parameters
        self.kelly_multiplier = config.get("kelly_multiplier", 0.25)
        self.bankroll_fallback = config.get("bankroll_cents", 5000)
        self.min_contracts = config.get("min_contracts", 1)
        self.max_contracts = config.get("max_contracts", 15)
        self.max_bankroll_pct = config.get("max_bankroll_pct", 0.05)
        self.min_confidence = config.get("min_confidence", 10)
        self.fee_rate = config.get("fee_rate", 0.007)
        self.use_live_balance = config.get("use_live_balance", True)
        self.balance_cache_seconds = config.get("balance_cache_seconds", 60)

        # Static logic params for old_decision comparison
        self.conviction_tiers = config.get("conviction_tiers", {75: 8, 80: 10})
        self.static_min_bid = config.get("min_bid", 75)
        self.static_overnight_min_bid = config.get("overnight_min_bid", 86)

        # Balance cache
        self._cached_balance = None
        self._balance_cache_time = 0

        # Dampening factor for secondary features (series, hour)
        # Prevents multiplicative LR drag from overwhelming the price signal
        self.secondary_dampening = config.get("secondary_dampening", 0.3)

        # Calibration tables (populated by _calibrate)
        self.base_rate = 0.5
        self.price_wr = {}    # price_bin -> smoothed win rate
        self.series_wr = {}   # series -> smoothed win rate
        self.hour_wr = {}     # hour -> smoothed win rate
        self.price_n = {}     # price_bin -> sample count
        self.series_n = {}    # series -> sample count
        self.hour_n = {}      # hour -> sample count
        self.total_calibration_trades = 0

        self._calibrate()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def _calibrate(self):
        """Load history and build empirical win rate lookup tables."""
        history_path = os.path.join(self.data_dir, "straddle_history.jsonl")
        if not os.path.exists(history_path):
            print("  [Bayesian] WARNING: No history file found, using flat priors")
            self.base_rate = 0.5
            return

        # Load momentum entries with known outcomes
        entries = []
        with open(history_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    h = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Filter to momentum entries (one side entry_price == 0)
                yes_p = h.get("yes_entry_price", 0)
                no_p = h.get("no_entry_price", 0)
                if yes_p != 0 and no_p != 0:
                    continue  # straddle, not momentum

                result = h.get("settlement_result")
                if result not in ("yes", "no"):
                    continue  # not yet settled

                # Derive features
                entry_price = max(yes_p, no_p)  # the side we bought (ask price)
                buy_side = "yes" if yes_p > no_p else "no"
                won = (result == buy_side)

                # Parse hour from entry_time
                entry_time = h.get("entry_time", "")
                try:
                    hour = datetime.fromisoformat(entry_time).hour
                except (ValueError, TypeError):
                    hour = 12  # fallback

                series = h.get("series", "UNKNOWN")
                price_bin = (entry_price // 5) * 5

                entries.append({
                    "won": won,
                    "price_bin": price_bin,
                    "series": series,
                    "hour": hour,
                    "entry_price": entry_price,
                })

        if not entries:
            print("  [Bayesian] WARNING: No momentum entries found in history")
            self.base_rate = 0.5
            return

        self.total_calibration_trades = len(entries)

        # Base rate
        total_wins = sum(1 for e in entries if e["won"])
        self.base_rate = total_wins / len(entries)

        # Build per-feature smoothed win rate tables
        self.price_wr, self.price_n = self._build_wr(entries, "price_bin")
        self.series_wr, self.series_n = self._build_wr(entries, "series")
        self.hour_wr, self.hour_n = self._build_wr(entries, "hour")

        self.print_calibration()

    def _build_wr(self, entries, feature_key):
        """
        Build smoothed win rate table for a given feature.

        Uses Laplace smoothing: blend toward base_rate for small samples.
        """
        bins = defaultdict(lambda: {"wins": 0, "total": 0})
        for e in entries:
            val = e[feature_key]
            bins[val]["total"] += 1
            if e["won"]:
                bins[val]["wins"] += 1

        wr_table = {}
        n_table = {}
        for val, counts in bins.items():
            wins = counts["wins"]
            total = counts["total"]
            n_table[val] = total

            # Laplace smoothing: blend toward base_rate for small samples
            smoothed_wr = (wins + self.base_rate * _SMOOTHING_N) / (total + _SMOOTHING_N)
            wr_table[val] = smoothed_wr

        return wr_table, n_table

    def print_calibration(self):
        """Print calibration summary tables."""
        print(f"\n  {'='*60}")
        print(f"  BAYESIAN SIGNAL ENGINE — Calibration")
        print(f"  {self.total_calibration_trades} momentum trades loaded")
        print(f"  Base win rate: {self.base_rate:.1%}")
        print(f"  Secondary dampening: {self.secondary_dampening}")
        print(f"  {'='*60}")

        # Price bins
        print(f"\n  Price Bin    WR       N     Kelly@0.25x")
        print(f"  {'-'*45}")
        for price_bin in sorted(self.price_wr.keys()):
            wr = self.price_wr[price_bin]
            n = self.price_n[price_bin]
            buy_ask = price_bin + 2  # rough midpoint
            net_win, net_loss = self._compute_net_payoffs(buy_ask)
            if net_win > 0:
                b = net_win / net_loss
                kelly = (wr * b - (1 - wr)) / b
            else:
                kelly = -999
            print(f"  {price_bin:3d}-{price_bin+4:3d}c  {wr:5.1%}   {n:4d}     {kelly:+.3f}")

        # Series
        print(f"\n  Series       WR       N    Shift")
        print(f"  {'-'*38}")
        for series in sorted(self.series_wr.keys()):
            wr = self.series_wr[series]
            n = self.series_n[series]
            shift = self.secondary_dampening * (wr - self.base_rate)
            short = series.replace("KX", "").replace("15M", "")
            print(f"  {short:8s}  {wr:5.1%}   {n:4d}   {shift:+.1%}")

        # Hours
        print(f"\n  Hour    WR       N    Shift")
        print(f"  {'-'*32}")
        for hour in sorted(self.hour_wr.keys()):
            wr = self.hour_wr[hour]
            n = self.hour_n[hour]
            shift = self.secondary_dampening * (wr - self.base_rate)
            flag = " **" if abs(shift) > 0.01 else ""
            print(f"  {hour:2d}:00  {wr:5.1%}   {n:4d}   {shift:+.1%}{flag}")

        print()

    # ------------------------------------------------------------------
    # Live Balance
    # ------------------------------------------------------------------

    def get_bankroll(self):
        """
        Get current bankroll in cents.
        Uses live Kalshi balance with caching, falls back to static config.
        """
        if not self.use_live_balance or self.client is None:
            return self.bankroll_fallback

        now = time.time()
        if (self._cached_balance is not None
                and now - self._balance_cache_time < self.balance_cache_seconds):
            return self._cached_balance

        try:
            balance_data = self.client.get_balance()
            # Kalshi returns balance in cents
            balance = balance_data.get("balance", self.bankroll_fallback)
            self._cached_balance = balance
            self._balance_cache_time = now
            return balance
        except Exception as e:
            print(f"  [Bayesian] Balance API error: {e}, using fallback")
            return self._cached_balance or self.bankroll_fallback

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, leader_bid, buy_ask, series, hour, depth=None):
        """
        Evaluate a potential momentum entry.

        Args:
            leader_bid: best bid on the leading side (the signal strength)
            buy_ask: actual cost to buy (the ask price we'd pay)
            series: e.g. "KXBTC15M"
            hour: current hour (0-23)
            depth: orderbook depth at best bid (logged but not yet used in model)

        Returns:
            SignalResult with posterior, Kelly, sizing, and comparison to static logic.
        """
        price_bin = (leader_bid // 5) * 5

        # Primary signal: price-bin specific win rate
        price_wr = self.price_wr.get(price_bin, self.base_rate)

        # Secondary signals: series and hour provide dampened additive shifts
        # This prevents naive Bayes independence assumption from dragging
        # the posterior away from the dominant price signal at extreme prices
        series_wr = self.series_wr.get(series, self.base_rate)
        hour_wr = self.hour_wr.get(hour, self.base_rate)

        series_shift = self.secondary_dampening * (series_wr - self.base_rate)
        hour_shift = self.secondary_dampening * (hour_wr - self.base_rate)

        posterior = price_wr + series_shift + hour_shift
        posterior = max(0.001, min(0.999, posterior))  # clamp

        # Confidence: weakest link across feature bins
        conf_price = self.price_n.get(price_bin, 0)
        conf_series = self.series_n.get(series, 0)
        conf_hour = self.hour_n.get(hour, 0)
        confidence = min(conf_price, conf_series, conf_hour)

        # Kelly with fees
        net_win, net_loss = self._compute_net_payoffs(buy_ask)

        if net_win <= 0:
            kelly_fraction = -999.0
            ev_per_contract = -net_loss
        else:
            b = net_win / net_loss
            kelly_fraction = (posterior * b - (1 - posterior)) / b
            ev_per_contract = posterior * net_win - (1 - posterior) * net_loss

        # Position sizing from Kelly
        bankroll = self.get_bankroll()
        recommended = 0

        if kelly_fraction > 0 and confidence >= self.min_confidence:
            fractional_kelly = kelly_fraction * self.kelly_multiplier
            bankroll_risk = fractional_kelly * bankroll
            recommended = int(bankroll_risk / net_loss) if net_loss > 0 else 0

            # Enforce 5% bankroll cap per trade
            max_cost = bankroll * self.max_bankroll_pct
            max_contracts_by_cap = int(max_cost / buy_ask) if buy_ask > 0 else 0
            recommended = min(recommended, max_contracts_by_cap)

            # Clamp to [min, max]
            recommended = max(self.min_contracts, min(self.max_contracts, recommended))

        # Build old_decision for comparison
        old_contracts = 0
        for bid_level in sorted(self.conviction_tiers.keys(), reverse=True):
            if leader_bid >= bid_level:
                old_contracts = self.conviction_tiers[bid_level]
                break
        old_would_enter = leader_bid >= self.static_min_bid  # simplified (ignores overnight)

        features = {
            "leader_bid": leader_bid,
            "buy_ask": buy_ask,
            "series": series,
            "hour": hour,
            "price_bin": price_bin,
            "depth": depth,
        }
        breakdown = {
            "price_wr": round(price_wr, 4),
            "series_wr": round(series_wr, 4),
            "hour_wr": round(hour_wr, 4),
            "series_shift": round(series_shift, 4),
            "hour_shift": round(hour_shift, 4),
            "conf_price": conf_price,
            "conf_series": conf_series,
            "conf_hour": conf_hour,
        }
        old_decision = {
            "would_enter": old_would_enter,
            "contracts": old_contracts,
        }

        return SignalResult(
            posterior=posterior,
            confidence=confidence,
            kelly_fraction=kelly_fraction,
            recommended_contracts=recommended,
            ev_per_contract_cents=ev_per_contract,
            bankroll_cents=bankroll,
            features=features,
            breakdown=breakdown,
            old_decision=old_decision,
        )

    def should_enter(self, signal):
        """Returns True if the Bayesian engine recommends entry."""
        return (signal.kelly_fraction > 0
                and signal.recommended_contracts > 0
                and signal.confidence >= self.min_confidence)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_net_payoffs(self, buy_ask):
        """
        Compute net win and loss amounts per contract, accounting for fees.

        Kalshi charges 0.7% per leg:
          - Entry fee: buy_ask * fee_rate (paid on buy)
          - Win settlement: no additional trade fee (settled automatically)
          - Loss: lose buy_ask, no exit fee (contract expires worthless)

        Net win = (100 - buy_ask) - entry_fee
        Net loss = buy_ask + entry_fee
        """
        entry_fee = math.ceil(buy_ask * self.fee_rate * 100) / 100  # round up
        net_win = (100 - buy_ask) - entry_fee
        net_loss = buy_ask + entry_fee
        return net_win, net_loss


# ------------------------------------------------------------------
# Standalone test / calibration check
# ------------------------------------------------------------------

if __name__ == "__main__":
    import pathlib
    data_dir = str(pathlib.Path(__file__).parent / "data")
    config = {
        "kelly_multiplier": 0.25,
        "bankroll_cents": 5000,
        "min_contracts": 1,
        "max_contracts": 15,
        "max_bankroll_pct": 0.05,
        "min_confidence": 10,
        "fee_rate": 0.007,
        "conviction_tiers": {75: 8, 80: 10},
        "min_bid": 75,
        "overnight_min_bid": 86,
        "use_live_balance": False,
        "balance_cache_seconds": 60,
    }

    engine = BayesianSignal(data_dir, config)

    # Test evaluations at key price points with realistic 1c spread
    print(f"\n  {'='*70}")
    print(f"  TEST EVALUATIONS — 1c spread (realistic), $50 bankroll")
    print(f"  {'='*70}")

    for label, series, hour in [("BTC h15", "KXBTC15M", 15),
                                 ("XRP h16", "KXXRP15M", 16),
                                 ("ETH h09", "KXETH15M", 9)]:
        short = label
        print(f"\n  {short}:")
        print(f"  {'Bid':>5} {'Ask':>5} {'P(win)':>8} {'Kelly':>8} {'EV/ct':>8} {'Cts':>5} {'Old':>5}")
        print(f"  {'-'*52}")
        for bid in [75, 80, 85, 88, 90, 92, 95, 97]:
            ask = bid + 1  # tight crypto spread
            sig = engine.evaluate(
                leader_bid=bid, buy_ask=ask,
                series=series, hour=hour, depth=10
            )
            old_ct = sig.old_decision["contracts"]
            print(f"  {bid:5d} {ask:5d} {sig.posterior:7.1%} {sig.kelly_fraction:+7.3f} "
                  f"{sig.ev_per_contract_cents:+7.1f}c {sig.recommended_contracts:5d} {old_ct:5d}")

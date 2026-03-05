"""
Maker Executor — 15-Min Crypto Momentum Observation Strategy.
Mirrors the taker's momentum signal (T=420s, leader_bid) but places
virtual maker limit orders at the bid. Tests whether taker's 93% WR
works with 4x lower maker fees, and measures fill rates.

Virtual order lifecycle:
  spotted → pending (resting order) → filled (trade at our price) → settled (market resolves)
                                    → expired (no fill before deadline/close)

Runs alongside the momentum bot with zero interference (read-only API calls).
"""

import os
import json
import time
import calendar
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from .config import (
    OBSERVATION_MODE,
    SCAN_INTERVAL_SECONDS,
    SETTLEMENT_CHECK_INTERVAL,
    PRINT_INTERVAL_SECONDS,
    MAX_POSITIONS,
    MAX_EXPOSURE_CENTS,
    CONTRACTS_PER_MARKET,
    MAKER_FEE_COEFFICIENT,
    FILL_CHECK_INTERVAL,
    FILL_TOLERANCE_CENTS,
    MAKER_DEADLINE_SECONDS,
    MAKER_ENTRY_SECONDS,
    MAKER_ENTRY_WINDOW,
    SKIP_HOURS,
    CRYPTO_SERIES,
    MIN_FAVORITE_PRICE,
    OVERNIGHT_MIN_BID,
    BAYESIAN_ENABLED, BAYESIAN_SHADOW_MODE,
    KELLY_MULTIPLIER, KELLY_USE_LIVE_BALANCE, KELLY_BANKROLL_CENTS,
    KELLY_BALANCE_CACHE_SECONDS, KELLY_MIN_CONTRACTS, KELLY_MAX_CONTRACTS,
    KELLY_MAX_BANKROLL_PCT, KELLY_MIN_CONFIDENCE, BAYESIAN_SECONDARY_DAMPENING,
    maker_fee_per_contract,
)
from .market_scanner import scan_crypto_markets, calculate_maker_fee, compute_elapsed

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

OBS_LOG = os.path.join(DATA_DIR, "maker_crypto_obs.jsonl")
OBS_HISTORY = os.path.join(DATA_DIR, "maker_crypto_history.jsonl")
SCAN_LOG = os.path.join(DATA_DIR, "maker_crypto_scan_log.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "maker_crypto_state.json")


class MakerExecutor:
    def __init__(self, client):
        self.client = client
        # Two-stage tracking: pending orders → filled positions
        self.pending_orders = {}   # ticker -> order dict (waiting for fill)
        self.filled_positions = {} # ticker -> position dict (filled, waiting for settlement)
        self.settled_count = 0
        self.total_hypothetical_pnl = 0
        self.fill_count = 0
        self.expire_count = 0
        self.scan_count = 0
        self.start_time = datetime.now()
        self._entered_windows = set()  # (series, close_time) tuples for dedup
        self._load_state()

        # Initialize Bayesian signal engine (calibrated on taker's historical data)
        self.bayesian = None
        if BAYESIAN_ENABLED or BAYESIAN_SHADOW_MODE:
            import sys
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sys.path.insert(0, root_dir)
            from trade_straddle.bayesian_signal import BayesianSignal

            # Use taker's historical data for calibration (1,371 trades, same 4 series)
            calibration_dir = os.path.join(root_dir, "trade_straddle", "data")

            self.bayesian = BayesianSignal(
                data_dir=calibration_dir,
                config={
                    "kelly_multiplier": KELLY_MULTIPLIER,
                    "bankroll_cents": KELLY_BANKROLL_CENTS,
                    "min_contracts": KELLY_MIN_CONTRACTS,
                    "max_contracts": KELLY_MAX_CONTRACTS,
                    "max_bankroll_pct": KELLY_MAX_BANKROLL_PCT,
                    "min_confidence": KELLY_MIN_CONFIDENCE,
                    "fee_function": maker_fee_per_contract,
                    "use_live_balance": KELLY_USE_LIVE_BALANCE,
                    "balance_cache_seconds": KELLY_BALANCE_CACHE_SECONDS,
                    "secondary_dampening": BAYESIAN_SECONDARY_DAMPENING,
                    # Maker has no conviction tiers — static is flat 5 contracts
                    "conviction_tiers": {},
                    "min_bid": MIN_FAVORITE_PRICE,
                    "overnight_min_bid": OVERNIGHT_MIN_BID,
                },
                kalshi_client=client,
            )

    # Set to True to reset counters on next startup (fresh data collection)
    _RESET_COUNTERS_ON_LOAD = False

    def _load_state(self):
        """Load state from file."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                self.pending_orders = state.get("pending_orders", {})
                self.filled_positions = state.get("filled_positions", {})

                if self._RESET_COUNTERS_ON_LOAD:
                    # Fresh start: zero counters, keep any active positions
                    self.settled_count = 0
                    self.total_hypothetical_pnl = 0
                    self.fill_count = len(self.filled_positions)  # count current fills
                    self.expire_count = 0
                    print("  *** Counters reset for fresh Bayesian data collection ***")
                else:
                    self.settled_count = state.get("settled_count", 0)
                    self.total_hypothetical_pnl = state.get("total_hypothetical_pnl", 0)
                    self.fill_count = state.get("fill_count", 0)
                    self.expire_count = state.get("expire_count", 0)

                self._entered_windows = set(
                    tuple(w) for w in state.get("entered_windows", [])
                )
                pending = len(self.pending_orders)
                filled = len(self.filled_positions)
                print(f"  Loaded state: {pending} pending, {filled} filled, "
                      f"{self.settled_count} settled, P&L: {self.total_hypothetical_pnl:+d}c")
            except Exception as e:
                print(f"  Warning: Failed to load state: {e}")

    def _save_state(self):
        """Persist state to file."""
        state = {
            "pending_orders": self.pending_orders,
            "filled_positions": self.filled_positions,
            "settled_count": self.settled_count,
            "total_hypothetical_pnl": self.total_hypothetical_pnl,
            "fill_count": self.fill_count,
            "expire_count": self.expire_count,
            "entered_windows": list(self._entered_windows),
            "last_saved": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def _log_jsonl(self, path, entry):
        """Append a JSON entry to a JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _cleanup_entered_windows(self):
        """Remove expired window entries (close_time has passed + 2min buffer)."""
        now_utc = calendar.timegm(datetime.utcnow().timetuple())
        to_remove = set()
        for series, close_time in self._entered_windows:
            try:
                ct = close_time
                if ct.endswith("Z"):
                    ct = ct[:-1] + "+00:00"
                close_dt = datetime.fromisoformat(ct)
                close_utc = calendar.timegm(close_dt.timetuple())
                if now_utc > close_utc + 120:  # 2 min buffer after close
                    to_remove.add((series, close_time))
            except Exception:
                to_remove.add((series, close_time))
        self._entered_windows -= to_remove

    def run_continuous(self):
        """Main observation loop."""
        print("\n" + "=" * 60)
        print("  MAKER OBSERVER — 15-Min Crypto MOMENTUM (mirrors taker)")
        print("  Mode: OBSERVATION ONLY (no orders placed)")
        print(f"  Series: {', '.join(CRYPTO_SERIES)}")
        print(f"  Entry window: T={MAKER_ENTRY_SECONDS}s ±{MAKER_ENTRY_WINDOW // 2}s")
        print(f"  Fill deadline: T={MAKER_DEADLINE_SECONDS}s")
        print(f"  Scan interval: {SCAN_INTERVAL_SECONDS}s")
        print(f"  Fill tolerance: ±{FILL_TOLERANCE_CENTS}c")
        print(f"  Skip hours (EST): {sorted(SKIP_HOURS)}")
        print(f"  Max virtual positions: {MAX_POSITIONS}")
        print(f"  Max exposure: ${MAX_EXPOSURE_CENTS / 100:.0f}")
        if self.bayesian:
            if BAYESIAN_ENABLED:
                print(f"  Bayesian signal engine: *** LIVE *** (Kelly={KELLY_MULTIPLIER}x, max={KELLY_MAX_CONTRACTS}ct)")
                print(f"  Calibration: taker data ({self.bayesian.total_calibration_trades} trades)")
            elif BAYESIAN_SHADOW_MODE:
                print(f"  Bayesian signal engine: SHADOW (logging only, static sizing trades)")
        print("=" * 60 + "\n")

        last_settlement_check = 0
        last_print = 0

        while True:
            try:
                now = time.time()

                # Cleanup old window entries
                self._cleanup_entered_windows()

                # 1. Scan markets, create new pending orders
                self._scan_and_log()

                # 2. Check for fills on pending orders (every cycle)
                self._check_fills()

                # 3. Check settlements on filled positions
                if now - last_settlement_check >= SETTLEMENT_CHECK_INTERVAL:
                    self._check_settlements()
                    last_settlement_check = now

                # 4. Print summary periodically
                if now - last_print >= PRINT_INTERVAL_SECONDS:
                    self._print_summary()
                    last_print = now

                self._save_state()
                time.sleep(SCAN_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print("\n  Maker observer stopped.")
                self._save_state()
                break
            except Exception as e:
                print(f"  Error in main loop: {e}")
                time.sleep(10)

    def _scan_and_log(self):
        """Scan crypto markets and create pending virtual orders."""
        self.scan_count += 1
        opportunities, scan_meta = scan_crypto_markets(self.client)

        # Log scan stats
        self._log_jsonl(SCAN_LOG, {
            "ts": datetime.now().isoformat(),
            "scan_number": self.scan_count,
            **scan_meta,
            "opportunities_found": len(opportunities),
            "pending_orders": len(self.pending_orders),
            "filled_positions": len(self.filled_positions),
        })

        if self.scan_count <= 5 or self.scan_count % 20 == 0:
            print(f"  Scan #{self.scan_count}: "
                  f"{scan_meta['series_in_window']}/{scan_meta['series_scanned']} in window → "
                  f"{len(opportunities)} opps | "
                  f"pending:{len(self.pending_orders)} filled:{len(self.filled_positions)}")

        # Current exposure (pending + filled)
        current_exposure = sum(
            p.get("buy_price", p.get("favorite_price", 0)) * p["contracts"]
            for p in list(self.pending_orders.values()) + list(self.filled_positions.values())
        )
        total_tracked = len(self.pending_orders) + len(self.filled_positions)

        new_count = 0
        for opp in opportunities:
            ticker = opp["ticker"]
            series = opp["series"]
            close_time = opp["close_time"]

            # Skip if already tracking this ticker
            if ticker in self.pending_orders or ticker in self.filled_positions:
                continue

            # Skip if already entered this window for this series
            window_key = (series, close_time)
            if window_key in self._entered_windows:
                continue

            if total_tracked >= MAX_POSITIONS:
                break

            # ── Bayesian Signal Evaluation ──
            bayesian_signal = None
            current_hour = datetime.now().hour
            if self.bayesian is not None:
                bayesian_signal = self.bayesian.evaluate(
                    leader_bid=opp["leader_bid"],
                    buy_ask=opp["buy_price"],  # maker pays bid price (limit order)
                    series=series,
                    hour=current_hour,
                    depth=opp["depth"],
                )

            # ── Entry Decision: Bayesian LIVE vs Static ──
            if BAYESIAN_ENABLED and bayesian_signal is not None:
                # LIVE Bayesian mode: Kelly controls entry and sizing
                if not self.bayesian.should_enter(bayesian_signal):
                    self._log_bayesian_decision(ticker, series, bayesian_signal,
                                                entered=False, mode="live",
                                                reason="kelly_negative")
                    continue  # Bayesian says skip
                contracts = bayesian_signal.recommended_contracts
                self._log_bayesian_decision(ticker, series, bayesian_signal,
                                            entered=True, mode="live")
            else:
                # Static sizing (original logic)
                contracts = CONTRACTS_PER_MARKET
                if bayesian_signal is not None and BAYESIAN_SHADOW_MODE:
                    self._log_bayesian_decision(ticker, series, bayesian_signal,
                                                entered=True, mode="shadow",
                                                static_contracts=contracts)

            position_cost = opp["buy_price"] * contracts
            if current_exposure + position_cost > MAX_EXPOSURE_CENTS:
                continue

            # Create PENDING virtual order (momentum fields)
            order = {
                "ticker": ticker,
                "title": opp["title"],
                "series": series,
                "buy_side": opp["buy_side"],
                "buy_price": opp["buy_price"],         # limit order at bid
                "buy_ask": opp.get("buy_ask", 0),      # what taker would pay (for comparison)
                "leader_bid": opp["leader_bid"],        # signal strength
                "contracts": contracts,
                "depth": opp["depth"],
                "order_time": datetime.now(timezone.utc).isoformat(),  # UTC for correct fill time comparison
                "close_time": close_time,
                "elapsed_at_entry": opp["elapsed_s"],
                "status": "pending",
                "last_trade_check": None,
            }

            self.pending_orders[ticker] = order
            self._entered_windows.add(window_key)
            current_exposure += position_cost
            total_tracked += 1
            new_count += 1

            if bayesian_signal:
                mode_tag = "BAYES" if BAYESIAN_ENABLED else "STATIC"
                print(f"  [{mode_tag}] {ticker}: {opp['buy_side'].upper()} @{opp['buy_price']}c "
                      f"→ {contracts}ct | P(win)={bayesian_signal.posterior:.1%} "
                      f"Kelly={bayesian_signal.kelly_fraction:+.3f} "
                      f"EV={bayesian_signal.ev_per_contract_cents:+.1f}c")

            self._log_jsonl(OBS_LOG, {
                "type": "order_placed",
                "ts": datetime.now().isoformat(),
                **order,
            })

        if new_count > 0:
            print(f"  +{new_count} new pending orders "
                  f"(pending:{len(self.pending_orders)} filled:{len(self.filled_positions)} "
                  f"exposure:${current_exposure / 100:.2f})")

    # Hours that were previously hard-blocked, now Bayesian-managed
    _FORMERLY_SKIPPED_HOURS = {3, 11, 13, 14, 20, 23}

    def _log_bayesian_decision(self, ticker, series, signal, entered, mode,
                                static_contracts=None, reason=None):
        """Log Bayesian signal evaluation to maker_bayesian_decisions.jsonl."""
        hour = signal.features.get("hour", datetime.now().hour)
        entry = {
            "ts": datetime.now().isoformat(),
            "ticker": ticker,
            "series": series,
            "mode": mode,
            "entered": entered,
            "posterior": round(signal.posterior, 4),
            "confidence": signal.confidence,
            "kelly_fraction": round(signal.kelly_fraction, 4),
            "recommended_contracts": signal.recommended_contracts,
            "ev_per_contract": round(signal.ev_per_contract_cents, 2),
            "bankroll_cents": signal.bankroll_cents,
            "features": signal.features,
            "breakdown": signal.breakdown,
            "old_decision": signal.old_decision,
            "formerly_skipped_hour": hour in self._FORMERLY_SKIPPED_HOURS,
        }
        if static_contracts is not None:
            entry["static_contracts"] = static_contracts
        if reason:
            entry["reason"] = reason

        log_path = os.path.join(DATA_DIR, "maker_bayesian_decisions.jsonl")
        self._log_jsonl(log_path, entry)

    def _check_fills(self):
        """
        Check if any pending orders would have been filled.

        For each pending order, fetch recent trades and check if any trade
        occurred at our hypothetical maker price (±tolerance). This simulates
        whether a resting limit order would have been matched.

        Fill logic:
        - buy_side="no" at price Xc: we BUY NO at Xc (≡ SELL YES at (100-X)c)
          → fill when taker_side=yes AND yes_price ≈ (100-X) ±tolerance
          → AND trade volume >= our order size
        - buy_side="yes" at price Xc: we BUY YES at Xc
          → fill when taker_side=no AND yes_price ≈ X ±tolerance
          → AND trade volume >= our order size

        Time comparison: order_time is stored in UTC (fixed from local time bug).
        Kalshi trade created_time is also UTC. Both are ISO 8601 strings.
        """
        if not self.pending_orders:
            return

        filled = []
        expired = []
        now = datetime.now()

        for ticker, order in list(self.pending_orders.items()):
            # Check window deadline (T >= MAKER_DEADLINE_SECONDS)
            close_time = order.get("close_time", "")
            elapsed_s = compute_elapsed(close_time)
            if elapsed_s is not None and elapsed_s >= MAKER_DEADLINE_SECONDS:
                expired.append(ticker)
                continue

            # Also check if market has fully closed (UTC fallback)
            if close_time:
                try:
                    ct = close_time
                    if ct.endswith("Z"):
                        ct = ct[:-1] + "+00:00"
                    close_dt = datetime.fromisoformat(ct)
                    close_utc = calendar.timegm(close_dt.timetuple())
                    now_utc = calendar.timegm(datetime.utcnow().timetuple())
                    if now_utc > close_utc:
                        expired.append(ticker)
                        continue
                except Exception:
                    pass

            # Fetch recent trades
            try:
                trades_data = self.client.get_trades(ticker=ticker, limit=50)
                trades = trades_data.get("trades", [])
            except Exception:
                continue

            if not trades:
                continue

            # Check each trade for a fill match
            buy_side = order.get("buy_side", order.get("favorite_side", ""))
            buy_price = order.get("buy_price", order.get("favorite_price", 0))
            contracts = order["contracts"]
            order_time_str = order["order_time"]  # UTC ISO string

            for trade in trades:
                # Only count trades AFTER our order was placed
                # Both order_time and trade created_time are now UTC ISO strings
                trade_time = trade.get("created_time", "")
                if trade_time and trade_time < order_time_str:
                    continue

                yes_price = trade.get("yes_price", 0)
                taker_side = trade.get("taker_side", "")
                trade_count = trade.get("count", 0)

                # Volume check: trade must have enough contracts to fill our order
                if trade_count < contracts:
                    continue

                if buy_side == "no":
                    # We're buying NO at buy_price (≡ selling YES at 100-buy_price)
                    # Fill when a taker BUYS YES at our ask price (±tolerance)
                    our_yes_ask = 100 - buy_price
                    if taker_side == "yes" and abs(yes_price - our_yes_ask) <= FILL_TOLERANCE_CENTS:
                        filled.append((ticker, trade_time, yes_price, trade_count, taker_side))
                        break

                elif buy_side == "yes":
                    # We're buying YES at buy_price
                    # Fill when a taker SELLS YES into our bid (taker_side=no)
                    if taker_side == "no" and abs(yes_price - buy_price) <= FILL_TOLERANCE_CENTS:
                        filled.append((ticker, trade_time, yes_price, trade_count, taker_side))
                        break

            time.sleep(0.1)  # Rate limit trade lookups

        # Process fills
        for ticker, fill_time, fill_yes_price, fill_count, fill_taker_side in filled:
            order = self.pending_orders.pop(ticker)
            order["status"] = "filled"
            order["fill_time"] = fill_time
            order["fill_yes_price"] = fill_yes_price
            order["fill_volume"] = fill_count
            order["fill_taker_side"] = fill_taker_side

            # Compute time-to-fill (both times are UTC now)
            try:
                order_placed = datetime.fromisoformat(order["order_time"].replace("Z", "+00:00"))
                ft = fill_time.replace("Z", "+00:00") if fill_time else ""
                fill_dt = datetime.fromisoformat(ft) if ft else datetime.now(timezone.utc)
                order["time_to_fill_s"] = round((fill_dt - order_placed).total_seconds())
            except Exception:
                order["time_to_fill_s"] = 0

            self.filled_positions[ticker] = order
            self.fill_count += 1

            buy_side = order.get("buy_side", order.get("favorite_side", ""))
            buy_price = order.get("buy_price", order.get("favorite_price", 0))
            self._log_jsonl(OBS_LOG, {
                "type": "order_filled",
                "ts": datetime.now().isoformat(),
                "ticker": ticker,
                "series": order.get("series", ""),
                "fill_time": fill_time,
                "fill_yes_price": fill_yes_price,
                "fill_volume": fill_count,
                "fill_taker_side": fill_taker_side,
                "time_to_fill_s": order["time_to_fill_s"],
                "buy_side": buy_side,
                "buy_price": buy_price,
            })

        # Process expirations
        for ticker in expired:
            order = self.pending_orders.pop(ticker)
            order["status"] = "expired"
            order["expired_time"] = now.isoformat()
            self.expire_count += 1

            buy_side = order.get("buy_side", order.get("favorite_side", ""))
            buy_price = order.get("buy_price", order.get("favorite_price", 0))
            self._log_jsonl(OBS_LOG, {
                "type": "order_expired",
                "ts": now.isoformat(),
                "ticker": ticker,
                "series": order.get("series", ""),
                "buy_side": buy_side,
                "buy_price": buy_price,
                "elapsed_at_expiry": compute_elapsed(order.get("close_time", "")),
            })

        if filled or expired:
            total_orders = self.fill_count + self.expire_count
            fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0
            print(f"  Orders: +{len(filled)} filled, +{len(expired)} expired | "
                  f"Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%) | "
                  f"Pending:{len(self.pending_orders)} Filled:{len(self.filled_positions)}")

    def _check_settlements(self):
        """Check if any filled positions have settled."""
        if not self.filled_positions:
            return

        settled = []

        for ticker, pos in list(self.filled_positions.items()):
            try:
                market_data = self.client.get_market(ticker)
                market = market_data.get("market", market_data)
                result = market.get("result", "")

                if result not in ("yes", "no"):
                    continue

                # Compute hypothetical P&L (supports both old and new field names)
                buy_side = pos.get("buy_side", pos.get("favorite_side", ""))
                buy_price = pos.get("buy_price", pos.get("favorite_price", 0))
                contracts = pos["contracts"]
                fee = calculate_maker_fee(contracts, buy_price)

                if buy_side == result:
                    pnl = (100 - buy_price) * contracts - fee
                    won = True
                else:
                    pnl = -(buy_price * contracts) - fee
                    won = False

                # Archive
                history_entry = {
                    **pos,
                    "settlement_result": result,
                    "won": won,
                    "pnl_cents": pnl,
                    "fee_cents": fee,
                    "settled_time": datetime.now().isoformat(),
                }
                self._log_jsonl(OBS_HISTORY, history_entry)

                self.settled_count += 1
                self.total_hypothetical_pnl += pnl
                settled.append((ticker, result, pnl, won))

                del self.filled_positions[ticker]

            except Exception:
                continue

        if settled:
            wins = sum(1 for _, _, _, w in settled if w)
            losses = len(settled) - wins
            pnl_batch = sum(p for _, _, p, _ in settled)
            print(f"  Settled {len(settled)} positions: "
                  f"{wins}W/{losses}L, batch P&L: {pnl_batch:+d}c | "
                  f"Total: {self.total_hypothetical_pnl:+d}c "
                  f"(${self.total_hypothetical_pnl / 100:+.2f})")

    def _print_summary(self):
        """Print periodic summary with fill rate metrics."""
        elapsed = (datetime.now() - self.start_time).total_seconds() / 3600
        if elapsed < 0.01:
            elapsed = 0.01

        # Series breakdown across pending + filled
        by_series = defaultdict(lambda: {"pending": 0, "filled": 0})
        for pos in self.pending_orders.values():
            by_series[pos.get("series", "?")]["pending"] += 1
        for pos in self.filled_positions.values():
            by_series[pos.get("series", "?")]["filled"] += 1

        # Fill rate stats
        total_orders = self.fill_count + self.expire_count
        fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0

        # Time-to-fill from history
        fill_times = []
        if os.path.exists(OBS_LOG):
            with open(OBS_LOG) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "order_filled" and entry.get("time_to_fill_s") is not None:
                            fill_times.append(entry["time_to_fill_s"])
                    except Exception:
                        pass

        # Settlement stats from history
        history_wins = 0
        history_losses = 0
        if os.path.exists(OBS_HISTORY):
            with open(OBS_HISTORY) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("won"):
                            history_wins += 1
                        else:
                            history_losses += 1
                    except Exception:
                        pass

        total_settled = history_wins + history_losses

        print(f"\n{'=' * 55}")
        print(f"  15-MIN CRYPTO MAKER MOMENTUM OBSERVER")
        print(f"  Runtime: {elapsed:.1f}hrs | Scans: {self.scan_count}")
        print(f"  ---")
        print(f"  Orders: {len(self.pending_orders)} pending, "
              f"{len(self.filled_positions)} filled, "
              f"{self.settled_count} settled")
        if by_series:
            series_str = ", ".join(
                f"{k}:{v['pending']}p/{v['filled']}f"
                for k, v in sorted(by_series.items())
            )
            print(f"  Series: {series_str}")
        print(f"  ---")
        print(f"  Fill rate: {self.fill_count}/{total_orders} "
              f"({fill_rate:.0f}%)" if total_orders > 0 else
              f"  Fill rate: waiting for data")
        print(f"  Expired: {self.expire_count}")
        if fill_times:
            avg_ttf = sum(fill_times) / len(fill_times)
            median_ttf = sorted(fill_times)[len(fill_times) // 2]
            print(f"  Avg time-to-fill: {avg_ttf:.0f}s | Median: {median_ttf:.0f}s")
        print(f"  ---")
        if total_settled > 0:
            win_rate = history_wins / total_settled * 100
            print(f"  Settled: {total_settled} "
                  f"({history_wins}W/{history_losses}L, {win_rate:.1f}% win rate)")
        else:
            print(f"  Settled: 0 (waiting for results)")
        print(f"  Hypothetical P&L: {self.total_hypothetical_pnl:+d}c "
              f"(${self.total_hypothetical_pnl / 100:+.2f})")
        if total_settled > 0:
            print(f"  Per-trade avg: {self.total_hypothetical_pnl / total_settled:+.1f}c")
        if elapsed >= 1:
            print(f"  Hourly rate: ${self.total_hypothetical_pnl / 100 / elapsed:+.2f}/hr")
            windows_per_hour = (self.fill_count + self.expire_count) / elapsed
            print(f"  Windows/hr: {windows_per_hour:.1f}")
        print(f"{'=' * 55}\n")

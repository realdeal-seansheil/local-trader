"""
Underdog Executor — Core engine for underdog trading strategies.
Manages two-stage order lifecycle: pending → filled → settled.

Strategy 2: Early Window (T=300-390s, leader 55-74c, maker order at bid)
Strategy 4: Fade the Extreme (T=600-840s, favorite >= 90c, buy underdog)
Strategy 6: Signal observation (delegated to SignalLogger)

Maker fill detection:
  - LIVE mode: check real order status via Kalshi API
  - OBS mode: simulate fills from trades API (same as trade_maker)
"""

import os
import json
import time
import calendar
from datetime import datetime, timezone
from collections import defaultdict

from .config import (
    OBSERVATION_MODE,
    LOOP_INTERVAL_SECONDS,
    SCAN_INTERVAL_SECONDS,
    PRINT_INTERVAL_SECONDS,
    SETTLEMENT_CHECK_INTERVAL,
    SETTLEMENT_BUFFER_S,
    TICK_LOGGING_ENABLED,
    SIGNAL_OBS_ENABLED,
    EARLY_ENABLED,
    EARLY_ENTRY_START_S,
    EARLY_ENTRY_END_S,
    EARLY_MIN_LEADER_BID,
    EARLY_MAX_LEADER_BID,
    EARLY_MIN_CONTRACTS,
    EARLY_MAX_CONTRACTS,
    EARLY_MIN_DEPTH,
    EARLY_FILL_DEADLINE_S,
    EARLY_OVERNIGHT_MIN_BID,
    FADE_ENABLED,
    FADE_ENTRY_START_S,
    FADE_ENTRY_END_S,
    FADE_EXTREME_THRESHOLD,
    FADE_MAX_UNDERDOG_PRICE,
    FADE_MIN_CONTRACTS,
    FADE_MAX_CONTRACTS,
    FADE_MIN_DEPTH,
    FADE_FILL_DEADLINE_S,
    FADE_OVERNIGHT_ENABLED,
    FILL_TOLERANCE_CENTS,
    SKIP_HOURS,
    CRYPTO_SERIES,
    calculate_maker_fee,
)
from .market_scanner import fetch_all_snapshots, compute_elapsed, is_skip_hour, is_overnight
from .tick_logger import TickLogger
from .signal_logger import SignalLogger
from .enrichment_manager import EnrichmentManager

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

OBS_LOG = os.path.join(DATA_DIR, "underdog_obs.jsonl")
HISTORY_LOG = os.path.join(DATA_DIR, "underdog_history.jsonl")
SCAN_LOG = os.path.join(DATA_DIR, "underdog_scan_log.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "underdog_state.json")


class UnderdogExecutor:
    def __init__(self, client):
        self.client = client

        # Two-stage tracking (same pattern as maker executor)
        self.pending_orders = {}    # ticker -> order dict
        self.filled_positions = {}  # ticker -> position dict
        self._entered_windows = set()  # (series, close_time) dedup

        # Counters
        self.fill_count = 0
        self.expire_count = 0
        self.settled_count = 0
        self.total_pnl = 0
        self.scan_count = 0
        self.start_time = datetime.now()

        # Strategy-specific counters
        self.early_count = 0
        self.fade_count = 0

        # Sub-components
        self.tick_logger = TickLogger()
        self.signal_logger = SignalLogger()
        self.enrichment = EnrichmentManager(client)

        self._load_state()

    # ── State Persistence ──

    def _load_state(self):
        """Load state from file."""
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            self.pending_orders = state.get("pending_orders", {})
            self.filled_positions = state.get("filled_positions", {})
            self.fill_count = state.get("fill_count", 0)
            self.expire_count = state.get("expire_count", 0)
            self.settled_count = state.get("settled_count", 0)
            self.total_pnl = state.get("total_pnl", 0)
            self.early_count = state.get("early_count", 0)
            self.fade_count = state.get("fade_count", 0)
            self._entered_windows = set(
                tuple(w) for w in state.get("entered_windows", [])
            )
            pending = len(self.pending_orders)
            filled = len(self.filled_positions)
            print(f"  Loaded state: {pending} pending, {filled} filled, "
                  f"{self.settled_count} settled, P&L: {self.total_pnl:+d}c")
        except Exception as e:
            print(f"  Warning: Failed to load state: {e}")

    def _save_state(self):
        """Persist state to file."""
        state = {
            "pending_orders": self.pending_orders,
            "filled_positions": self.filled_positions,
            "fill_count": self.fill_count,
            "expire_count": self.expire_count,
            "settled_count": self.settled_count,
            "total_pnl": self.total_pnl,
            "early_count": self.early_count,
            "fade_count": self.fade_count,
            "entered_windows": list(self._entered_windows),
            "last_saved": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def _log_jsonl(self, path, entry):
        """Append a JSON entry to a JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    # ── Window Cleanup ──

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
                if now_utc > close_utc + SETTLEMENT_BUFFER_S:
                    to_remove.add((series, close_time))
            except Exception:
                to_remove.add((series, close_time))
        self._entered_windows -= to_remove

    # ── Exposure Calculation ──

    def _current_exposure(self):
        """Total exposure across pending + filled positions."""
        exposure = 0
        for pos in list(self.pending_orders.values()) + list(self.filled_positions.values()):
            exposure += pos.get("buy_price", 0) * pos.get("contracts", 0)
        return exposure

    # ── Strategy 2: Early Window ──

    def _scan_early_window(self, snapshots):
        """
        Strategy 2: Buy the leading side early (T=300-390s) when prices
        are cheaper (55-74c) using a maker limit order at the bid.
        """
        if not EARLY_ENABLED:
            return

        overnight = is_overnight()
        effective_min_bid = EARLY_OVERNIGHT_MIN_BID if overnight else EARLY_MIN_LEADER_BID

        for snap in snapshots:
            elapsed_s = snap["elapsed_s"]
            if not (EARLY_ENTRY_START_S <= elapsed_s <= EARLY_ENTRY_END_S):
                continue

            ticker = snap["ticker"]
            series = snap["series"]
            close_time = snap["close_time"]
            ob = snap["ob"]

            # Dedup
            if ticker in self.pending_orders or ticker in self.filled_positions:
                continue
            window_key = (series, close_time)
            if window_key in self._entered_windows:
                continue

            # Identify leader
            leader_bid = max(ob["yes_bid"], ob["no_bid"])
            if leader_bid < effective_min_bid or leader_bid > EARLY_MAX_LEADER_BID:
                continue

            # Determine buy side
            if ob["yes_bid"] >= ob["no_bid"]:
                buy_side = "yes"
                buy_price = ob["yes_bid"]  # Maker limit at bid
                depth = ob["yes_depth"]
            else:
                buy_side = "no"
                buy_price = ob["no_bid"]
                depth = ob["no_depth"]

            if depth < EARLY_MIN_DEPTH:
                continue

            # ── Enrichment filters (graceful: skip filter if data missing) ──
            vol = snap.get("vol_regime", {})
            if vol.get("regime_action") == "skip_early":
                continue  # Low vol — not enough movement for early entries

            momentum = snap.get("momentum", {})
            if momentum.get("bid_velocity", 0) < -1:
                continue  # Leader bid dropping fast — skip

            spot = snap.get("spot", {})
            if spot.get("leader_divergent"):
                continue  # Kalshi leader disagrees with spot movement — skip

            # Position sizing (fixed for now, future: Kelly)
            contracts = EARLY_MAX_CONTRACTS

            # Create pending order
            order = {
                "ticker": ticker,
                "title": snap.get("title", ""),
                "series": series,
                "strategy": "early_window",
                "buy_side": buy_side,
                "buy_price": buy_price,
                "leader_bid": leader_bid,
                "contracts": contracts,
                "depth": depth,
                "order_time": datetime.now(timezone.utc).isoformat(),
                "close_time": close_time,
                "elapsed_at_entry": elapsed_s,
                "status": "pending",
            }

            # Place real order if live
            if not OBSERVATION_MODE:
                try:
                    result = self.client.place_order(
                        ticker=ticker,
                        side=buy_side,
                        action="buy",
                        count=contracts,
                        price=buy_price,
                    )
                    if "error" in result:
                        print(f"  EARLY ORDER ERROR: {ticker} {result}")
                        continue
                    order["order_id"] = result.get("order", {}).get("order_id", "")
                    order["live"] = True
                except Exception as e:
                    print(f"  EARLY ORDER FAILED: {ticker} {e}")
                    continue

            self.pending_orders[ticker] = order
            self._entered_windows.add(window_key)
            self.early_count += 1

            mode_tag = "LIVE" if not OBSERVATION_MODE else "OBS"
            print(f"  [{mode_tag}] EARLY: {ticker} {buy_side.upper()} "
                  f"@{buy_price}c x{contracts} | leader={leader_bid}c "
                  f"T={elapsed_s:.0f}s depth={depth}")

            self._log_jsonl(OBS_LOG, {
                "type": "early_order", "ts": datetime.now().isoformat(), **order,
                "enrichment": {
                    "spot": snap.get("spot", {}),
                    "tape": snap.get("tape", {}),
                    "momentum": snap.get("momentum", {}),
                    "cross_series": snap.get("cross_series", {}),
                    "vol_regime": snap.get("vol_regime", {}),
                },
            })

    # ── Strategy 4: Fade the Extreme ──

    def _scan_fade_extreme(self, snapshots):
        """
        Strategy 4: When the favorite hits 90c+, buy the cheap underdog
        side using a maker limit order. Massive risk/reward asymmetry.
        """
        if not FADE_ENABLED:
            return

        for snap in snapshots:
            elapsed_s = snap["elapsed_s"]
            if not (FADE_ENTRY_START_S <= elapsed_s <= FADE_ENTRY_END_S):
                continue

            ticker = snap["ticker"]
            series = snap["series"]
            close_time = snap["close_time"]
            ob = snap["ob"]

            # Dedup
            if ticker in self.pending_orders or ticker in self.filled_positions:
                continue
            window_key = (series, close_time)
            if window_key in self._entered_windows:
                continue

            # Find the favorite side (highest bid)
            if ob["yes_bid"] >= ob["no_bid"]:
                favorite_bid = ob["yes_bid"]
                underdog_side = "no"
                underdog_bid = ob["no_bid"]
                underdog_depth = ob["no_depth"]
            else:
                favorite_bid = ob["no_bid"]
                underdog_side = "yes"
                underdog_bid = ob["yes_bid"]
                underdog_depth = ob["yes_depth"]

            # Check extreme threshold
            if favorite_bid < FADE_EXTREME_THRESHOLD:
                continue

            # Check underdog is cheap enough
            if underdog_bid > FADE_MAX_UNDERDOG_PRICE or underdog_bid <= 0:
                continue

            if underdog_depth < FADE_MIN_DEPTH:
                continue

            # ── Enrichment filters (graceful: skip filter if data missing) ──
            vol = snap.get("vol_regime", {})
            if vol.get("regime_action") == "skip_fade":
                continue  # High vol — momentum too strong, fades get crushed

            tape = snap.get("tape", {})
            if tape.get("acceleration", 0) > 5:
                continue  # Volume accelerating toward favorite — don't fade

            momentum = snap.get("momentum", {})
            if momentum.get("bid_velocity", 0) > 2:
                continue  # Favorite bid still climbing fast — too early to fade

            # Position sizing
            contracts = FADE_MAX_CONTRACTS

            # Create pending order (buy underdog at its bid)
            order = {
                "ticker": ticker,
                "title": snap.get("title", ""),
                "series": series,
                "strategy": "fade_extreme",
                "buy_side": underdog_side,
                "buy_price": underdog_bid,
                "favorite_bid": favorite_bid,
                "contracts": contracts,
                "depth": underdog_depth,
                "order_time": datetime.now(timezone.utc).isoformat(),
                "close_time": close_time,
                "elapsed_at_entry": elapsed_s,
                "status": "pending",
            }

            # Place real order if live
            if not OBSERVATION_MODE:
                try:
                    result = self.client.place_order(
                        ticker=ticker,
                        side=underdog_side,
                        action="buy",
                        count=contracts,
                        price=underdog_bid,
                    )
                    if "error" in result:
                        print(f"  FADE ORDER ERROR: {ticker} {result}")
                        continue
                    order["order_id"] = result.get("order", {}).get("order_id", "")
                    order["live"] = True
                except Exception as e:
                    print(f"  FADE ORDER FAILED: {ticker} {e}")
                    continue

            self.pending_orders[ticker] = order
            self._entered_windows.add(window_key)
            self.fade_count += 1

            mode_tag = "LIVE" if not OBSERVATION_MODE else "OBS"
            print(f"  [{mode_tag}] FADE: {ticker} {underdog_side.upper()} "
                  f"@{underdog_bid}c x{contracts} | fav={favorite_bid}c "
                  f"T={elapsed_s:.0f}s depth={underdog_depth}")

            self._log_jsonl(OBS_LOG, {
                "type": "fade_order", "ts": datetime.now().isoformat(), **order,
                "enrichment": {
                    "spot": snap.get("spot", {}),
                    "tape": snap.get("tape", {}),
                    "momentum": snap.get("momentum", {}),
                    "cross_series": snap.get("cross_series", {}),
                    "vol_regime": snap.get("vol_regime", {}),
                },
            })

    # ── Fill Detection ──

    def _check_fills(self):
        """
        Check if pending orders have been filled.
        LIVE: check real order status via API.
        OBS: simulate fills from trades API (same pattern as trade_maker).
        """
        if not self.pending_orders:
            return

        filled = []
        expired = []

        for ticker, order in list(self.pending_orders.items()):
            # Check strategy-specific fill deadline
            close_time = order.get("close_time", "")
            elapsed_s = compute_elapsed(close_time)
            strategy = order.get("strategy", "early_window")
            deadline = EARLY_FILL_DEADLINE_S if strategy == "early_window" else FADE_FILL_DEADLINE_S

            if elapsed_s is not None and elapsed_s >= deadline:
                expired.append(ticker)
                continue

            # Check if market has closed
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

            # ── LIVE: Check real order status ──
            if order.get("live") and order.get("order_id"):
                try:
                    order_data = self.client.get_order(order["order_id"])
                    status = order_data.get("order", {}).get("status", "")
                    if status in ("executed", "filled"):
                        fill_time = datetime.now(timezone.utc).isoformat()
                        filled.append((ticker, fill_time, order["buy_price"],
                                       order["contracts"], "live_fill"))
                except Exception:
                    pass
                time.sleep(0.1)
                continue

            # ── OBS: Simulate fills from trades API (try enrichment cache first) ──
            cached = self.enrichment.get_trade_cache(ticker)
            if cached is not None:
                trades = cached
            else:
                try:
                    trades_data = self.client.get_trades(ticker=ticker, limit=50)
                    trades = trades_data.get("trades", [])
                except Exception:
                    continue

            if not trades:
                continue

            buy_side = order["buy_side"]
            buy_price = order["buy_price"]
            contracts = order["contracts"]
            order_time_str = order["order_time"]

            # Accumulate partial fills across multiple trades
            accumulated = 0
            last_fill_time = ""
            last_fill_price = 0
            last_taker_side = ""

            for trade in trades:
                trade_time = trade.get("created_time", "")
                if trade_time and trade_time < order_time_str:
                    continue

                # API returns dollars as strings: "yes_price_dollars", "count_fp"
                yes_price_raw = trade.get("yes_price_dollars") or trade.get("yes_price", 0)
                yes_price = round(float(yes_price_raw) * 100)  # convert $0.55 → 55c
                taker_side = trade.get("taker_side", "")
                count_raw = trade.get("count_fp") or trade.get("count", 0)
                trade_count = int(float(count_raw))

                # Maker buy YES: filled when taker sells YES (taker_side="no")
                # at our bid price
                if buy_side == "yes":
                    if abs(yes_price - buy_price) <= FILL_TOLERANCE_CENTS:
                        accumulated += trade_count
                        last_fill_time = trade_time
                        last_fill_price = yes_price
                        last_taker_side = taker_side
                # Maker buy NO: filled when taker buys YES at (100 - our_bid)
                elif buy_side == "no":
                    our_yes_ask = 100 - buy_price
                    if abs(yes_price - our_yes_ask) <= FILL_TOLERANCE_CENTS:
                        accumulated += trade_count
                        last_fill_time = trade_time
                        last_fill_price = yes_price
                        last_taker_side = taker_side

                if accumulated >= contracts:
                    filled.append((ticker, last_fill_time, last_fill_price,
                                   accumulated, last_taker_side))
                    break

            time.sleep(0.1)

        # Process fills
        for ticker, fill_time, fill_yes_price, fill_count, fill_taker_side in filled:
            order = self.pending_orders.pop(ticker)
            order["status"] = "filled"
            order["fill_time"] = fill_time
            order["fill_yes_price"] = fill_yes_price
            order["fill_volume"] = fill_count
            order["fill_taker_side"] = fill_taker_side

            # Compute time-to-fill
            try:
                order_placed = datetime.fromisoformat(order["order_time"].replace("Z", "+00:00"))
                ft = fill_time.replace("Z", "+00:00") if fill_time else ""
                fill_dt = datetime.fromisoformat(ft) if ft else datetime.now(timezone.utc)
                order["time_to_fill_s"] = round((fill_dt - order_placed).total_seconds())
            except Exception:
                order["time_to_fill_s"] = 0

            self.filled_positions[ticker] = order
            self.fill_count += 1

            print(f"  FILLED: {ticker} {order['strategy']} {order['buy_side'].upper()} "
                  f"@{order['buy_price']}c x{order['contracts']} "
                  f"(fill in {order['time_to_fill_s']}s)")

            self._log_jsonl(OBS_LOG, {
                "type": "order_filled",
                "ts": datetime.now().isoformat(),
                "ticker": ticker,
                "strategy": order["strategy"],
                "fill_time": fill_time,
                "time_to_fill_s": order["time_to_fill_s"],
                "buy_side": order["buy_side"],
                "buy_price": order["buy_price"],
            })

        # Process expirations
        for ticker in expired:
            order = self.pending_orders.pop(ticker)

            # Cancel real order if live
            if order.get("live") and order.get("order_id"):
                try:
                    self.client.cancel_order(order["order_id"])
                    print(f"  CANCELLED: {ticker} (deadline reached)")
                except Exception as e:
                    print(f"  Cancel failed {ticker}: {e}")

            order["status"] = "expired"
            order["expired_time"] = datetime.now().isoformat()
            self.expire_count += 1

            self._log_jsonl(OBS_LOG, {
                "type": "order_expired",
                "ts": datetime.now().isoformat(),
                "ticker": ticker,
                "strategy": order.get("strategy", ""),
                "buy_side": order.get("buy_side", ""),
                "buy_price": order.get("buy_price", 0),
            })

        if filled or expired:
            total_orders = self.fill_count + self.expire_count
            fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0
            print(f"  Orders: +{len(filled)} filled, +{len(expired)} expired | "
                  f"Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%)")

    # ── Settlement ──

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

                # Compute P&L with maker fees
                buy_side = pos["buy_side"]
                buy_price = pos["buy_price"]
                contracts = pos["contracts"]
                fee = calculate_maker_fee(contracts, buy_price)

                won = (buy_side == result)
                if won:
                    pnl = (100 - buy_price) * contracts - fee
                else:
                    pnl = -(buy_price * contracts) - fee

                # Archive to history
                history_entry = {
                    **pos,
                    "settlement_result": result,
                    "won": won,
                    "pnl_cents": pnl,
                    "fee_cents": fee,
                    "settled_time": datetime.now().isoformat(),
                }
                self._log_jsonl(HISTORY_LOG, history_entry)

                self.settled_count += 1
                self.total_pnl += pnl
                settled.append((ticker, result, pnl, won, pos["strategy"]))

                del self.filled_positions[ticker]

            except Exception:
                continue

        if settled:
            wins = sum(1 for _, _, _, w, _ in settled if w)
            losses = len(settled) - wins
            pnl_batch = sum(p for _, _, p, _, _ in settled)
            print(f"  Settled {len(settled)}: {wins}W/{losses}L, "
                  f"batch P&L: {pnl_batch:+d}c | "
                  f"Total: {self.total_pnl:+d}c (${self.total_pnl / 100:+.2f})")

    # ── Signal Settlement Backfill ──

    def _backfill_signal_settlements(self):
        """
        Backfill settlement results into underdog_signals.jsonl.
        Reads unsettled signals, checks if their markets have settled,
        writes results to a settlement mapping file.
        """
        settlement_map_path = os.path.join(DATA_DIR, "signal_settlements.json")

        # Load existing settlement map
        settlement_map = {}
        if os.path.exists(settlement_map_path):
            try:
                with open(settlement_map_path) as f:
                    settlement_map = json.load(f)
            except Exception:
                pass

        # Find unsettled tickers from signal log
        signal_log = os.path.join(DATA_DIR, "underdog_signals.jsonl")
        if not os.path.exists(signal_log):
            return

        unsettled_tickers = set()
        with open(signal_log) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ticker = entry.get("ticker", "")
                    if ticker and ticker not in settlement_map:
                        unsettled_tickers.add(ticker)
                except Exception:
                    pass

        if not unsettled_tickers:
            return

        # Check settlements (batch, max 10 per cycle to avoid API spam)
        checked = 0
        for ticker in unsettled_tickers:
            if checked >= 10:
                break
            try:
                market_data = self.client.get_market(ticker)
                market = market_data.get("market", market_data)
                result = market.get("result", "")
                if result in ("yes", "no"):
                    settlement_map[ticker] = result
                    checked += 1
            except Exception:
                pass
            time.sleep(0.1)

        # Save updated map
        if checked > 0:
            with open(settlement_map_path, "w") as f:
                json.dump(settlement_map, f, indent=2)

    # ── Summary Printing ──

    def _print_summary(self):
        """Print periodic summary."""
        elapsed_hrs = (datetime.now() - self.start_time).total_seconds() / 3600
        if elapsed_hrs < 0.01:
            elapsed_hrs = 0.01

        # Strategy breakdown
        by_strategy = defaultdict(lambda: {"pending": 0, "filled": 0})
        for pos in self.pending_orders.values():
            by_strategy[pos.get("strategy", "?")]["pending"] += 1
        for pos in self.filled_positions.values():
            by_strategy[pos.get("strategy", "?")]["filled"] += 1

        # Fill rate
        total_orders = self.fill_count + self.expire_count
        fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0

        # Win rate from history
        history_wins = 0
        history_losses = 0
        early_wins = 0
        early_losses = 0
        fade_wins = 0
        fade_losses = 0
        if os.path.exists(HISTORY_LOG):
            with open(HISTORY_LOG) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        strategy = entry.get("strategy", "")
                        if entry.get("won"):
                            history_wins += 1
                            if strategy == "early_window":
                                early_wins += 1
                            elif strategy == "fade_extreme":
                                fade_wins += 1
                        else:
                            history_losses += 1
                            if strategy == "early_window":
                                early_losses += 1
                            elif strategy == "fade_extreme":
                                fade_losses += 1
                    except Exception:
                        pass

        total_settled = history_wins + history_losses
        mode_tag = "LIVE" if not OBSERVATION_MODE else "OBSERVER"

        print(f"\n{'=' * 60}")
        print(f"  UNDERDOG BOT — 15-Min Crypto ({mode_tag})")
        print(f"  Runtime: {elapsed_hrs:.1f}hrs | Scans: {self.scan_count}")
        print(f"  ---")
        print(f"  Orders: {len(self.pending_orders)} pending, "
              f"{len(self.filled_positions)} filled, {self.settled_count} settled")
        if by_strategy:
            for strat, counts in sorted(by_strategy.items()):
                print(f"    {strat}: {counts['pending']}p/{counts['filled']}f")
        print(f"  Strategies: early={self.early_count} fade={self.fade_count}")
        print(f"  ---")
        if total_orders > 0:
            print(f"  Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%)")
        else:
            print(f"  Fill rate: waiting for data")
        print(f"  Expired: {self.expire_count}")
        print(f"  ---")
        if total_settled > 0:
            win_rate = history_wins / total_settled * 100
            print(f"  Settled: {total_settled} ({history_wins}W/{history_losses}L, {win_rate:.1f}%)")
            if early_wins + early_losses > 0:
                early_wr = early_wins / (early_wins + early_losses) * 100
                print(f"    Early: {early_wins}W/{early_losses}L ({early_wr:.1f}%)")
            if fade_wins + fade_losses > 0:
                fade_wr = fade_wins / (fade_wins + fade_losses) * 100
                print(f"    Fade:  {fade_wins}W/{fade_losses}L ({fade_wr:.1f}%)")
        else:
            print(f"  Settled: 0 (waiting for results)")
        print(f"  P&L: {self.total_pnl:+d}c (${self.total_pnl / 100:+.2f})")
        if total_settled > 0:
            print(f"  Per-trade avg: {self.total_pnl / total_settled:+.1f}c")
        print(f"  Exposure: ${self._current_exposure() / 100:.2f}")
        enrich_ms = self.enrichment.get_enrich_latency_ms()
        print(f"  Enrichment latency: {enrich_ms}ms")
        print(f"{'=' * 60}\n")

    # ── Main Loop ──

    def run_continuous(self):
        """Main observation/trading loop."""
        mode_str = "*** LIVE TRADING ***" if not OBSERVATION_MODE else "OBSERVATION MODE (virtual fills)"
        print("\n" + "=" * 60)
        print("  UNDERDOG BOT — 15-Min Crypto Maker")
        print(f"  Mode: {mode_str}")
        print(f"  Series: {', '.join(CRYPTO_SERIES)}")
        print(f"  Early window: T={EARLY_ENTRY_START_S}-{EARLY_ENTRY_END_S}s, "
              f"bid {EARLY_MIN_LEADER_BID}-{EARLY_MAX_LEADER_BID}c")
        print(f"  Fade extreme: T={FADE_ENTRY_START_S}-{FADE_ENTRY_END_S}s, "
              f"fav >= {FADE_EXTREME_THRESHOLD}c, dog <= {FADE_MAX_UNDERDOG_PRICE}c")
        print(f"  Skip hours: {sorted(SKIP_HOURS)}")
        print(f"  Enrichment: spot_feed + ob_momentum + cross_series + trade_tape + vol_regime")
        print("=" * 60 + "\n")

        last_settlement_check = 0
        last_print = 0
        last_signal_backfill = 0

        while True:
            try:
                now = time.time()

                # Cleanup old window entries
                self._cleanup_entered_windows()

                # 1. Fetch all market snapshots (shared across all consumers)
                snapshots = fetch_all_snapshots(self.client)
                self.scan_count += 1

                # 1b. Enrich snapshots with signal data (spot, momentum, cross, tape, vol)
                if snapshots:
                    snapshots = self.enrichment.enrich(snapshots)

                # 2. Log passive ticks (T=0-900)
                if TICK_LOGGING_ENABLED and snapshots:
                    self.tick_logger.log_from_snapshots(snapshots)

                # 3. Log underdog signal observations (Strategy 6)
                if SIGNAL_OBS_ENABLED and snapshots:
                    self.signal_logger.log_from_snapshots(snapshots)
                    # Cleanup stale tickers from signal throttle cache
                    active_tickers = {s["ticker"] for s in snapshots}
                    self.signal_logger.cleanup_tickers(active_tickers)

                # 4. Scan for early window entries (Strategy 2)
                self._scan_early_window(snapshots)

                # 5. Scan for fade-the-extreme entries (Strategy 4)
                self._scan_fade_extreme(snapshots)

                # 6. Check for fills on pending orders
                self._check_fills()

                # 7. Check settlements on filled positions
                if now - last_settlement_check >= SETTLEMENT_CHECK_INTERVAL:
                    self._check_settlements()
                    last_settlement_check = now

                # 8. Backfill signal settlements (every 5 min)
                if now - last_signal_backfill >= 300:
                    self._backfill_signal_settlements()
                    last_signal_backfill = now

                # 9. Periodic summary
                if now - last_print >= PRINT_INTERVAL_SECONDS:
                    self._print_summary()
                    last_print = now

                self._save_state()
                time.sleep(LOOP_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print("\n  Underdog bot stopped.")
                self._save_state()
                break
            except Exception as e:
                print(f"  Error in main loop: {e}")
                time.sleep(10)

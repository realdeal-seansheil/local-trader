"""
Kelly Executor — Underdog strategy clone with Kelly criterion position sizing.

Mirrors trade_underdog exactly (early window + fade extreme + enrichment filters)
but replaces fixed 3-contract sizing with Kelly-optimal sizing based on
historical win rates by price bucket.

Tracks a virtual balance starting at $100 (10,000c).

Kelly formula for binary options:
    f* = (p * b - q) / b
    where p = estimated win probability, q = 1-p, b = (100-price)/price

Half-Kelly used for conservative sizing (KELLY_FRACTION = 0.5).
"""

import os
import json
import time
import math
import calendar
from datetime import datetime, timezone
from collections import defaultdict

from .config import (
    OBSERVATION_MODE,
    LOOP_INTERVAL_SECONDS,
    PRINT_INTERVAL_SECONDS,
    SETTLEMENT_CHECK_INTERVAL,
    SETTLEMENT_BUFFER_S,
    EARLY_ENABLED,
    EARLY_ENTRY_START_S,
    EARLY_ENTRY_END_S,
    EARLY_MIN_LEADER_BID,
    EARLY_MAX_LEADER_BID,
    EARLY_MIN_DEPTH,
    EARLY_FILL_DEADLINE_S,
    EARLY_OVERNIGHT_MIN_BID,
    FADE_ENABLED,
    FADE_ENTRY_START_S,
    FADE_ENTRY_END_S,
    FADE_EXTREME_THRESHOLD,
    FADE_MAX_UNDERDOG_PRICE,
    FADE_MIN_DEPTH,
    FADE_FILL_DEADLINE_S,
    FILL_TOLERANCE_CENTS,
    CRYPTO_SERIES,
    STARTING_BALANCE_CENTS,
    KELLY_FRACTION,
    KELLY_MIN_CONTRACTS,
    KELLY_MAX_CONTRACTS,
    KELLY_MIN_EDGE,
    UNDERDOG_HISTORY_PATH,
    calculate_maker_fee,
)

from trade_underdog.market_scanner import fetch_all_snapshots, compute_elapsed, is_overnight
from trade_underdog.enrichment_manager import EnrichmentManager

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

OBS_LOG = os.path.join(DATA_DIR, "fade_obs.jsonl")
HISTORY_LOG = os.path.join(DATA_DIR, "fade_history.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "fade_state.json")


class FadeExecutor:
    def __init__(self, client):
        self.client = client

        self.pending_orders = {}
        self.filled_positions = {}
        self._entered_windows = set()

        # Counters
        self.fill_count = 0
        self.expire_count = 0
        self.settled_count = 0
        self.total_pnl = 0
        self.scan_count = 0
        self.early_count = 0
        self.fade_count = 0
        self.start_time = datetime.now()

        # Balance tracking
        self.balance = STARTING_BALANCE_CENTS
        self.balance_history = []  # [(ts, balance)] for dashboard

        # Kelly win rate estimates (bootstrapped from underdog history)
        self._win_rates = {}  # price_bucket -> win_rate
        self._load_win_rates()

        # Enrichment
        self.enrichment = EnrichmentManager(client)

        self._load_state()

    # ── Kelly Criterion ──

    def _load_win_rates(self):
        """Bootstrap win rate estimates from underdog bot history."""
        if not os.path.exists(UNDERDOG_HISTORY_PATH):
            print("  Kelly: No underdog history found, using defaults")
            self._win_rates = {
                "52-60": 0.58, "61-70": 0.62, "71-80": 0.72,
                "fade_1-10": 0.05, "fade_11-25": 0.12,
            }
            return

        buckets = defaultdict(lambda: {"wins": 0, "total": 0})
        try:
            with open(UNDERDOG_HISTORY_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    bp = entry.get("buy_price", 0)
                    strategy = entry.get("strategy", "")
                    won = entry.get("won", False)

                    if strategy == "early_window":
                        if 52 <= bp <= 60:
                            key = "52-60"
                        elif 61 <= bp <= 70:
                            key = "61-70"
                        elif 71 <= bp <= 80:
                            key = "71-80"
                        else:
                            continue
                    elif strategy == "fade_extreme":
                        if 1 <= bp <= 10:
                            key = "fade_1-10"
                        elif 11 <= bp <= 25:
                            key = "fade_11-25"
                        else:
                            continue
                    else:
                        continue

                    buckets[key]["total"] += 1
                    if won:
                        buckets[key]["wins"] += 1
        except Exception as e:
            print(f"  Kelly: Error reading underdog history: {e}")

        for key, data in buckets.items():
            if data["total"] >= 10:
                self._win_rates[key] = data["wins"] / data["total"]
            else:
                # Not enough data, use conservative defaults
                defaults = {"52-60": 0.58, "61-70": 0.62, "71-80": 0.72,
                            "fade_1-10": 0.05, "fade_11-25": 0.12}
                self._win_rates[key] = defaults.get(key, 0.55)

        # Fill any missing buckets
        for key in ["52-60", "61-70", "71-80", "fade_1-10", "fade_11-25"]:
            if key not in self._win_rates:
                defaults = {"52-60": 0.58, "61-70": 0.62, "71-80": 0.72,
                            "fade_1-10": 0.05, "fade_11-25": 0.12}
                self._win_rates[key] = defaults[key]

        print(f"  Kelly win rates: {dict(self._win_rates)}")

    def _get_win_rate(self, buy_price, strategy):
        """Look up estimated win rate for this price/strategy."""
        if strategy == "fade_extreme":
            if buy_price <= 10:
                return self._win_rates.get("fade_1-10", 0.05)
            else:
                return self._win_rates.get("fade_11-25", 0.12)
        else:
            if buy_price <= 60:
                return self._win_rates.get("52-60", 0.58)
            elif buy_price <= 70:
                return self._win_rates.get("61-70", 0.62)
            else:
                return self._win_rates.get("71-80", 0.72)

    def _kelly_size(self, buy_price, strategy):
        """
        Compute Kelly-optimal contract count.
        Returns (contracts, kelly_fraction, estimated_edge, win_prob).
        """
        p = self._get_win_rate(buy_price, strategy)
        q = 1 - p

        # Binary option odds: risk buy_price to win (100 - buy_price)
        b = (100 - buy_price) / buy_price if buy_price > 0 else 0

        # Kelly fraction: f* = (p*b - q) / b
        if b <= 0:
            return 0, 0, 0, p

        f_star = (p * b - q) / b
        edge = p * b - q  # positive = we have edge

        if edge < KELLY_MIN_EDGE:
            return 0, f_star, edge, p

        # Apply fractional Kelly
        f_adjusted = f_star * KELLY_FRACTION

        # Convert to contracts: wager = f * balance, contracts = wager / buy_price
        wager_cents = f_adjusted * self.balance
        contracts = int(wager_cents / buy_price) if buy_price > 0 else 0

        # Clamp
        contracts = max(KELLY_MIN_CONTRACTS, min(KELLY_MAX_CONTRACTS, contracts))

        # Don't bet more than we can afford
        max_affordable = int(self.balance / buy_price) if buy_price > 0 else 0
        contracts = min(contracts, max_affordable)

        if contracts < KELLY_MIN_CONTRACTS:
            return 0, f_adjusted, edge, p

        return contracts, f_adjusted, edge, p

    # ── State Persistence ──

    def _load_state(self):
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
            self.balance = state.get("balance", STARTING_BALANCE_CENTS)
            self._entered_windows = set(
                tuple(w) for w in state.get("entered_windows", [])
            )
            print(f"  Loaded state: {len(self.pending_orders)} pending, "
                  f"{len(self.filled_positions)} filled, "
                  f"balance: ${self.balance / 100:.2f}")
        except Exception as e:
            print(f"  Warning: Failed to load state: {e}")

    def _save_state(self):
        state = {
            "pending_orders": self.pending_orders,
            "filled_positions": self.filled_positions,
            "fill_count": self.fill_count,
            "expire_count": self.expire_count,
            "settled_count": self.settled_count,
            "total_pnl": self.total_pnl,
            "early_count": self.early_count,
            "fade_count": self.fade_count,
            "balance": self.balance,
            "entered_windows": list(self._entered_windows),
            "last_saved": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def _log_jsonl(self, path, entry):
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    # ── Window Cleanup ──

    def _cleanup_entered_windows(self):
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

    # ── Exposure ──

    def _current_exposure(self):
        exposure = 0
        for pos in list(self.pending_orders.values()) + list(self.filled_positions.values()):
            exposure += pos.get("buy_price", 0) * pos.get("contracts", 0)
        return exposure

    # ── Strategy 2: Early Window (mirrored from underdog) ──

    def _scan_early_window(self, snapshots):
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

            if ticker in self.pending_orders or ticker in self.filled_positions:
                continue
            window_key = (series, close_time)
            if window_key in self._entered_windows:
                continue

            leader_bid = max(ob["yes_bid"], ob["no_bid"])
            if leader_bid < effective_min_bid or leader_bid > EARLY_MAX_LEADER_BID:
                continue

            if ob["yes_bid"] >= ob["no_bid"]:
                buy_side, buy_price, depth = "yes", ob["yes_bid"], ob["yes_depth"]
            else:
                buy_side, buy_price, depth = "no", ob["no_bid"], ob["no_depth"]

            if depth < EARLY_MIN_DEPTH:
                continue

            # Enrichment filters (same as underdog)
            vol = snap.get("vol_regime", {})
            if vol.get("regime_action") == "skip_early":
                continue
            momentum = snap.get("momentum", {})
            if momentum.get("bid_velocity", 0) < -1:
                continue
            spot = snap.get("spot", {})
            if spot.get("leader_divergent"):
                continue

            # ═══ KELLY SIZING ═══
            contracts, kelly_f, edge, win_prob = self._kelly_size(buy_price, "early_window")
            if contracts == 0:
                continue

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
                "kelly_f": round(kelly_f, 4),
                "kelly_edge": round(edge, 4),
                "kelly_win_prob": round(win_prob, 4),
                "balance_at_entry": self.balance,
            }

            if not OBSERVATION_MODE:
                try:
                    result = self.client.place_order(
                        ticker=ticker, side=buy_side, action="buy",
                        count=contracts, price=buy_price,
                    )
                    if "error" in result:
                        continue
                    order["order_id"] = result.get("order", {}).get("order_id", "")
                    order["live"] = True
                except Exception:
                    continue

            self.pending_orders[ticker] = order
            self._entered_windows.add(window_key)
            self.early_count += 1

            mode_tag = "LIVE" if not OBSERVATION_MODE else "OBS"
            print(f"  [{mode_tag}] EARLY: {ticker} {buy_side.upper()} "
                  f"@{buy_price}c x{contracts} (kelly={kelly_f:.2f} edge={edge:.3f} "
                  f"p={win_prob:.2f}) bal=${self.balance / 100:.2f}")

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

    # ── Strategy 4: Fade the Extreme (mirrored from underdog) ──

    def _scan_fade_extreme(self, snapshots):
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

            if ticker in self.pending_orders or ticker in self.filled_positions:
                continue
            window_key = (series, close_time)
            if window_key in self._entered_windows:
                continue

            if ob["yes_bid"] >= ob["no_bid"]:
                favorite_bid = ob["yes_bid"]
                underdog_side, underdog_bid, underdog_depth = "no", ob["no_bid"], ob["no_depth"]
            else:
                favorite_bid = ob["no_bid"]
                underdog_side, underdog_bid, underdog_depth = "yes", ob["yes_bid"], ob["yes_depth"]

            if favorite_bid < FADE_EXTREME_THRESHOLD:
                continue
            if underdog_bid > FADE_MAX_UNDERDOG_PRICE or underdog_bid <= 0:
                continue
            if underdog_depth < FADE_MIN_DEPTH:
                continue

            # Enrichment filters (same as underdog)
            vol = snap.get("vol_regime", {})
            if vol.get("regime_action") == "skip_fade":
                continue
            tape = snap.get("tape", {})
            if tape.get("acceleration", 0) > 5:
                continue
            momentum_data = snap.get("momentum", {})
            if momentum_data.get("bid_velocity", 0) > 2:
                continue

            # ═══ KELLY SIZING ═══
            contracts, kelly_f, edge, win_prob = self._kelly_size(underdog_bid, "fade_extreme")
            if contracts == 0:
                continue

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
                "kelly_f": round(kelly_f, 4),
                "kelly_edge": round(edge, 4),
                "kelly_win_prob": round(win_prob, 4),
                "balance_at_entry": self.balance,
            }

            if not OBSERVATION_MODE:
                try:
                    result = self.client.place_order(
                        ticker=ticker, side=underdog_side, action="buy",
                        count=contracts, price=underdog_bid,
                    )
                    if "error" in result:
                        continue
                    order["order_id"] = result.get("order", {}).get("order_id", "")
                    order["live"] = True
                except Exception:
                    continue

            self.pending_orders[ticker] = order
            self._entered_windows.add(window_key)
            self.fade_count += 1

            mode_tag = "LIVE" if not OBSERVATION_MODE else "OBS"
            print(f"  [{mode_tag}] FADE: {ticker} {underdog_side.upper()} "
                  f"@{underdog_bid}c x{contracts} (kelly={kelly_f:.2f} edge={edge:.3f} "
                  f"p={win_prob:.2f}) bal=${self.balance / 100:.2f}")

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

    # ── Fill Detection (same as underdog) ──

    def _check_fills(self):
        if not self.pending_orders:
            return

        filled = []
        expired = []

        for ticker, order in list(self.pending_orders.items()):
            close_time = order.get("close_time", "")
            elapsed_s = compute_elapsed(close_time)
            strategy = order.get("strategy", "early_window")
            deadline = EARLY_FILL_DEADLINE_S if strategy == "early_window" else FADE_FILL_DEADLINE_S

            if elapsed_s is not None and elapsed_s >= deadline:
                expired.append(ticker)
                continue

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

            accumulated = 0
            last_fill_time = ""
            last_fill_price = 0
            last_taker_side = ""

            for trade in trades:
                trade_time = trade.get("created_time", "")
                if trade_time and trade_time < order_time_str:
                    continue

                yes_price_raw = trade.get("yes_price_dollars") or trade.get("yes_price", 0)
                yes_price = round(float(yes_price_raw) * 100)
                taker_side = trade.get("taker_side", "")
                count_raw = trade.get("count_fp") or trade.get("count", 0)
                trade_count = int(float(count_raw))

                if buy_side == "yes":
                    if abs(yes_price - buy_price) <= FILL_TOLERANCE_CENTS:
                        accumulated += trade_count
                        last_fill_time = trade_time
                        last_fill_price = yes_price
                        last_taker_side = taker_side
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

        for ticker, fill_time, fill_yes_price, fill_count, fill_taker_side in filled:
            order = self.pending_orders.pop(ticker)
            order["status"] = "filled"
            order["fill_time"] = fill_time
            order["fill_yes_price"] = fill_yes_price
            order["fill_volume"] = fill_count
            order["fill_taker_side"] = fill_taker_side

            try:
                order_placed = datetime.fromisoformat(order["order_time"].replace("Z", "+00:00"))
                ft = fill_time.replace("Z", "+00:00") if fill_time else ""
                fill_dt = datetime.fromisoformat(ft) if ft else datetime.now(timezone.utc)
                order["time_to_fill_s"] = round((fill_dt - order_placed).total_seconds())
            except Exception:
                order["time_to_fill_s"] = 0

            self.filled_positions[ticker] = order
            self.fill_count += 1

            print(f"  FILLED: {ticker} {order['buy_side'].upper()} "
                  f"@{order['buy_price']}c x{order['contracts']} "
                  f"(fill in {order['time_to_fill_s']}s)")

            self._log_jsonl(OBS_LOG, {
                "type": "order_filled", "ts": datetime.now().isoformat(),
                "ticker": ticker, "fill_time": fill_time,
                "time_to_fill_s": order["time_to_fill_s"],
                "buy_side": order["buy_side"], "buy_price": order["buy_price"],
                "contracts": order["contracts"],
            })

        for ticker in expired:
            order = self.pending_orders.pop(ticker)
            if order.get("live") and order.get("order_id"):
                try:
                    self.client.cancel_order(order["order_id"])
                except Exception:
                    pass
            order["status"] = "expired"
            self.expire_count += 1
            self._log_jsonl(OBS_LOG, {
                "type": "order_expired", "ts": datetime.now().isoformat(),
                "ticker": ticker, "strategy": order.get("strategy", ""),
                "buy_side": order.get("buy_side", ""),
                "buy_price": order.get("buy_price", 0),
            })

        if filled or expired:
            total_orders = self.fill_count + self.expire_count
            fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0
            print(f"  Orders: +{len(filled)} filled, +{len(expired)} expired | "
                  f"Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%)")

    # ── Settlement (with balance tracking) ──

    def _check_settlements(self):
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

                buy_side = pos["buy_side"]
                buy_price = pos["buy_price"]
                contracts = pos["contracts"]
                fee = calculate_maker_fee(contracts, buy_price)

                won = (buy_side == result)
                if won:
                    pnl = (100 - buy_price) * contracts - fee
                else:
                    pnl = -(buy_price * contracts) - fee

                # Update balance
                self.balance += pnl

                history_entry = {
                    **pos,
                    "settlement_result": result,
                    "won": won,
                    "pnl_cents": pnl,
                    "fee_cents": fee,
                    "settled_time": datetime.now().isoformat(),
                    "balance_after": self.balance,
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
                  f"Balance: ${self.balance / 100:.2f}")

    # ── Summary ──

    def _print_summary(self):
        elapsed_hrs = (datetime.now() - self.start_time).total_seconds() / 3600
        if elapsed_hrs < 0.01:
            elapsed_hrs = 0.01

        total_orders = self.fill_count + self.expire_count
        fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0

        history_wins = 0
        history_losses = 0
        if os.path.exists(HISTORY_LOG):
            with open(HISTORY_LOG) as f:
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
        mode_tag = "LIVE" if not OBSERVATION_MODE else "OBSERVER"
        bal_pct = (self.balance - STARTING_BALANCE_CENTS) / STARTING_BALANCE_CENTS * 100

        print(f"\n{'=' * 60}")
        print(f"  KELLY BOT — Underdog Clone + Kelly Sizing ({mode_tag})")
        print(f"  Balance: ${self.balance / 100:.2f} ({bal_pct:+.1f}%)")
        print(f"  Runtime: {elapsed_hrs:.1f}hrs | Scans: {self.scan_count}")
        print(f"  ---")
        print(f"  Strategies: early={self.early_count} fade={self.fade_count}")
        print(f"  Orders: {len(self.pending_orders)} pending, "
              f"{len(self.filled_positions)} filled, {self.settled_count} settled")
        if total_orders > 0:
            print(f"  Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%)")
        if total_settled > 0:
            win_rate = history_wins / total_settled * 100
            print(f"  Settled: {total_settled} ({history_wins}W/{history_losses}L, {win_rate:.1f}%)")
        print(f"  P&L: {self.total_pnl:+d}c (${self.total_pnl / 100:+.2f})")
        if total_settled > 0:
            print(f"  Per-trade avg: {self.total_pnl / total_settled:+.1f}c")
        print(f"  Kelly win rates: {dict(self._win_rates)}")
        print(f"  Enrichment latency: {self.enrichment.get_enrich_latency_ms()}ms")
        print(f"{'=' * 60}\n")

    # ── Main Loop ──

    def run_continuous(self):
        mode_str = "*** LIVE TRADING ***" if not OBSERVATION_MODE else "OBSERVATION MODE"
        print("\n" + "=" * 60)
        print("  KELLY BOT — Underdog Clone + Kelly Sizing")
        print(f"  Mode: {mode_str}")
        print(f"  Starting balance: ${STARTING_BALANCE_CENTS / 100:.2f}")
        print(f"  Kelly fraction: {KELLY_FRACTION} (half-Kelly)")
        print(f"  Series: {', '.join(CRYPTO_SERIES)}")
        print(f"  Early: T={EARLY_ENTRY_START_S}-{EARLY_ENTRY_END_S}s, "
              f"bid {EARLY_MIN_LEADER_BID}-{EARLY_MAX_LEADER_BID}c")
        print(f"  Fade: T={FADE_ENTRY_START_S}-{FADE_ENTRY_END_S}s, "
              f"fav >= {FADE_EXTREME_THRESHOLD}c, dog <= {FADE_MAX_UNDERDOG_PRICE}c")
        print(f"  Win rates: {dict(self._win_rates)}")
        print("=" * 60 + "\n")

        last_settlement_check = 0
        last_print = 0
        last_kelly_refresh = time.time()

        while True:
            try:
                now = time.time()
                self._cleanup_entered_windows()

                snapshots = fetch_all_snapshots(self.client)
                self.scan_count += 1

                if snapshots:
                    snapshots = self.enrichment.enrich(snapshots)

                self._scan_early_window(snapshots)
                self._scan_fade_extreme(snapshots)
                self._check_fills()

                if now - last_settlement_check >= SETTLEMENT_CHECK_INTERVAL:
                    self._check_settlements()
                    last_settlement_check = now

                # Refresh Kelly win rates every hour from underdog history
                if now - last_kelly_refresh >= 3600:
                    self._load_win_rates()
                    last_kelly_refresh = now

                if now - last_print >= PRINT_INTERVAL_SECONDS:
                    self._print_summary()
                    last_print = now

                self._save_state()
                time.sleep(LOOP_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print("\n  Kelly bot stopped.")
                self._save_state()
                break
            except Exception as e:
                print(f"  Error in main loop: {e}")
                time.sleep(10)

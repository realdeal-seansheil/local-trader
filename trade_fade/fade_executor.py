"""
Fade Executor — Enrichment-gated high-ratio fade strategy.

Shadow bot running alongside trade_underdog. Single strategy: buy the
underdog side (11-15c) when enrichment signals indicate the extreme
favorite move is losing steam.

Reuses trade_underdog infrastructure:
  - EnrichmentManager (spot, OB momentum, cross-series, trade tape, vol regime)
  - market_scanner (fetch_all_snapshots, compute_elapsed)
  - KalshiClient (from trade_arbitrage)
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
    PRINT_INTERVAL_SECONDS,
    SETTLEMENT_CHECK_INTERVAL,
    SETTLEMENT_BUFFER_S,
    FADE_ENTRY_START_S,
    FADE_ENTRY_END_S,
    FADE_MIN_FAVORITE_BID,
    FADE_MIN_UNDERDOG_PRICE,
    FADE_MAX_UNDERDOG_PRICE,
    FADE_MIN_DEPTH,
    FADE_MAX_CONTRACTS,
    FADE_FILL_DEADLINE_S,
    FILL_TOLERANCE_CENTS,
    GATE_MAX_TAPE_ACCELERATION,
    GATE_MAX_VELOCITY_30S,
    GATE_MAX_CROSS_AGREEMENT,
    GATE_MAX_BID_VELOCITY,
    CRYPTO_SERIES,
    calculate_maker_fee,
)

# Import shared infrastructure from sibling module
from trade_underdog.market_scanner import fetch_all_snapshots, compute_elapsed
from trade_underdog.enrichment_manager import EnrichmentManager

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

OBS_LOG = os.path.join(DATA_DIR, "fade_obs.jsonl")
HISTORY_LOG = os.path.join(DATA_DIR, "fade_history.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "fade_state.json")


class FadeExecutor:
    def __init__(self, client):
        self.client = client

        # Two-stage tracking: pending → filled → settled
        self.pending_orders = {}
        self.filled_positions = {}
        self._entered_windows = set()  # (series, close_time) dedup

        # Counters
        self.fill_count = 0
        self.expire_count = 0
        self.settled_count = 0
        self.total_pnl = 0
        self.scan_count = 0
        self.fade_count = 0
        self.gate_blocked = 0  # count of entries blocked by enrichment gates
        self.start_time = datetime.now()

        # Shared enrichment infrastructure
        self.enrichment = EnrichmentManager(client)

        self._load_state()

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
            self.fade_count = state.get("fade_count", 0)
            self.gate_blocked = state.get("gate_blocked", 0)
            self._entered_windows = set(
                tuple(w) for w in state.get("entered_windows", [])
            )
            print(f"  Loaded state: {len(self.pending_orders)} pending, "
                  f"{len(self.filled_positions)} filled, "
                  f"{self.settled_count} settled, P&L: {self.total_pnl:+d}c")
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
            "fade_count": self.fade_count,
            "gate_blocked": self.gate_blocked,
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

    # ── Core Strategy: Enrichment-Gated Fade ──

    def _scan_fade(self, snapshots):
        """
        Buy the underdog side (11-15c) when enrichment signals indicate
        the extreme favorite is losing steam. All 4 enrichment gates
        must pass for entry.
        """
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

            # Find favorite and underdog sides
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

            # Core thresholds
            if favorite_bid < FADE_MIN_FAVORITE_BID:
                continue
            if underdog_bid < FADE_MIN_UNDERDOG_PRICE or underdog_bid > FADE_MAX_UNDERDOG_PRICE:
                continue
            if underdog_depth < FADE_MIN_DEPTH:
                continue

            # ══════════════════════════════════════════
            # ENRICHMENT SIGNAL GATES — the differentiator
            # All gates must pass. If any data is missing, skip (strict mode).
            # ══════════════════════════════════════════

            tape = snap.get("tape", {})
            cross = snap.get("cross_series", {})
            momentum = snap.get("momentum", {})

            # Gate 1: Tape acceleration must be negative (volume dying down)
            tape_acc = tape.get("acceleration")
            if tape_acc is None or tape_acc > GATE_MAX_TAPE_ACCELERATION:
                self.gate_blocked += 1
                continue

            # Gate 2: Low recent trading activity
            vel30 = tape.get("velocity_30s")
            if vel30 is None or vel30 > GATE_MAX_VELOCITY_30S:
                self.gate_blocked += 1
                continue

            # Gate 3: Cross-series move not unanimous
            agreement = cross.get("agreement_count")
            if agreement is None or agreement > GATE_MAX_CROSS_AGREEMENT:
                self.gate_blocked += 1
                continue

            # Gate 4: Favorite bid not still climbing
            bid_vel = momentum.get("bid_velocity")
            if bid_vel is None or bid_vel > GATE_MAX_BID_VELOCITY:
                self.gate_blocked += 1
                continue

            # ═══ All gates passed — enter fade ═══

            contracts = FADE_MAX_CONTRACTS

            order = {
                "ticker": ticker,
                "title": snap.get("title", ""),
                "series": series,
                "strategy": "enrichment_fade",
                "buy_side": underdog_side,
                "buy_price": underdog_bid,
                "favorite_bid": favorite_bid,
                "contracts": contracts,
                "depth": underdog_depth,
                "order_time": datetime.now(timezone.utc).isoformat(),
                "close_time": close_time,
                "elapsed_at_entry": elapsed_s,
                "status": "pending",
                # Gate values at entry (for analysis)
                "gate_tape_acc": tape_acc,
                "gate_vel30": vel30,
                "gate_cross_agree": agreement,
                "gate_bid_vel": bid_vel,
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
                  f"T={elapsed_s:.0f}s | gates: acc={tape_acc:.1f} "
                  f"vel30={vel30:.0f} cross={agreement} bid_vel={bid_vel:.3f}")

            self._log_jsonl(OBS_LOG, {
                "type": "fade_order", "ts": datetime.now().isoformat(), **order,
                "enrichment": {
                    "spot": snap.get("spot", {}),
                    "tape": tape,
                    "momentum": momentum,
                    "cross_series": cross,
                    "vol_regime": snap.get("vol_regime", {}),
                },
            })

    # ── Fill Detection ──

    def _check_fills(self):
        if not self.pending_orders:
            return

        filled = []
        expired = []

        for ticker, order in list(self.pending_orders.items()):
            close_time = order.get("close_time", "")
            elapsed_s = compute_elapsed(close_time)

            if elapsed_s is not None and elapsed_s >= FADE_FILL_DEADLINE_S:
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

            # LIVE: Check real order status
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

            # OBS: Simulate fills (try enrichment cache first)
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

                # API returns dollars as strings
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

        # Process fills
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
            })

        # Process expirations
        for ticker in expired:
            order = self.pending_orders.pop(ticker)

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
                "type": "order_expired", "ts": datetime.now().isoformat(),
                "ticker": ticker, "buy_side": order.get("buy_side", ""),
                "buy_price": order.get("buy_price", 0),
            })

        if filled or expired:
            total_orders = self.fill_count + self.expire_count
            fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0
            print(f"  Orders: +{len(filled)} filled, +{len(expired)} expired | "
                  f"Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%)")

    # ── Settlement ──

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
                settled.append((ticker, result, pnl, won))

                del self.filled_positions[ticker]

            except Exception:
                continue

        if settled:
            wins = sum(1 for _, _, _, w in settled if w)
            losses = len(settled) - wins
            pnl_batch = sum(p for _, _, p, _ in settled)
            print(f"  Settled {len(settled)}: {wins}W/{losses}L, "
                  f"batch P&L: {pnl_batch:+d}c | "
                  f"Total: {self.total_pnl:+d}c (${self.total_pnl / 100:+.2f})")

    # ── Summary ──

    def _print_summary(self):
        elapsed_hrs = (datetime.now() - self.start_time).total_seconds() / 3600
        if elapsed_hrs < 0.01:
            elapsed_hrs = 0.01

        total_orders = self.fill_count + self.expire_count
        fill_rate = self.fill_count / total_orders * 100 if total_orders > 0 else 0

        # Win rate from history
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

        print(f"\n{'=' * 60}")
        print(f"  FADE BOT — Enrichment-Gated High-Ratio Fades ({mode_tag})")
        print(f"  Runtime: {elapsed_hrs:.1f}hrs | Scans: {self.scan_count}")
        print(f"  ---")
        print(f"  Fades entered: {self.fade_count} | Gates blocked: {self.gate_blocked}")
        print(f"  Orders: {len(self.pending_orders)} pending, "
              f"{len(self.filled_positions)} filled, {self.settled_count} settled")
        if total_orders > 0:
            print(f"  Fill rate: {self.fill_count}/{total_orders} ({fill_rate:.0f}%)")
        else:
            print(f"  Fill rate: waiting for data")
        print(f"  Expired: {self.expire_count}")
        print(f"  ---")
        if total_settled > 0:
            win_rate = history_wins / total_settled * 100
            print(f"  Settled: {total_settled} ({history_wins}W/{history_losses}L, {win_rate:.1f}%)")
        else:
            print(f"  Settled: 0 (waiting for results)")
        print(f"  P&L: {self.total_pnl:+d}c (${self.total_pnl / 100:+.2f})")
        if total_settled > 0:
            print(f"  Per-trade avg: {self.total_pnl / total_settled:+.1f}c")
        print(f"  Exposure: ${self._current_exposure() / 100:.2f}")
        enrich_ms = self.enrichment.get_enrich_latency_ms()
        print(f"  Enrichment latency: {enrich_ms}ms")
        print(f"  ---")
        print(f"  Gates: acc≤{GATE_MAX_TAPE_ACCELERATION} vel30≤{GATE_MAX_VELOCITY_30S} "
              f"cross≤{GATE_MAX_CROSS_AGREEMENT} bid_vel≤{GATE_MAX_BID_VELOCITY}")
        print(f"  Underdog range: {FADE_MIN_UNDERDOG_PRICE}-{FADE_MAX_UNDERDOG_PRICE}c")
        print(f"{'=' * 60}\n")

    # ── Main Loop ──

    def run_continuous(self):
        mode_str = "*** LIVE TRADING ***" if not OBSERVATION_MODE else "OBSERVATION MODE (virtual fills)"
        print("\n" + "=" * 60)
        print("  FADE BOT — Enrichment-Gated High-Ratio Fades")
        print(f"  Mode: {mode_str}")
        print(f"  Series: {', '.join(CRYPTO_SERIES)}")
        print(f"  Window: T={FADE_ENTRY_START_S}-{FADE_ENTRY_END_S}s")
        print(f"  Favorite >= {FADE_MIN_FAVORITE_BID}c, "
              f"Underdog {FADE_MIN_UNDERDOG_PRICE}-{FADE_MAX_UNDERDOG_PRICE}c")
        print(f"  Gates: tape_acc≤{GATE_MAX_TAPE_ACCELERATION} vel30≤{GATE_MAX_VELOCITY_30S} "
              f"cross≤{GATE_MAX_CROSS_AGREEMENT} bid_vel≤{GATE_MAX_BID_VELOCITY}")
        print(f"  Enrichment: spot_feed + ob_momentum + cross_series + trade_tape + vol_regime")
        print("=" * 60 + "\n")

        last_settlement_check = 0
        last_print = 0

        while True:
            try:
                now = time.time()

                self._cleanup_entered_windows()

                # 1. Fetch all market snapshots
                snapshots = fetch_all_snapshots(self.client)
                self.scan_count += 1

                # 2. Enrich with signal data
                if snapshots:
                    snapshots = self.enrichment.enrich(snapshots)

                # 3. Scan for fade entries
                self._scan_fade(snapshots)

                # 4. Check fills
                self._check_fills()

                # 5. Check settlements
                if now - last_settlement_check >= SETTLEMENT_CHECK_INTERVAL:
                    self._check_settlements()
                    last_settlement_check = now

                # 6. Periodic summary
                if now - last_print >= PRINT_INTERVAL_SECONDS:
                    self._print_summary()
                    last_print = now

                self._save_state()
                time.sleep(LOOP_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                print("\n  Fade bot stopped.")
                self._save_state()
                break
            except Exception as e:
                print(f"  Error in main loop: {e}")
                time.sleep(10)

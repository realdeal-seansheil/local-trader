"""
Maker Executor — Observation-mode favorite-bias strategy.
Scans all Kalshi markets, logs hypothetical trades, tracks virtual positions,
and computes hypothetical P&L from settlement results.

Runs alongside the momentum bot with zero interference (read-only API calls).
"""

import os
import json
import time
import math
from datetime import datetime
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
)
from .market_scanner import scan_markets, calculate_maker_fee

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

OBS_LOG = os.path.join(DATA_DIR, "maker_obs.jsonl")
OBS_HISTORY = os.path.join(DATA_DIR, "maker_obs_history.jsonl")
SCAN_LOG = os.path.join(DATA_DIR, "maker_scan_log.jsonl")
STATE_FILE = os.path.join(DATA_DIR, "maker_state.json")


class MakerExecutor:
    def __init__(self, client):
        self.client = client
        self.virtual_positions = {}  # ticker -> position dict
        self.settled_count = 0
        self.total_hypothetical_pnl = 0
        self.scan_count = 0
        self.start_time = datetime.now()
        self._load_state()

    def _load_state(self):
        """Load virtual positions from state file."""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                self.virtual_positions = state.get("virtual_positions", {})
                self.settled_count = state.get("settled_count", 0)
                self.total_hypothetical_pnl = state.get("total_hypothetical_pnl", 0)
                print(f"  Loaded state: {len(self.virtual_positions)} virtual positions, "
                      f"{self.settled_count} settled, P&L: {self.total_hypothetical_pnl:+d}c")
            except Exception as e:
                print(f"  Warning: Failed to load state: {e}")

    def _save_state(self):
        """Persist virtual positions to state file."""
        state = {
            "virtual_positions": self.virtual_positions,
            "settled_count": self.settled_count,
            "total_hypothetical_pnl": self.total_hypothetical_pnl,
            "last_saved": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def _log_jsonl(self, path, entry):
        """Append a JSON entry to a JSONL file."""
        with open(path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def run_continuous(self):
        """Main observation loop."""
        print("\n" + "=" * 60)
        print("  MAKER OBSERVER — Favorite Bias Strategy")
        print("  Mode: OBSERVATION ONLY (no orders placed)")
        print(f"  Scan interval: {SCAN_INTERVAL_SECONDS}s")
        print(f"  Max virtual positions: {MAX_POSITIONS}")
        print(f"  Max exposure: ${MAX_EXPOSURE_CENTS / 100:.0f}")
        print("=" * 60 + "\n")

        last_settlement_check = 0
        last_print = 0

        while True:
            try:
                now = time.time()

                # 1. Scan markets for opportunities
                self._scan_and_log()

                # 2. Check settlements periodically
                if now - last_settlement_check >= SETTLEMENT_CHECK_INTERVAL:
                    self._check_settlements()
                    last_settlement_check = now

                # 3. Print summary periodically
                if now - last_print >= PRINT_INTERVAL_SECONDS:
                    self._print_summary()
                    last_print = now

                # Save state after each cycle
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
        """Scan markets and log new opportunities."""
        self.scan_count += 1
        opportunities, total_scanned, series_hits = scan_markets(self.client)

        # Log scan stats
        self._log_jsonl(SCAN_LOG, {
            "ts": datetime.now().isoformat(),
            "scan_number": self.scan_count,
            "markets_scanned": total_scanned,
            "opportunities_found": len(opportunities),
            "virtual_positions": len(self.virtual_positions),
            "series_hits": series_hits,
        })

        if self.scan_count <= 3 or self.scan_count % 10 == 0:
            series_str = ", ".join(f"{k}:{v}" for k, v in sorted(series_hits.items())) if series_hits else "none"
            print(f"  Scan #{self.scan_count}: {total_scanned} markets → "
                  f"{len(opportunities)} opportunities | "
                  f"{len(self.virtual_positions)} virtual positions")
            if self.scan_count <= 3:
                print(f"    Candidates by series: {series_str}")

        # Current exposure
        current_exposure = sum(
            p["favorite_price"] * p["contracts"]
            for p in self.virtual_positions.values()
        )

        # Add new virtual positions for opportunities we're not already tracking
        new_count = 0
        for opp in opportunities:
            ticker = opp["ticker"]

            # Skip if already tracked
            if ticker in self.virtual_positions:
                continue

            # Check limits
            if len(self.virtual_positions) >= MAX_POSITIONS:
                break
            position_cost = opp["favorite_price"] * opp["contracts"]
            if current_exposure + position_cost > MAX_EXPOSURE_CENTS:
                continue

            # Create virtual position
            position = {
                "ticker": ticker,
                "title": opp["title"],
                "category": opp["category"],
                "favorite_side": opp["favorite_side"],
                "favorite_price": opp["favorite_price"],
                "longshot_price": opp["longshot_price"],
                "contracts": opp["contracts"],
                "edge_estimate_pp": opp["edge_estimate_pp"],
                "edge_cents": opp["edge_cents"],
                "depth": opp["depth"],
                "entry_time": datetime.now().isoformat(),
                "close_time": opp["close_time"],
            }

            self.virtual_positions[ticker] = position
            current_exposure += position_cost
            new_count += 1

            # Log the hypothetical entry
            self._log_jsonl(OBS_LOG, {
                "type": "virtual_entry",
                "ts": datetime.now().isoformat(),
                **position,
            })

        if new_count > 0:
            print(f"  +{new_count} new virtual positions "
                  f"(total: {len(self.virtual_positions)}, "
                  f"exposure: ${current_exposure / 100:.2f})")

    def _check_settlements(self):
        """Check if any virtual positions have settled."""
        settled = []

        for ticker, pos in list(self.virtual_positions.items()):
            try:
                market_data = self.client.get_market(ticker)
                market = market_data.get("market", market_data)
                result = market.get("result", "")

                if result not in ("yes", "no"):
                    continue  # Not yet settled

                # Compute hypothetical P&L
                favorite_side = pos["favorite_side"]
                favorite_price = pos["favorite_price"]
                contracts = pos["contracts"]
                fee = calculate_maker_fee(contracts, favorite_price)

                if favorite_side == result:
                    # Favorite won — we profit
                    payout = 100 * contracts
                    cost = favorite_price * contracts
                    pnl = payout - cost - fee
                    won = True
                else:
                    # Longshot hit — we lose
                    payout = 0
                    cost = favorite_price * contracts
                    pnl = payout - cost - fee
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

                # Remove from active
                del self.virtual_positions[ticker]

            except Exception:
                continue  # Skip on API error, try next cycle

        if settled:
            wins = sum(1 for _, _, _, w in settled if w)
            losses = len(settled) - wins
            pnl_batch = sum(p for _, _, p, _ in settled)
            print(f"  Settled {len(settled)} positions: "
                  f"{wins}W/{losses}L, batch P&L: {pnl_batch:+d}c | "
                  f"Total: {self.total_hypothetical_pnl:+d}c "
                  f"(${self.total_hypothetical_pnl / 100:+.2f})")

    def _print_summary(self):
        """Print periodic summary."""
        elapsed = (datetime.now() - self.start_time).total_seconds() / 3600
        if elapsed < 0.01:
            elapsed = 0.01

        # Category breakdown
        by_category = defaultdict(int)
        for pos in self.virtual_positions.values():
            by_category[pos["category"]] += 1

        # History stats
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

        total_trades = history_wins + history_losses

        print(f"\n{'=' * 50}")
        print(f"  MAKER OBSERVER SUMMARY")
        print(f"  Runtime: {elapsed:.1f}hrs | Scans: {self.scan_count}")
        print(f"  Virtual positions: {len(self.virtual_positions)}")
        if by_category:
            cats = ", ".join(f"{k}:{v}" for k, v in sorted(by_category.items()))
            print(f"  Categories: {cats}")
        print(f"  Settled: {total_trades} "
              f"({history_wins}W/{history_losses}L, "
              f"{history_wins / total_trades * 100:.1f}% win rate)" if total_trades > 0 else
              f"  Settled: 0 (waiting)")
        print(f"  Hypothetical P&L: {self.total_hypothetical_pnl:+d}c "
              f"(${self.total_hypothetical_pnl / 100:+.2f})")
        if total_trades > 0:
            print(f"  Per-trade avg: {self.total_hypothetical_pnl / total_trades:+.1f}c")
        if elapsed >= 1:
            print(f"  Hourly rate: ${self.total_hypothetical_pnl / 100 / elapsed:+.2f}/hr")
        print(f"{'=' * 50}\n")

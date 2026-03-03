"""
Position Tracker for Straddle Bot.

Manages the lifecycle of straddle positions:
- Open new straddles (entry)
- Record partial/full exits
- Persist state to disk (survives restarts)
- Track daily stats for risk limits
- Log all events to JSONL for analysis
"""

import json
import os
from datetime import datetime, date
from config import DATA_DIR


def _held_side(h):
    """Determine which side was held to expiry from a history dict."""
    if h.get("yes_sold", 0) == 0 and h.get("no_sold", 0) > 0:
        return "yes"  # sold NO, held YES
    elif h.get("no_sold", 0) == 0 and h.get("yes_sold", 0) > 0:
        return "no"   # sold YES, held NO
    return None


STATE_FILE = os.path.join(DATA_DIR, "straddle_state.json")
EVENT_LOG = os.path.join(DATA_DIR, "straddle_events.jsonl")
HISTORY_LOG = os.path.join(DATA_DIR, "straddle_history.jsonl")


class StraddlePosition:
    """Represents one straddle (YES + NO on same market)."""

    def __init__(self, ticker, series, yes_entry_price, no_entry_price,
                 contracts, entry_time=None, market_close_time=None):
        self.ticker = ticker
        self.series = series
        self.entry_time = entry_time or datetime.now().isoformat()
        self.market_close_time = market_close_time  # ISO string or None
        self.yes_entry_price = yes_entry_price      # cents (what we paid for YES)
        self.no_entry_price = no_entry_price        # cents (what we paid for NO)
        self.contracts = contracts
        self.status = "open"  # open, partial_exit, closed, expired

        # Exit tracking
        self.yes_sold = 0
        self.no_sold = 0
        self.yes_exit_price = None   # cents (what we sold YES for)
        self.no_exit_price = None    # cents (what we sold NO for)
        self.exit_time = None

        # Observation mode tracking
        self.observation = False

        # Fees
        self.taker_fees = 0  # cents — Kalshi taker fees for this entry

        # P&L
        self.pnl_cents = None
        self.pnl_best_case = None    # best case for partial exits (held side wins)
        self.pnl_actual = None       # actual P&L after settlement
        self.settlement_result = None  # "yes" or "no" — actual market outcome

    @property
    def combined_entry_cents(self):
        return self.yes_entry_price + self.no_entry_price

    @property
    def total_cost_cents(self):
        return self.combined_entry_cents * self.contracts

    def to_dict(self):
        d = {
            "ticker": self.ticker,
            "series": self.series,
            "entry_time": self.entry_time,
            "market_close_time": self.market_close_time,
            "yes_entry_price": self.yes_entry_price,
            "no_entry_price": self.no_entry_price,
            "contracts": self.contracts,
            "status": self.status,
            "yes_sold": self.yes_sold,
            "no_sold": self.no_sold,
            "yes_exit_price": self.yes_exit_price,
            "no_exit_price": self.no_exit_price,
            "exit_time": self.exit_time,
            "observation": self.observation,
            "taker_fees": self.taker_fees,
            "pnl_cents": self.pnl_cents,
        }
        if self.pnl_best_case is not None:
            d["pnl_best_case"] = self.pnl_best_case
        if self.pnl_actual is not None:
            d["pnl_actual"] = self.pnl_actual
        if self.settlement_result is not None:
            d["settlement_result"] = self.settlement_result
        return d

    @classmethod
    def from_dict(cls, d):
        pos = cls(
            ticker=d["ticker"],
            series=d["series"],
            yes_entry_price=d["yes_entry_price"],
            no_entry_price=d["no_entry_price"],
            contracts=d["contracts"],
            entry_time=d.get("entry_time"),
            market_close_time=d.get("market_close_time"),
        )
        pos.status = d.get("status", "open")
        pos.yes_sold = d.get("yes_sold", 0)
        pos.no_sold = d.get("no_sold", 0)
        pos.yes_exit_price = d.get("yes_exit_price")
        pos.no_exit_price = d.get("no_exit_price")
        pos.exit_time = d.get("exit_time")
        pos.observation = d.get("observation", False)
        pos.taker_fees = d.get("taker_fees", 0)
        pos.pnl_cents = d.get("pnl_cents")
        pos.pnl_best_case = d.get("pnl_best_case")
        pos.pnl_actual = d.get("pnl_actual")
        pos.settlement_result = d.get("settlement_result")
        return pos


class PositionTracker:
    """Track all straddle positions with file persistence."""

    def __init__(self):
        self.positions = {}  # ticker -> StraddlePosition
        self.daily_straddle_count = 0
        self.daily_exposure_cents = 0
        self.last_reset_date = date.today().isoformat()
        self._load_state()

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                for ticker, pos_dict in state.get("positions", {}).items():
                    self.positions[ticker] = StraddlePosition.from_dict(pos_dict)
                self.daily_straddle_count = state.get("daily_straddle_count", 0)
                self.daily_exposure_cents = state.get("daily_exposure_cents", 0)
                saved_date = state.get("last_reset_date", "")
                if saved_date != date.today().isoformat():
                    # New day — reset daily counters
                    self.daily_straddle_count = 0
                    self.daily_exposure_cents = 0
                self.last_reset_date = date.today().isoformat()
                print(f"  Loaded {len(self.positions)} positions from state")
            except Exception as e:
                print(f"  Warning: Could not load state: {e}")

    def save_state(self):
        state = {
            "positions": {t: p.to_dict() for t, p in self.positions.items()},
            "daily_straddle_count": self.daily_straddle_count,
            "daily_exposure_cents": self.daily_exposure_cents,
            "last_reset_date": self.last_reset_date,
            "last_saved": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def open_straddle(self, ticker, series, yes_entry_price, no_entry_price,
                      contracts, market_close_time=None, observation=False):
        """Record a new straddle entry."""
        pos = StraddlePosition(
            ticker=ticker,
            series=series,
            yes_entry_price=yes_entry_price,
            no_entry_price=no_entry_price,
            contracts=contracts,
            market_close_time=market_close_time,
        )
        pos.observation = observation
        self.positions[ticker] = pos

        self.daily_straddle_count += 1
        self.daily_exposure_cents += pos.total_cost_cents

        self.log_event({
            "type": "straddle_entry",
            "ticker": ticker,
            "series": series,
            "yes_entry_price": yes_entry_price,
            "no_entry_price": no_entry_price,
            "combined_entry": yes_entry_price + no_entry_price,
            "contracts": contracts,
            "total_cost_cents": pos.total_cost_cents,
            "observation": observation,
        })

        self.save_state()
        return pos

    def record_exit(self, ticker, side, exit_price, qty):
        """Record selling one side of a straddle."""
        if ticker not in self.positions:
            print(f"  Warning: No position for {ticker}")
            return None

        pos = self.positions[ticker]

        if side == "yes":
            pos.yes_sold += qty
            pos.yes_exit_price = exit_price
        elif side == "no":
            pos.no_sold += qty
            pos.no_exit_price = exit_price

        pos.exit_time = datetime.now().isoformat()

        # Update status
        if pos.yes_sold >= pos.contracts and pos.no_sold >= pos.contracts:
            pos.status = "closed"
        elif pos.yes_sold > 0 or pos.no_sold > 0:
            pos.status = "partial_exit"

        # Calculate P&L if fully closed
        if pos.status == "closed":
            self._calculate_pnl(pos)

        self.log_event({
            "type": "straddle_exit",
            "ticker": ticker,
            "side": side,
            "exit_price": exit_price,
            "qty": qty,
            "status": pos.status,
            "pnl_cents": pos.pnl_cents,
            "observation": pos.observation,
        })

        self.save_state()
        return pos

    def close_at_expiry(self, ticker):
        """Mark a straddle as expired (held to settlement).

        For partial exits (one side sold, one held), we can't know the final
        P&L until settlement. We record:
          pnl_cents     = worst case (held side = $0)
          pnl_best_case = best case (held side wins = $1 each)
        The actual P&L depends on settlement_result, resolved later.
        """
        if ticker not in self.positions:
            return

        pos = self.positions[ticker]
        pos.status = "expired"
        pos.exit_time = datetime.now().isoformat()

        # Hedged pairs pay $1 guaranteed
        hedged = min(
            pos.contracts - pos.yes_sold,
            pos.contracts - pos.no_sold,
        )
        remaining_yes = pos.contracts - pos.yes_sold
        remaining_no = pos.contracts - pos.no_sold
        expiry_payout = hedged * 100  # $1 per hedged pair

        # Sell proceeds from sides already sold
        sell_proceeds = 0
        if pos.yes_exit_price and pos.yes_sold > 0:
            sell_proceeds += pos.yes_exit_price * pos.yes_sold
        if pos.no_exit_price and pos.no_sold > 0:
            sell_proceeds += pos.no_exit_price * pos.no_sold

        if hedged == 0 and (pos.yes_sold > 0 or pos.no_sold > 0):
            # Partial exit — one side sold, one held directionally
            # Worst case: held side = $0
            worst_pnl = sell_proceeds - pos.total_cost_cents
            # Best case: held side wins at $1 each
            held_count = remaining_yes + remaining_no
            best_pnl = worst_pnl + (held_count * 100)
            pos.pnl_cents = worst_pnl
            pos.pnl_best_case = best_pnl
        else:
            # Fully hedged (both sides held) or no sides sold
            pos.pnl_cents = sell_proceeds + expiry_payout - pos.total_cost_cents
            pos.pnl_best_case = None  # deterministic, no range

        self.log_event({
            "type": "straddle_expiry",
            "ticker": ticker,
            "hedged_contracts": hedged,
            "remaining_yes": remaining_yes,
            "remaining_no": remaining_no,
            "sell_proceeds": sell_proceeds,
            "expiry_payout_cents": expiry_payout,
            "pnl_worst": pos.pnl_cents,
            "pnl_best": pos.pnl_best_case,
            "observation": pos.observation,
        })

        # Move to history
        self._archive_position(pos)
        self.save_state()

    def _calculate_pnl(self, pos):
        """Calculate P&L for a fully closed straddle (both sides sold)."""
        sell_proceeds = 0
        if pos.yes_exit_price is not None:
            sell_proceeds += pos.yes_exit_price * pos.yes_sold
        if pos.no_exit_price is not None:
            sell_proceeds += pos.no_exit_price * pos.no_sold

        # Total cost = what we paid to enter both sides
        total_cost = pos.total_cost_cents

        # Fees: 0.7% on each trade (entry + exit = 4 legs)
        from config import KALSHI_FEE_RATE
        entry_fees = total_cost * KALSHI_FEE_RATE
        exit_fees = sell_proceeds * KALSHI_FEE_RATE
        total_fees = entry_fees + exit_fees

        pos.pnl_cents = int(round(sell_proceeds - total_cost - total_fees))

    def _archive_position(self, pos):
        """Move completed position to history log."""
        with open(HISTORY_LOG, "a") as f:
            f.write(json.dumps(pos.to_dict(), default=str) + "\n")
        # Remove from active positions
        if pos.ticker in self.positions:
            del self.positions[pos.ticker]

    def get_open_positions(self):
        """Return list of open/partial positions."""
        return [p for p in self.positions.values()
                if p.status in ("open", "partial_exit")]

    def get_daily_stats(self):
        """Return daily trading stats for risk limit checks."""
        # Reset if new day
        if self.last_reset_date != date.today().isoformat():
            self.daily_straddle_count = 0
            self.daily_exposure_cents = 0
            self.last_reset_date = date.today().isoformat()
            self.save_state()

        return {
            "daily_straddles": self.daily_straddle_count,
            "daily_exposure_cents": self.daily_exposure_cents,
            "open_positions": len(self.get_open_positions()),
        }

    def log_event(self, event):
        """Append an event to the JSONL log."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            **event,
        }
        with open(EVENT_LOG, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def get_history(self, limit=20):
        """Read recent completed straddles from history."""
        if not os.path.exists(HISTORY_LOG):
            return []
        entries = []
        with open(HISTORY_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries[-limit:]

    def print_status(self):
        """Print current status to console."""
        stats = self.get_daily_stats()
        print(f"\n{'='*55}")
        print(f"STRADDLE BOT STATUS")
        print(f"{'='*55}")
        print(f"  Daily straddles:  {stats['daily_straddles']}")
        print(f"  Daily exposure:   ${stats['daily_exposure_cents']/100:.2f}")
        print(f"  Open positions:   {stats['open_positions']}")

        open_pos = self.get_open_positions()
        if open_pos:
            print(f"\n  Open Straddles:")
            for pos in open_pos:
                obs = " [OBS]" if pos.observation else ""
                print(f"    {pos.ticker}{obs}")
                print(f"      Entry: YES@{pos.yes_entry_price}c + "
                      f"NO@{pos.no_entry_price}c = "
                      f"{pos.combined_entry_cents}c")
                print(f"      Contracts: {pos.contracts} | "
                      f"Status: {pos.status}")
                if pos.yes_sold:
                    print(f"      YES sold: {pos.yes_sold}@{pos.yes_exit_price}c")
                if pos.no_sold:
                    print(f"      NO sold: {pos.no_sold}@{pos.no_exit_price}c")
        else:
            print(f"\n  No open positions.")

        # Recent history
        history = self.get_history(5)
        if history:
            print(f"\n  Recent Completed:")
            for h in history[-5:]:
                pnl = h.get("pnl_cents", 0) or 0
                best = h.get("pnl_best_case")
                obs = " [OBS]" if h.get("observation") else ""
                settlement = h.get("settlement_result", "")
                if best is not None and settlement:
                    # We know the actual outcome
                    actual = best if settlement == _held_side(h) else pnl
                    sign = "+" if actual >= 0 else ""
                    print(f"    {h['ticker']}: {sign}{actual}c "
                          f"(settled {settlement}){obs}")
                elif best is not None:
                    # Range — settlement unknown
                    sign_w = "+" if pnl >= 0 else ""
                    sign_b = "+" if best >= 0 else ""
                    print(f"    {h['ticker']}: {sign_w}{pnl}c to "
                          f"{sign_b}{best}c (awaiting settlement){obs}")
                else:
                    sign = "+" if pnl >= 0 else ""
                    print(f"    {h['ticker']}: {sign}{pnl}c "
                          f"({h.get('status', '?')}){obs}")

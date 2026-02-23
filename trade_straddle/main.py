"""
Crypto Straddle Trading Bot for Kalshi 15-Min Markets.

Buys both YES and NO at market open, sells whichever side moves +5c.
Based on distinct-baguette's Polymarket strategy analysis.

Usage:
  python main.py straddle   # Run one cycle: enter → monitor → exit
  python main.py loop       # Continuous: scan all series, enter/exit in real time
  python main.py status     # Show open positions and daily stats
  python main.py history    # Show completed straddle history
"""

import sys
import pathlib
import time
from datetime import datetime

# Ensure imports work from any working directory
_BASE = pathlib.Path(__file__).parent
sys.path.insert(0, str(_BASE))
sys.path.insert(0, str(_BASE.parent / "trade_arbitrage"))


def cmd_straddle():
    """Run one straddle cycle: wait for quarter → enter → monitor → exit."""
    from straddle_executor import StraddleExecutor
    from config import OBSERVATION_MODE

    print(f"=== Crypto Straddle Bot ===")
    print(f"Mode: {'OBSERVATION' if OBSERVATION_MODE else '*** LIVE ***'}")
    print()

    executor = StraddleExecutor()

    # Wait for next quarter hour
    next_q = executor.wait_for_quarter_hour()
    print(f"  Quarter hour: {next_q.strftime('%H:%M:%S')} — scanning...")

    # Run the cycle
    pos = executor.run_single_cycle()

    if pos:
        print(f"\n  Cycle complete.")
    else:
        print(f"\n  No straddle executed this cycle.")


def cmd_loop():
    """Continuous mode: scan all series, enter/exit in real time."""
    from straddle_executor import StraddleExecutor
    from config import OBSERVATION_MODE

    print(f"=== Crypto Straddle Bot — CONTINUOUS MODE ===")
    print(f"Mode: {'OBSERVATION' if OBSERVATION_MODE else '*** LIVE ***'}")
    print(f"Press Ctrl+C to stop.\n")

    executor = StraddleExecutor()

    try:
        executor.run_continuous()
    except KeyboardInterrupt:
        print(f"\n\nStopped.")
        executor.tracker.print_status()


def cmd_status():
    """Show current positions and daily stats."""
    from position_tracker import PositionTracker
    tracker = PositionTracker()
    tracker.print_status()


def cmd_history():
    """Show completed straddle history."""
    from position_tracker import PositionTracker
    tracker = PositionTracker()

    history = tracker.get_history(limit=50)
    if not history:
        print("No completed straddles in history.")
        return

    print(f"\n{'='*60}")
    print(f"STRADDLE HISTORY ({len(history)} entries)")
    print(f"{'='*60}")

    total_pnl = 0
    winners = 0
    losers = 0

    for h in history:
        pnl = h.get("pnl_cents", 0) or 0
        total_pnl += pnl
        if pnl > 0:
            winners += 1
        elif pnl < 0:
            losers += 1

        sign = "+" if pnl >= 0 else ""
        obs = " [OBS]" if h.get("observation") else ""
        status = h.get("status", "?")
        entry = f"YES@{h.get('yes_entry_price', '?')}c + NO@{h.get('no_entry_price', '?')}c"

        print(f"\n  {h.get('ticker', '?')}{obs}")
        print(f"    Entry: {entry} | Status: {status}")
        if h.get("yes_exit_price"):
            print(f"    YES exit: {h.get('yes_sold', 0)}x @ {h['yes_exit_price']}c")
        if h.get("no_exit_price"):
            print(f"    NO exit:  {h.get('no_sold', 0)}x @ {h['no_exit_price']}c")
        print(f"    P&L: {sign}{pnl}c (${pnl/100:.2f})")

    print(f"\n{'='*60}")
    print(f"TOTALS")
    print(f"{'='*60}")
    total = winners + losers
    wr = (winners / total * 100) if total > 0 else 0
    sign = "+" if total_pnl >= 0 else ""
    print(f"  Straddles: {len(history)} | Winners: {winners} | Losers: {losers}")
    print(f"  Win rate: {wr:.1f}%")
    print(f"  Total P&L: {sign}{total_pnl}c (${total_pnl/100:.2f})")


COMMANDS = {
    "straddle": cmd_straddle,
    "loop": cmd_loop,
    "status": cmd_status,
    "history": cmd_history,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()

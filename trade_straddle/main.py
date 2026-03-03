"""
Crypto Trading Bot for Kalshi 15-Min Markets.

Strategies:
  1. Straddle (legacy): Buy both YES+NO at open, sell one side, hold other.
  2. Momentum (active):  At T=7min, buy the leading side (bid>=60c), hold to settlement.
     Direction-agnostic — 86% win rate on 203-market backtest.

Usage:
  python main.py loop       # Continuous: momentum entries + passive tick logging
  python main.py straddle   # Run one straddle cycle (legacy)
  python main.py status     # Show open positions and daily stats
  python main.py history    # Show completed trade history
  python main.py report     # Full P&L analysis with settlement tracking
  python main.py settle     # Check Kalshi API for settlement results
  python main.py pnl        # Quick rolling P&L by window (settles first)
  python main.py stats      # Analytics: per-series win rates, exit triggers, entry prices
  python main.py momentum   # Analyze passive tick data for momentum entry signals
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


def cmd_settle():
    """Check Kalshi API for settlement results on expired partial-exit straddles."""
    from straddle_executor import StraddleExecutor

    print(f"\n=== Checking Settlements ===\n")
    executor = StraddleExecutor()
    resolved = executor.check_settlements()

    if resolved:
        print(f"\n  Resolved {len(resolved)} straddles.")
    else:
        print(f"  No new settlements found.")


def cmd_report():
    """Full P&L analysis report with settlement tracking."""
    import json
    import os
    from position_tracker import PositionTracker
    from config import DATA_DIR

    tracker = PositionTracker()

    # Gather all positions: active (in state) + completed (in history)
    history_path = os.path.join(DATA_DIR, "straddle_history.jsonl")
    history = []
    if os.path.exists(history_path):
        with open(history_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        history.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    # Active positions from state
    active = [p.to_dict() for p in tracker.positions.values()]

    all_straddles = history + active
    if not all_straddles:
        print("No straddles to report.")
        return

    # Group by market window (date-aware, using ticker date)
    _MONTH_MAP = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12',
    }
    windows = {}
    for s in all_straddles:
        ticker = s.get("ticker", "")
        parts = ticker.split("-")
        if len(parts) >= 2:
            time_part = parts[1][-4:] if len(parts[1]) >= 4 else parts[1]
            # Parse ticker date (YYMMMDD) for correct midnight ordering
            ticker_date = parts[1][:-4] if len(parts[1]) > 4 else ""
            date_part = None
            if len(ticker_date) >= 7:
                yy, mmm, dd = ticker_date[:2], ticker_date[2:5], ticker_date[5:7]
                mm = _MONTH_MAP.get(mmm.upper())
                if mm:
                    date_part = f"20{yy}-{mm}-{dd}"
            if not date_part:
                date_part = s.get("entry_time", "")[:10]
            window_key = f"{date_part}:{time_part}" if date_part else time_part
        else:
            window_key = "unknown"
        if window_key not in windows:
            windows[window_key] = []
        windows[window_key].append(s)

    print(f"\n{'='*70}")
    print(f"  STRADDLE BOT — FULL P&L REPORT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    total_cost = 0
    total_pnl_worst = 0
    total_pnl_best = 0
    total_pnl_actual = 0
    has_actual = 0
    total_count = 0
    hit_count = 0
    settled_wins = 0
    settled_losses = 0

    prev_date = None
    for window_key in sorted(windows.keys()):
        straddles = windows[window_key]
        # Parse date:time from key (e.g. "2026-02-23:1315")
        if ":" in window_key:
            w_date, w_time = window_key.split(":", 1)
        else:
            w_date, w_time = "", window_key
        if w_date and w_date != prev_date:
            print(f"\n  {'='*50}")
            print(f"  {w_date}")
            print(f"  {'='*50}")
            prev_date = w_date
        print(f"\n  ── Window :{w_time} ({len(straddles)} straddles) ──")

        for s in straddles:
            total_count += 1
            ticker = s.get("ticker", "?")
            series = s.get("series", "?")
            status = s.get("status", "?")
            yes_entry = s.get("yes_entry_price", 0)
            no_entry = s.get("no_entry_price", 0)
            combined = yes_entry + no_entry
            contracts = s.get("contracts", 5)
            cost = combined * contracts
            total_cost += cost
            obs = " [OBS]" if s.get("observation") else ""

            # Determine what was sold
            yes_sold = s.get("yes_sold", 0)
            no_sold = s.get("no_sold", 0)
            yes_exit = s.get("yes_exit_price")
            no_exit = s.get("no_exit_price")

            # Did profit target trigger?
            if yes_sold > 0 or no_sold > 0:
                hit_count += 1

            # Build sold description
            if yes_sold > 0 and no_sold > 0:
                sold_desc = f"BOTH (Y@{yes_exit}c, N@{no_exit}c)"
            elif yes_sold > 0:
                pnl_side = (yes_exit or 0) - yes_entry
                sold_desc = f"YES@{yes_exit}c ({pnl_side:+d}c)"
            elif no_sold > 0:
                pnl_side = (no_exit or 0) - no_entry
                sold_desc = f"NO@{no_exit}c ({pnl_side:+d}c)"
            else:
                sold_desc = "(held both)"

            # P&L — compute range if missing (legacy data before pnl_best_case)
            pnl = s.get("pnl_cents", 0) or 0
            best = s.get("pnl_best_case")
            actual = s.get("pnl_actual")
            settlement = s.get("settlement_result")

            # Retroactively compute pnl range for partial exits missing pnl_best_case
            held_yes = contracts - yes_sold
            held_no = contracts - no_sold
            is_partial = (yes_sold > 0) != (no_sold > 0)  # exactly one side sold
            if best is None and is_partial and status in ("expired", "partial_exit"):
                # Compute sell proceeds
                sell_proc = 0
                if yes_exit and yes_sold > 0:
                    sell_proc += yes_exit * yes_sold
                if no_exit and no_sold > 0:
                    sell_proc += no_exit * no_sold
                worst = sell_proc - cost
                best = worst + (held_yes + held_no) * 100
                pnl = worst  # override the old buggy value

            if actual is not None:
                # Settled via API — we know actual P&L
                has_actual += 1
                total_pnl_actual += actual
                if actual >= 0:
                    settled_wins += 1
                else:
                    settled_losses += 1
                pnl_str = f"{actual:+d}c (settled {settlement})"
            elif best is not None:
                # Unsettled range (partial exit)
                pnl_str = f"{pnl:+d}c to {best:+d}c"
                total_pnl_worst += pnl
                total_pnl_best += best
            elif status == "closed":
                # Both sides sold — deterministic P&L
                pnl_str = f"{pnl:+d}c"
                total_pnl_worst += pnl
                total_pnl_best += pnl
                total_pnl_actual += pnl
                has_actual += 1
                if pnl >= 0:
                    settled_wins += 1
                else:
                    settled_losses += 1
            else:
                # Fully hedged to expiry — deterministic
                pnl_str = f"{pnl:+d}c"
                total_pnl_worst += pnl
                total_pnl_best += pnl
                total_pnl_actual += pnl
                has_actual += 1
                if pnl >= 0:
                    settled_wins += 1
                else:
                    settled_losses += 1

            # Short series name
            short = series.replace("KX", "").replace("15M", "") if series else "?"

            print(f"    {short:>4} Y@{yes_entry:<3}+N@{no_entry:<3}={combined}c "
                  f"| {sold_desc:<30} | {pnl_str:<25} {status}{obs}")

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    hit_rate = (hit_count / total_count * 100) if total_count > 0 else 0
    print(f"  Total straddles:   {total_count}")
    print(f"  Hit rate:          {hit_count}/{total_count} = {hit_rate:.0f}%")
    print(f"  Total entry cost:  {total_cost}c (${total_cost/100:.2f})")

    if has_actual > 0:
        print(f"\n  Settled straddles:  {has_actual}")
        print(f"    Winners: {settled_wins} | Losers: {settled_losses}")
        print(f"    Settled P&L:  {total_pnl_actual:+d}c (${total_pnl_actual/100:.2f})")

    unsettled = total_count - has_actual
    if unsettled > 0:
        print(f"\n  Unsettled straddles: {unsettled}")
        print(f"    P&L range: {total_pnl_worst:+d}c to {total_pnl_best:+d}c")
        print(f"    (${total_pnl_worst/100:.2f} to ${total_pnl_best/100:.2f})")

    combined_worst = total_pnl_actual + total_pnl_worst
    combined_best = total_pnl_actual + total_pnl_best
    print(f"\n  Overall P&L range: {combined_worst:+d}c to {combined_best:+d}c")
    print(f"  (${combined_worst/100:.2f} to ${combined_best/100:.2f})")
    print()


def cmd_pnl():
    """Quick rolling P&L by window — settles any unresolved markets first."""
    from straddle_executor import StraddleExecutor

    executor = StraddleExecutor()
    resolved = executor.check_settlements()
    if resolved:
        print(f"  Resolved {len(resolved)} new settlements.\n")
    executor.print_rolling_pnl()


def cmd_stats():
    """Analytics dashboard: per-series win rates, exit triggers, settlement bias."""
    from straddle_executor import StraddleExecutor

    executor = StraddleExecutor()
    resolved = executor.check_settlements()
    if resolved:
        print(f"  Resolved {len(resolved)} new settlements.\n")
    executor.print_stats()


def cmd_momentum():
    """Analyze passive tick data for momentum entry signals."""
    import json
    import os
    import glob
    from config import DATA_DIR

    HISTORY_LOG = os.path.join(DATA_DIR, "straddle_history.jsonl")

    # Load settlement results
    settled = {}
    if os.path.exists(HISTORY_LOG):
        with open(HISTORY_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        e = json.loads(line)
                        if e.get("settlement_result") in ("yes", "no"):
                            settled[e["ticker"]] = e["settlement_result"]
                    except json.JSONDecodeError:
                        pass

    # Load passive tick files
    tick_files = glob.glob(os.path.join(DATA_DIR, "passive_ticks_*.jsonl"))
    if not tick_files:
        print("No passive tick data found. Run the bot with PASSIVE_TICK_LOGGING=True first.")
        return

    # Build per-ticker timelines
    tickers = {}  # ticker -> list of ticks
    for tf in tick_files:
        ticker = os.path.basename(tf).replace("passive_ticks_", "").replace(".jsonl", "")
        ticks = []
        with open(tf) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        ticks.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        if ticks:
            tickers[ticker] = ticks

    print(f"\n{'='*70}")
    print(f"  MOMENTUM ANALYSIS — Passive Tick Data")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    print(f"  Passive tick files: {len(tick_files)}")
    print(f"  Tickers with data:  {len(tickers)}")
    print(f"  Settled tickers:    {len(settled)}")

    # Filter to tickers with settlement AND tick data
    analyzable = {t: ticks for t, ticks in tickers.items() if t in settled}
    print(f"  Analyzable (both):  {len(analyzable)}")

    if not analyzable:
        # Show data collection progress
        total_ticks = sum(len(t) for t in tickers.values())
        print(f"\n  Total passive ticks collected: {total_ticks}")
        if tickers:
            sample_ticker = list(tickers.keys())[0]
            sample_ticks = tickers[sample_ticker]
            elapsed_range = [t.get("elapsed_s") for t in sample_ticks if t.get("elapsed_s") is not None]
            if elapsed_range:
                print(f"  Sample: {sample_ticker}")
                print(f"    Ticks: {len(sample_ticks)}")
                print(f"    Elapsed: {min(elapsed_range):.0f}s to {max(elapsed_range):.0f}s")
        print(f"\n  Waiting for markets to settle. Check back after markets expire.")
        return

    # === Momentum signal analysis ===
    print(f"\n  {'='*60}")
    print(f"  MOMENTUM: Buy leader when bid >= threshold at time T")
    print(f"  {'='*60}")
    print(f"\n  {'T(s)':>5} | {'Bid>=':>5} | {'Trades':>6} | {'Win%':>5} | "
          f"{'AvgAsk':>6} | {'Margin':>6} | {'$/trade':>8} | {'Total P&L':>10}")
    print(f"  {'─'*70}")

    combos = []
    for time_point in [15, 30, 45, 60, 90, 120, 180, 240, 300, 360, 420, 480, 540, 600, 720, 840]:
        for thresh in [55, 58, 60, 62, 65, 68, 70, 75, 80]:
            trades = []
            for ticker, ticks in analyzable.items():
                sr = settled[ticker]
                # Find tick closest to time_point
                best_tick = None
                best_diff = 999
                for t in ticks:
                    es = t.get("elapsed_s")
                    if es is None:
                        continue
                    diff = abs(es - time_point)
                    if diff < best_diff:
                        best_diff = diff
                        best_tick = t
                if best_tick is None or best_diff > 10:
                    continue

                yb = best_tick.get("yes_bid", 0)
                nb = best_tick.get("no_bid", 0)

                if yb >= thresh:
                    ask = best_tick.get("yes_ask", 100 - nb)
                    won = (sr == "yes")
                    pnl = (100 - ask) * 5 if won else -ask * 5
                    trades.append((pnl, won, ask))
                elif nb >= thresh:
                    ask = best_tick.get("no_ask", 100 - yb)
                    won = (sr == "no")
                    pnl = (100 - ask) * 5 if won else -ask * 5
                    trades.append((pnl, won, ask))

            if len(trades) < 5:
                continue

            wins = sum(1 for _, w, _ in trades if w)
            total_pnl = sum(p for p, _, _ in trades)
            wr = wins / len(trades) * 100
            avg_ask = sum(a for _, _, a in trades) / len(trades)
            avg_pnl = total_pnl / len(trades)
            combos.append((total_pnl, time_point, thresh, len(trades), wr, avg_ask, avg_pnl))

    # Sort by total P&L and show top 20
    combos.sort(key=lambda x: -x[0])
    for pnl, tp, th, n, wr, aa, ap in combos[:20]:
        print(f"  {tp:5d} | {th:5d}c | {n:6d} | {wr:4.0f}% | "
              f"{aa:5.0f}c | {100-aa:5.0f}c | {ap:+7.1f}c | "
              f"{pnl:+8d}c (${pnl/100:+.2f})")

    # Data coverage summary
    print(f"\n  {'='*60}")
    print(f"  DATA COVERAGE")
    print(f"  {'='*60}")
    for tp in [30, 60, 120, 180, 300, 450, 600, 750, 900]:
        count = 0
        for ticker, ticks in analyzable.items():
            has = any(abs(t.get("elapsed_s", 0) - tp) < 10 for t in ticks)
            if has:
                count += 1
        print(f"    T={tp:3d}s ({tp/60:4.1f}min): {count:3d} / {len(analyzable)} tickers with data")

    print()


COMMANDS = {
    "straddle": cmd_straddle,
    "loop": cmd_loop,
    "status": cmd_status,
    "history": cmd_history,
    "report": cmd_report,
    "settle": cmd_settle,
    "pnl": cmd_pnl,
    "stats": cmd_stats,
    "momentum": cmd_momentum,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()

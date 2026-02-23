"""
Main Orchestrator - Polymarket Intelligence → Kalshi Execution

This is the main entry point that ties together:
1. Polymarket trade data fetching (fetch_trades.py)
2. Pattern analysis (analyze_patterns.py)
3. Account monitoring (monitor.py)
4. Kalshi execution (kalshi_executor.py)

Usage:
  python main.py fetch      # Pull all historical trade data
  python main.py analyze    # Run pattern analysis on fetched data
  python main.py monitor    # Start live monitoring for new trades
  python main.py scan       # Scan Kalshi for current opportunities
  python main.py run        # Full pipeline: fetch → analyze → scan
  python main.py live       # Monitor + auto-execute on Kalshi (USE WITH CAUTION)
"""

import sys
import json
import os
import time
from datetime import datetime

DATA_DIR = "data"
ANALYSIS_DIR = "analysis"


def cmd_fetch():
    """Fetch all historical trade data."""
    print("=" * 60)
    print("STEP 1: Fetching Polymarket Trade Data")
    print("=" * 60)
    from fetch_trades import (
        WALLET_ADDRESS, fetch_all_trades, fetch_all_activity,
        fetch_positions, fetch_all_closed_positions, save_json
    )

    trades = fetch_all_trades(WALLET_ADDRESS)
    save_json(trades, "trades_raw.json")

    activity = fetch_all_activity(WALLET_ADDRESS)
    save_json(activity, "activity_raw.json")

    try:
        positions = fetch_positions(WALLET_ADDRESS)
        save_json(positions, "positions_raw.json")
    except Exception as e:
        print(f"  Positions error: {e}")

    closed = fetch_all_closed_positions(WALLET_ADDRESS)
    save_json(closed, "closed_positions_raw.json")

    print(f"\nFetched {len(trades)} trades, {len(activity)} activities, {len(closed)} closed positions")
    return trades


def cmd_analyze():
    """Run pattern analysis."""
    print("\n" + "=" * 60)
    print("STEP 2: Analyzing Trading Patterns")
    print("=" * 60)
    from analyze_patterns import load_json, analyze_trades, generate_strategy_profile

    trades = load_json("trades_raw.json")
    if not trades:
        print("No trade data found. Run 'python main.py fetch' first.")
        return None

    analysis = analyze_trades(trades)
    profile = generate_strategy_profile(analysis)
    analysis["strategy_profile"] = profile

    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    with open(os.path.join(ANALYSIS_DIR, "pattern_analysis.json"), "w") as f:
        json.dump(analysis, f, indent=2, default=str)

    # Print summary
    print(f"\nStrategy Type: {profile['strategy_type']}")
    print(f"Confidence: {profile['confidence']}")
    print(f"\nKey Parameters:")
    for k, v in profile.get("key_parameters", {}).items():
        print(f"  {k}: {v}")

    print(f"\nKalshi Recommendations:")
    for r in profile.get("recommendations_for_kalshi", []):
        print(f"  → {r}")

    return analysis


def cmd_scan():
    """Scan Kalshi for current opportunities."""
    print("\n" + "=" * 60)
    print("STEP 3: Scanning Kalshi Markets")
    print("=" * 60)
    from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)

    report = executor.scan_and_report()
    print(f"\nFound {report['total_opportunities']} opportunities")

    for i, opp in enumerate(report.get("top_opportunities", [])[:5]):
        print(f"\n  {i+1}. {opp['title']}")
        print(f"     YES: {opp['yes_price_cents']}c | NO: {opp['no_price_cents']}c | Spread: {opp['spread']}")

    return report


def cmd_monitor():
    """Start live monitoring."""
    print("\n" + "=" * 60)
    print("MONITORING: distinct-baguette (Ctrl+C to stop)")
    print("=" * 60)
    from monitor import TradeMonitor, log_trade

    monitor = TradeMonitor("0xe00740bce98a594e26861838885ab310ec3b548c")
    monitor.on_new_trade(log_trade)

    check_count = 0
    while True:
        check_count += 1
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] Check #{check_count}...", end="")

        new = monitor.check_for_new_trades()
        if new:
            print(f" {len(new)} new trades!")
            shifts = monitor.detect_strategy_shift()
            if shifts:
                print(f"  *** STRATEGY SHIFT: {shifts}")
        else:
            print(" no new trades")

        time.sleep(60)


def cmd_run():
    """Full pipeline: fetch → analyze → scan."""
    cmd_fetch()
    analysis = cmd_analyze()
    try:
        cmd_scan()
    except Exception as e:
        print(f"\nKalshi scan failed (may need local network): {e}")

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\nOutput files:")
    print(f"  {DATA_DIR}/trades_raw.json       - Raw trade history")
    print(f"  {DATA_DIR}/activity_raw.json      - Full activity log")
    print(f"  {DATA_DIR}/positions_raw.json     - Current positions")
    print(f"  {ANALYSIS_DIR}/pattern_analysis.json - Strategy analysis")
    print(f"  {DATA_DIR}/kalshi_opportunities.json - Kalshi scan results")
    print(f"\nNext steps:")
    print(f"  1. Review the analysis in {ANALYSIS_DIR}/pattern_analysis.json")
    print(f"  2. Set up Kalshi API keys (see kalshi_executor.py)")
    print(f"  3. Run 'python main.py monitor' to track live changes")
    print(f"  4. When ready: 'python main.py live' for auto-execution")


def cmd_live():
    """Monitor + auto-execute. USE WITH CAUTION."""
    print("\n" + "=" * 60)
    print("LIVE MODE: Monitor + Auto-Execute on Kalshi")
    print("=" * 60)
    print("\n⚠️  This will place REAL TRADES on Kalshi.")
    print("Make sure USE_DEMO = True in kalshi_executor.py for testing.\n")

    confirm = input("Type 'confirm' to proceed: ")
    if confirm.lower() != "confirm":
        print("Aborted.")
        return

    from monitor import TradeMonitor
    from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
    from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, USE_DEMO

    print(f"\nMode: {'DEMO' if USE_DEMO else '*** LIVE ***'}")

    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)
    executor = StrategyExecutor(client)
    monitor = TradeMonitor("0xe00740bce98a594e26861838885ab310ec3b548c")

    def on_trade(trade):
        """Handle new trade from distinct-baguette."""
        title = trade.get("title", "")
        side = trade.get("side", "")
        price = trade.get("price", 0)
        outcome = trade.get("outcome", "")

        print(f"\n  Signal: {side} {outcome} on '{title}' @ {price}")

        # Try to find matching Kalshi market
        search_terms = title.split()[:4]  # First 4 words
        query = " ".join(search_terms)

        try:
            matches = client.search_markets(query)
            if matches:
                best = matches[0]
                print(f"  Kalshi match: {best['title']} ({best['ticker']})")

                # TODO: Add more sophisticated matching and execution logic
                # For now, just log the opportunity
                opp_log = os.path.join(DATA_DIR, "live_signals.jsonl")
                with open(opp_log, "a") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now().isoformat(),
                        "polymarket_signal": {
                            "title": title, "side": side,
                            "price": price, "outcome": outcome,
                        },
                        "kalshi_match": {
                            "title": best["title"],
                            "ticker": best["ticker"],
                            "yes_price": best.get("yes_price"),
                        },
                    }, default=str) + "\n")
                print(f"  Logged to {opp_log}")
            else:
                print(f"  No Kalshi match found for: {query}")
        except Exception as e:
            print(f"  Error finding match: {e}")

    monitor.on_new_trade(on_trade)

    # Also periodically scan for arb opportunities
    scan_interval = 300  # 5 min
    last_scan = 0

    while True:
        now = time.time()
        ts = datetime.now().strftime("%H:%M:%S")

        # Check for new Polymarket trades
        new = monitor.check_for_new_trades()
        if new:
            print(f"[{ts}] {len(new)} new signal(s)")
        else:
            print(f"[{ts}] monitoring...", end="\r")

        # Periodic arb scan on Kalshi
        if now - last_scan > scan_interval:
            try:
                opps = executor.find_arb_opportunities()
                if opps:
                    print(f"\n[{ts}] Found {len(opps)} Kalshi arb opportunities")
                    for o in opps[:3]:
                        print(f"  {o['ticker']}: spread={o['spread']}")
                last_scan = now
            except Exception:
                pass

        time.sleep(30)


COMMANDS = {
    "fetch": cmd_fetch,
    "analyze": cmd_analyze,
    "scan": cmd_scan,
    "monitor": cmd_monitor,
    "run": cmd_run,
    "live": cmd_live,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()

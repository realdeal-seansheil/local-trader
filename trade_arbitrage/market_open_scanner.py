"""
Market-Open Arbitrage Scanner for Kalshi Crypto 15-Min Markets

Kalshi's crypto 15-min binary markets (BTC, ETH, SOL, XRP) open new
contracts every 15 minutes. At market open, the orderbook is thin and
mispricings are most likely — YES + NO may briefly sum to < $1.00.

This scanner:
1. Sleeps until ~5 seconds before the next quarter hour
2. Aggressively polls all 4 crypto series' orderbooks for 120 seconds
3. Logs every snapshot: prices, spreads, depth, timestamps
4. Identifies arb opportunities (combined < $1.00 after fees)
5. In observation mode: logs but does NOT execute

Timing: quarter hours are :00, :15, :30, :45 past the hour.

Run:  python market_open_scanner.py
Or:   python main.py openscan
"""

import time
import json
import os
import pathlib
from datetime import datetime, timedelta
from collections import defaultdict

# Import from sibling modules
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from kalshi_executor import (
    KalshiAuth, KalshiClient, StrategyExecutor,
    KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH,
    OBSERVATION_MODE, calculate_arb_profitability,
    MIN_SPREAD_FOR_ARB, DATA_DIR,
)

# ============================================================
# SCANNER CONFIGURATION
# ============================================================

# Kalshi crypto 15-min series tickers
CRYPTO_SERIES = [
    "KXBTC15M",   # Bitcoin
    "KXETH15M",   # Ethereum
    "KXSOL15M",   # Solana
    "KXXRP15M",   # XRP
]

# Timing
SCAN_WINDOW_BEFORE_OPEN = 5      # Start scanning N seconds before quarter hour
SCAN_WINDOW_AFTER_OPEN = 120     # Keep scanning for N seconds after quarter hour
SCAN_INTERVAL_FAST = 2           # Poll every N seconds during hot window
SCAN_INTERVAL_IDLE = 30          # Poll every N seconds outside hot window
CONTINUOUS_MODE = True           # Keep running across multiple quarter hours

# Logging
SCAN_LOG_DIR = os.path.join(DATA_DIR, "market_open_scans")
os.makedirs(SCAN_LOG_DIR, exist_ok=True)


def next_quarter_hour():
    """Calculate the next quarter hour mark (XX:00, XX:15, XX:30, XX:45)."""
    now = datetime.now()
    minute = now.minute
    # Next quarter: round up to nearest 15
    next_q_minute = ((minute // 15) + 1) * 15
    if next_q_minute >= 60:
        next_q = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        next_q = now.replace(minute=next_q_minute, second=0, microsecond=0)
    return next_q


def seconds_until(target):
    """Seconds from now until target datetime."""
    delta = (target - datetime.now()).total_seconds()
    return max(0, delta)


def format_orderbook_summary(orderbook_data):
    """
    Extract key metrics from a Kalshi orderbook response.

    Kalshi orderbooks have:
      orderbook.yes = [[price_cents, quantity], ...]  — bids to BUY YES
      orderbook.no  = [[price_cents, quantity], ...]  — bids to BUY NO

    CRITICAL: On Kalshi, the orderbook only shows bids (buy orders).
    To TAKE liquidity (buy at the ask), the implied prices are:
      YES ask = 100 - max_no_bid   (buying YES = selling NO to someone)
      NO ask  = 100 - max_yes_bid  (buying NO = selling YES to someone)

    For an arb: combined_ask = yes_ask + no_ask < 100c means profit.
    Equivalently: max_yes_bid + max_no_bid > 100 means arb exists.
    """
    ob = orderbook_data.get("orderbook", {})
    yes_bids = ob.get("yes", [])
    no_bids = ob.get("no", [])

    # Sort by price descending to find the highest bid
    yes_sorted = sorted(yes_bids, key=lambda x: x[0], reverse=True)
    no_sorted = sorted(no_bids, key=lambda x: x[0], reverse=True)

    summary = {
        "yes_bid_levels": len(yes_bids),
        "no_bid_levels": len(no_bids),
        # Highest bids (best prices for someone selling to these bidders)
        "yes_max_bid": None,
        "yes_max_bid_qty": None,
        "no_max_bid": None,
        "no_max_bid_qty": None,
        # Implied ask prices (cost to take liquidity)
        "yes_ask": None,
        "no_ask": None,
        # Depth
        "yes_total_depth": 0,
        "no_total_depth": 0,
        # Combined cost and spread (ask-based)
        "combined_ask": None,
        "spread": None,
        # Top bids for logging
        "yes_top_bids": [],
        "no_top_bids": [],
    }

    if yes_sorted:
        summary["yes_max_bid"] = yes_sorted[0][0]
        summary["yes_max_bid_qty"] = yes_sorted[0][1]
        summary["yes_total_depth"] = sum(level[1] for level in yes_bids)
        summary["yes_top_bids"] = yes_sorted[:5]

    if no_sorted:
        summary["no_max_bid"] = no_sorted[0][0]
        summary["no_max_bid_qty"] = no_sorted[0][1]
        summary["no_total_depth"] = sum(level[1] for level in no_bids)
        summary["no_top_bids"] = no_sorted[:5]

    # Derive implied ask prices
    if summary["yes_max_bid"] is not None:
        summary["no_ask"] = 100 - summary["yes_max_bid"]
    if summary["no_max_bid"] is not None:
        summary["yes_ask"] = 100 - summary["no_max_bid"]

    # Combined ask cost and spread
    if summary["yes_ask"] is not None and summary["no_ask"] is not None:
        combined = summary["yes_ask"] + summary["no_ask"]
        summary["combined_ask"] = combined  # in cents
        # Positive spread = arb exists (combined < 100c)
        summary["spread"] = round((100 - combined) / 100.0, 4)

    return summary


class MarketOpenScanner:
    """
    Aggressively scans Kalshi crypto 15-min markets at quarter-hour opens
    to detect fleeting arbitrage opportunities.
    """

    def __init__(self, client: KalshiClient):
        self.client = client
        self.scan_count = 0
        self.opportunities_found = 0
        self.session_start = datetime.now()

        # Per-session log file
        ts = self.session_start.strftime("%Y%m%d_%H%M%S")
        self.session_log = os.path.join(SCAN_LOG_DIR, f"scan_session_{ts}.jsonl")
        self.opportunity_log = os.path.join(SCAN_LOG_DIR, f"opportunities_{ts}.jsonl")

        # Aggregate stats
        self.spread_history = defaultdict(list)  # series -> [spread values]

    def find_open_markets_for_series(self, series_ticker):
        """
        Find all currently open markets for a given series.
        Returns list of market dicts.
        """
        try:
            result = self.client.get_markets(
                status="open",
                limit=50,
                series_ticker=series_ticker,
            )
            return result.get("markets", [])
        except Exception as e:
            print(f"    Error fetching {series_ticker}: {e}")
            return []

    def scan_orderbook(self, ticker):
        """
        Pull full orderbook for a market ticker.
        Returns (orderbook_raw, summary) or (None, None) on error.
        """
        try:
            ob = self.client.get_orderbook(ticker)
            summary = format_orderbook_summary(ob)
            return ob, summary
        except Exception as e:
            return None, {"error": str(e)}

    def scan_all_series(self):
        """
        Scan all crypto series, pull orderbooks for each open market,
        and log everything.

        Uses correct ask-side pricing:
          YES ask = 100 - max_no_bid
          NO ask  = 100 - max_yes_bid
          Arb exists when yes_ask + no_ask < 100c

        Returns list of arb opportunities found.
        """
        self.scan_count += 1
        scan_time = datetime.now()
        opportunities = []

        for series in CRYPTO_SERIES:
            markets = self.find_open_markets_for_series(series)

            for market in markets:
                ticker = market.get("ticker", "")
                title = market.get("title", "")

                # Get detailed orderbook
                ob_raw, ob_summary = self.scan_orderbook(ticker)

                # Build scan entry
                entry = {
                    "timestamp": scan_time.isoformat(),
                    "scan_number": self.scan_count,
                    "series": series,
                    "ticker": ticker,
                    "title": title,
                    "orderbook": ob_summary,
                }

                # Check for arb opportunity using ask-side pricing
                combined_ask = ob_summary.get("combined_ask")  # in cents
                spread = ob_summary.get("spread")  # in dollars, positive = arb

                if combined_ask is not None and spread is not None:
                    self.spread_history[series].append(spread)

                    yes_ask = ob_summary["yes_ask"]
                    no_ask = ob_summary["no_ask"]

                    if spread > MIN_SPREAD_FOR_ARB:
                        # Calculate fee-aware profitability using ask prices
                        prof = calculate_arb_profitability(yes_ask, no_ask, count=1)

                        entry["arb_opportunity"] = True
                        entry["profitability"] = prof

                        if prof["profitable_after_fees"]:
                            # Real opportunity!
                            self.opportunities_found += 1
                            opp = {
                                "timestamp": scan_time.isoformat(),
                                "ticker": ticker,
                                "title": title,
                                "series": series,
                                "yes_ask_cents": yes_ask,
                                "no_ask_cents": no_ask,
                                "combined_ask_cents": combined_ask,
                                "spread": spread,
                                "yes_max_bid": ob_summary["yes_max_bid"],
                                "no_max_bid": ob_summary["no_max_bid"],
                                "yes_max_bid_qty": ob_summary["yes_max_bid_qty"],
                                "no_max_bid_qty": ob_summary["no_max_bid_qty"],
                                "net_profit_per_contract": prof["net_profit_per_contract"],
                                "roi_net_percent": prof["roi_net_percent"],
                                "profitable_after_fees": True,
                                "observation_mode": OBSERVATION_MODE,
                            }
                            opportunities.append(opp)

                            # Log opportunity separately
                            with open(self.opportunity_log, "a") as f:
                                f.write(json.dumps(opp, default=str) + "\n")

                            spread_cents = round(spread * 100, 1)
                            print(f"\n    *** ARB OPPORTUNITY ***")
                            print(f"    {title} ({ticker})")
                            print(f"    YES ask: {yes_ask}c | NO ask: {no_ask}c | Combined: {combined_ask}c")
                            print(f"    Spread: {spread_cents}c | Net profit/contract: ${prof['net_profit_per_contract']:.4f}")
                            print(f"    Bids: YES@{ob_summary['yes_max_bid']}c x{ob_summary['yes_max_bid_qty']} | "
                                  f"NO@{ob_summary['no_max_bid']}c x{ob_summary['no_max_bid_qty']}")
                            if OBSERVATION_MODE:
                                print(f"    [OBSERVATION MODE — not executing]")
                    else:
                        entry["arb_opportunity"] = False
                        # Log the spread even when no arb (useful for analysis)
                        entry["spread_cents"] = round(spread * 100, 1) if spread else None

                # Log every scan entry
                with open(self.session_log, "a") as f:
                    f.write(json.dumps(entry, default=str) + "\n")

        return opportunities

    def run_hot_window(self, quarter_time):
        """
        Run aggressive scanning during the market-open hot window.
        Scans every SCAN_INTERVAL_FAST seconds for SCAN_WINDOW_AFTER_OPEN seconds.
        """
        window_end = quarter_time + timedelta(seconds=SCAN_WINDOW_AFTER_OPEN)
        scan_round = 0

        print(f"\n{'='*60}")
        print(f"HOT WINDOW: {quarter_time.strftime('%H:%M:%S')} — scanning for {SCAN_WINDOW_AFTER_OPEN}s")
        print(f"{'='*60}")

        while datetime.now() < window_end:
            scan_round += 1
            elapsed = (datetime.now() - quarter_time).total_seconds()
            print(f"\n  [+{elapsed:.0f}s] Scan round #{scan_round}...", end="")

            opps = self.scan_all_series()
            if opps:
                print(f" — {len(opps)} opportunity(ies)!")
            else:
                print(f" — no arb (scanned {len(CRYPTO_SERIES)} series)")

            # Sleep between scans (but not past window end)
            remaining = (window_end - datetime.now()).total_seconds()
            sleep_time = min(SCAN_INTERVAL_FAST, max(0, remaining))
            if sleep_time > 0:
                time.sleep(sleep_time)

        # Count opportunities with positive spread (arb exists)
        arb_count = sum(1 for s in self.spread_history.values() for sp in s if sp > MIN_SPREAD_FOR_ARB)
        print(f"\n  Hot window closed. Arb opps detected: {arb_count}")

    def print_session_stats(self):
        """Print running session statistics."""
        elapsed = (datetime.now() - self.session_start).total_seconds()
        print(f"\n{'='*60}")
        print(f"SESSION STATS (running {elapsed/60:.1f} minutes)")
        print(f"{'='*60}")
        print(f"  Total scans:          {self.scan_count}")
        print(f"  Opportunities found:  {self.opportunities_found}")
        print(f"  Session log:          {self.session_log}")
        print(f"  Opportunity log:      {self.opportunity_log}")

        for series, spreads in self.spread_history.items():
            if spreads:
                avg_spread = sum(spreads) / len(spreads)
                max_spread = max(spreads)
                min_spread = min(spreads)
                arb_opps = sum(1 for s in spreads if s > MIN_SPREAD_FOR_ARB)
                print(f"\n  {series}:")
                print(f"    Snapshots: {len(spreads)}")
                print(f"    Spread (ask-based): avg={avg_spread*100:.1f}c | max={max_spread*100:.1f}c | min={min_spread*100:.1f}c")
                print(f"    Arb opportunities (>{MIN_SPREAD_FOR_ARB*100:.0f}c spread): {arb_opps}/{len(spreads)}")

    def run(self):
        """
        Main loop: sleep until quarter hour, run hot window, repeat.
        """
        print(f"=== Market-Open Arbitrage Scanner ===")
        print(f"Mode: {'OBSERVATION' if OBSERVATION_MODE else '*** LIVE EXECUTION ***'}")
        print(f"Series: {', '.join(CRYPTO_SERIES)}")
        print(f"Scan window: {SCAN_WINDOW_BEFORE_OPEN}s before → {SCAN_WINDOW_AFTER_OPEN}s after open")
        print(f"Fast scan interval: {SCAN_INTERVAL_FAST}s")
        print(f"Session log: {self.session_log}")
        print()

        try:
            while True:
                next_q = next_quarter_hour()
                wait_until = next_q - timedelta(seconds=SCAN_WINDOW_BEFORE_OPEN)
                wait_secs = seconds_until(wait_until)

                if wait_secs > 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Next quarter: "
                          f"{next_q.strftime('%H:%M:%S')} — sleeping {wait_secs:.0f}s...")

                    # Do an idle scan while waiting (to establish baseline)
                    if wait_secs > SCAN_INTERVAL_IDLE:
                        print(f"  Running baseline scan while waiting...")
                        self.scan_all_series()
                        remaining = seconds_until(wait_until)
                        if remaining > 0:
                            time.sleep(remaining)
                    else:
                        time.sleep(wait_secs)

                # Run the hot window
                self.run_hot_window(next_q)

                # Print stats after each window
                self.print_session_stats()

                if not CONTINUOUS_MODE:
                    break

        except KeyboardInterrupt:
            print("\n\nScanner stopped by user.")
            self.print_session_stats()


if __name__ == "__main__":
    print(f"Initializing Kalshi connection...")
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)

    scanner = MarketOpenScanner(client)
    scanner.run()

"""
Maker Observer — Entry Point
Runs the favorite-bias observation strategy alongside the momentum bot.

Usage:
    python -m trade_maker.main

Scans all Kalshi markets for favorite-longshot bias opportunities,
logs hypothetical trades, and tracks virtual P&L. No orders placed.
"""

import sys
import os

# Add project root to path so we can import from trade_arbitrage
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_arbitrage.kalshi_executor import KalshiClient, KalshiAuth, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from trade_maker.maker_executor import MakerExecutor


def main():
    print("\n  Initializing Kalshi API client...")
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)

    # Verify connection
    try:
        balance = client.get_balance()
        print(f"  Connected. Balance: ${balance.get('balance', 0) / 100:.2f}")
    except Exception as e:
        print(f"  Warning: Could not fetch balance: {e}")
        print(f"  Continuing anyway (observation mode only needs read-only access)...")

    # Quick market scan test
    try:
        test = client.get_markets(status="open", limit=5)
        count = len(test.get("markets", []))
        print(f"  API test: found {count} markets (sample)")
    except Exception as e:
        print(f"  ERROR: Cannot reach Kalshi API: {e}")
        sys.exit(1)

    executor = MakerExecutor(client)
    executor.run_continuous()


if __name__ == "__main__":
    main()

"""
Underdog Bot — Entry Point
Smaller positions on longer-shot wins using maker orders on 15-min crypto markets.

Usage:
    python -m trade_underdog.main
"""

import sys
import os

# Add project root to path so we can import from trade_arbitrage
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_arbitrage.kalshi_executor import KalshiClient, KalshiAuth, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from trade_underdog.underdog_executor import UnderdogExecutor


def main():
    print("\n  Initializing Kalshi API client for underdog bot...")
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)

    # Verify connection
    try:
        balance = client.get_balance()
        print(f"  Connected. Balance: ${balance.get('balance', 0) / 100:.2f}")
    except Exception as e:
        print(f"  Warning: Could not fetch balance: {e}")
        print(f"  Continuing anyway (observation mode only needs read-only access)...")

    # Quick test: verify we can fetch a crypto series
    try:
        test = client.get_markets(status="open", limit=1, series_ticker="KXBTC15M")
        count = len(test.get("markets", []))
        print(f"  API test: KXBTC15M has {count} open market(s)")
    except Exception as e:
        print(f"  ERROR: Cannot reach Kalshi API: {e}")
        sys.exit(1)

    executor = UnderdogExecutor(client)
    executor.run_continuous()


if __name__ == "__main__":
    main()

"""
Kelly Bot — Entry Point
Underdog strategy clone with Kelly criterion position sizing.

Usage:
    python -m trade_fade.main
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_arbitrage.kalshi_executor import KalshiClient, KalshiAuth, KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from trade_fade.fade_executor import FadeExecutor


def main():
    print("\n  Initializing Kalshi API client for Kelly bot...")
    auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
    client = KalshiClient(auth)

    # Verify connection
    try:
        balance = client.get_balance()
        print(f"  Connected. Balance: ${balance.get('balance', 0) / 100:.2f}")
    except Exception as e:
        print(f"  Warning: Could not fetch balance: {e}")
        print(f"  Continuing anyway (observation mode only needs read-only access)...")

    # Quick API test
    try:
        test = client.get_markets(status="open", limit=1, series_ticker="KXBTC15M")
        count = len(test.get("markets", []))
        print(f"  API test: KXBTC15M has {count} open market(s)")
    except Exception as e:
        print(f"  ERROR: Cannot reach Kalshi API: {e}")
        sys.exit(1)

    executor = FadeExecutor(client)
    executor.run_continuous()


if __name__ == "__main__":
    main()

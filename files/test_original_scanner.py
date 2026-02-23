#!/usr/bin/env python3
"""
Test the original working scanner
"""

from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
client = KalshiClient(auth)
executor = StrategyExecutor(client)

print('🔍 Testing ORIGINAL working scanner...')
opportunities = executor.find_arb_opportunities()

print(f'📊 Original scanner found: {len(opportunities) if opportunities else 0} opportunities')

if opportunities:
    print(f'🎉 Original scanner SUCCESS:')
    for i, opp in enumerate(opportunities[:3]):
        print(f'   {i+1}. {opp.get("ticker", "Unknown")}')
        print(f'      Spread: {opp.get("spread", 0)}')
        print(f'      Net profit: ${opp.get("net_profit_per_contract", 0):.4f}')
        print(f'      YES price: {opp.get("yes_price_cents", 0)}')
        print(f'      NO price: {opp.get("no_price_cents", 0)}')
else:
    print(f'❌ Original scanner found nothing')

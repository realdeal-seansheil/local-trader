#!/usr/bin/env python3
"""
Debug the scanner to see what's wrong
"""

from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
client = KalshiClient(auth)
executor = StrategyExecutor(client)

print('🔍 Testing the original working scanner...')
opportunities = executor.find_arb_opportunities()

print(f'📊 Found {len(opportunities) if opportunities else 0} opportunities')

if opportunities:
    print(f'🎉 SUCCESS! Found opportunities:')
    for i, opp in enumerate(opportunities[:3]):
        print(f'   {i+1}. {opp.get("ticker", "Unknown")}')
        print(f'      Spread: {opp.get("spread", 0)}')
        print(f'      Net profit: ${opp.get("net_profit_per_contract", 0):.4f}')
else:
    print(f'❌ No opportunities found')
    print(f'🔍 Let me debug the scanner...')
    
    # Debug the scanner step by step
    print(f'\n📊 Debugging the scanner...')
    result = client.get_markets(status="open", limit=50)
    markets = result.get("markets", [])
    print(f'📊 Total markets: {len(markets)}')
    
    # Check what the scanner is looking for
    valid_markets = 0
    for market in markets[:10]:
        ticker = market.get("ticker", "")
        yes_ask = market.get("yes_ask", 0)
        no_ask = market.get("no_ask", 0)
        
        if yes_ask and no_ask:
            valid_markets += 1
            combined = (yes_ask + no_ask) / 100
            print(f'📈 {ticker[:30]:30s}: {yes_ask}c + {no_ask}c = {combined:.4f}')
    
    print(f'📊 Markets with ask prices: {valid_markets}')

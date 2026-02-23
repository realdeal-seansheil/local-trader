#!/usr/bin/env python3
"""
Find Crypto Price Markets in Kalshi - Fixed Version
"""

from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH

auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
client = KalshiClient(auth)

print('🔍 Deep Search for Crypto Price Markets...')

# Try searching for markets with crypto-related terms
crypto_search_terms = [
    'BTC', 'BITCOIN', 'ETH', 'ETHEREUM', 'CRYPTO', 'COIN', 'DIGITAL', 'TOKEN', 'BLOCKCHAIN'
]

print(f'🔍 Searching for markets with crypto terms: {crypto_search_terms}')

# Get all markets and search more thoroughly
result = client.get_markets(limit=1000)
all_markets = result.get('markets', [])

crypto_price_markets = []

for market in all_markets:
    ticker = market.get('ticker', '')
    title = market.get('title', '')
    subtitle = market.get('subtitle', '')
    
    # Check all fields for crypto terms
    market_text = f'{ticker} {title} {subtitle}'.upper()
    
    # Check if any crypto term appears anywhere
    if any(term in market_text for term in crypto_search_terms):
        # Check if it's actually a price market (YES/NO pricing)
        yes_ask = market.get('yes_ask', 0)
        no_ask = market.get('no_ask', 0)
        yes_bid = market.get('yes_bid', 0)
        no_bid = market.get('no_bid', 0)
        
        # Look for actual price data (not just crypto references)
        if yes_ask > 0 or no_ask > 0 or yes_bid > 0 or no_bid > 0:
            crypto_price_markets.append({
                'ticker': ticker,
                'title': title,
                'subtitle': subtitle,
                'yes_ask': yes_ask,
                'no_ask': no_ask,
                'yes_bid': yes_bid,
                'no_bid': no_bid,
                'market': market
            })
            
            if len(crypto_price_markets) <= 10:
                print(f'   🚀 {ticker}')
                print(f'      📈 YES: {yes_bid}c/{yes_ask}c')
                print(f'      📈 NO: {no_bid}c/{no_ask}c')
                print(f'      📊 {title[:60]}')

print(f'\n🚀 Crypto price markets found: {len(crypto_price_markets)}')

if crypto_price_markets:
    print(f'\n🎉 SUCCESS: Found crypto price markets!')
    print(f'📊 These are actual crypto price markets with YES/NO pricing')
    
    # Check for arbitrage opportunities
    arbitrage_opportunities = []
    
    for market in crypto_price_markets:
        yes_ask = market['yes_ask']
        no_ask = market['no_ask']
        
        if yes_ask and no_ask:
            combined = (yes_ask + no_ask) / 100
            if combined < 1.0 - 0.02:  # 2c minimum spread
                spread = round(1.0 - combined, 4)
                arbitrage_opportunities.append({
                    'ticker': market['ticker'],
                    'title': market['title'],
                    'combined': combined,
                    'spread': spread,
                    'yes_ask': yes_ask,
                    'no_ask': no_ask,
                    'yes_bid': market['yes_bid'],
                    'no_bid': market['no_bid']
                })
    
    print(f'\n📊 Arbitrage opportunities in crypto markets: {len(arbitrage_opportunities)}')
    
    if arbitrage_opportunities:
        print(f'\n🎉 Crypto Arbitrage Opportunities:')
        for i, opp in enumerate(arbitrage_opportunities[:5]):
            print(f'   {i+1}. {opp["ticker"]}')
            print(f'      Spread: {opp["spread"]} | Combined: {opp["combined"]}')
            print(f'      YES: {opp["yes_ask"]}c/{opp["yes_bid"]}c')
            print(f'      NO: {opp["no_ask"]}c/{opp["no_bid"]}c')
            print(f'      📊 {opp["title"][:60]}')
    else:
        print(f'\n❌ No arbitrage opportunities in crypto markets')
        
        # Show best spreads even if not arbitrage
        sorted_markets = sorted(crypto_price_markets, key=lambda x: (x['yes_ask'] + x['no_ask']))
        print(f'\n📊 Best crypto market spreads:')
        for i, market in enumerate(sorted_markets[:5]):
            combined = (market['yes_ask'] + market['no_ask']) / 100
            spread = round(1.0 - combined, 4)
            print(f'   {i+1}. {market["ticker"]}')
            print(f'      Spread: {spread} | Combined: {combined}')
            print(f'      YES: {market["yes_ask"]}c/{market["yes_bid"]}c')
            print(f'      NO: {market["no_ask"]}c/{market["no_bid"]}c')
            print(f'      📊 {market["title"][:60]}')
else:
    print(f'\n❌ No crypto price markets found with actual pricing')
    
    # Try searching for any markets that might be crypto-related
    print(f'\n🔍 Searching for any other crypto-related patterns...')
    
    # Look for markets with different patterns
    alternative_crypto = []
    
    for market in all_markets:
        ticker = market.get('ticker', '')
        
        # Look for patterns that might indicate crypto
        if 'BTC' in ticker or 'ETH' in ticker:
            alternative_crypto.append(market)
    
    print(f'\n📈 Alternative crypto-related markets: {len(alternative_crypto)}')
    
    if alternative_crypto:
        print(f'\n📈 Alternative crypto markets:')
        for i, market in enumerate(alternative_crypto[:5]):
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            status = market.get('status', 'unknown')
            print(f'   {i+1}. {ticker} - {status}')
            print(f'      📊 {title[:60]}')

if __name__ == "__main__":
    find_crypto_price_markets()

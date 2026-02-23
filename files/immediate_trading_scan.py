#!/usr/bin/env python3
"""
Immediate Trading Scan - Find and Execute Trading Opportunities NOW
"""

import os
import json
from datetime import datetime as dt
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def get_crypto_markets(auth, series_ticker, limit=5):
    """Get markets for a crypto series."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit={limit}'
        method = 'GET'
        
        msg = timestamp + method + path
        
        sig_bytes = auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            'KALSHI-ACCESS-KEY': auth.api_key_id,
            'KALSHI-ACCESS-SIGNATURE': signature,
            'KALSHI-ACCESS-TIMESTAMP': timestamp,
            'Content-Type': 'application/json',
        }
        
        url = 'https://api.elections.kalshi.com' + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get('markets', [])
        else:
            return []
            
    except Exception as e:
        return []

def scan_trading_opportunities():
    """Scan for immediate trading opportunities."""
    print('🚀 IMMEDIATE TRADING SCAN')
    print('=' * 50)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication
        client = KalshiClient(auth)
        test_markets = client.get_markets(limit=1)
        
        if not test_markets.get('markets'):
            print("❌ Authentication failed - no market access")
            return
        
        print('✅ Authentication successful')
        print('🔍 Scanning for immediate trading opportunities...')
        
        # Get top crypto series with real opportunities
        crypto_series = ['KXCRYPTORETURNY', 'KXBTCVSGOLD', 'KXDOGEMAXY', 'KXSATOSHIBTCYEAR', 'KXETHATH']
        
        best_opportunities = []
        
        for series_ticker in crypto_series:
            print(f'\n📊 {series_ticker}:')
            
            markets = get_crypto_markets(auth, series_ticker, limit=5)
            
            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                volume = market.get('volume', 0)
                
                # Look for immediate trading opportunities
                if yes_ask > 0 and yes_ask < 80 and volume > 100:
                    profit = 100 - yes_ask
                    confidence = (100 - yes_ask) / 100
                    
                    best_opportunities.append({
                        'ticker': ticker,
                        'direction': 'YES',
                        'entry_price': yes_ask,
                        'profit': profit,
                        'confidence': confidence,
                        'volume': volume,
                        'title': title[:50],
                        'series': series_ticker
                    })
                    
                    print(f'   🚀 YES: {ticker} at {yes_ask}c (profit: {profit}c, vol: {volume})')
                
                if no_ask > 0 and no_ask < 80 and volume > 100:
                    profit = 100 - no_ask
                    confidence = (100 - no_ask) / 100
                    
                    best_opportunities.append({
                        'ticker': ticker,
                        'direction': 'NO',
                        'entry_price': no_ask,
                        'profit': profit,
                        'confidence': confidence,
                        'volume': volume,
                        'title': title[:50],
                        'series': series_ticker
                    })
                    
                    print(f'   🚀 NO: {ticker} at {no_ask}c (profit: {profit}c, vol: {volume})')
        
        # Sort by volume * confidence (best opportunities first)
        best_opportunities.sort(key=lambda x: x['volume'] * x['confidence'], reverse=True)
        
        print(f'\n🎯 TOP TRADING OPPORTUNITIES - EXECUTE NOW!')
        print('=' * 60)
        
        if best_opportunities:
            for i, opp in enumerate(best_opportunities[:5]):
                expected_profit = opp['profit'] * 10 / 100  # 10 contracts
                
                print(f'\n{i+1}. 🚀 {opp["ticker"]} ({opp["direction"]})')
                print(f'   📊 {opp["title"]}')
                print(f'   💰 BUY at {opp["entry_price"]}c | Profit: {opp["profit"]}c per contract')
                print(f'   📊 Volume: {opp["volume"]} | Confidence: {opp["confidence"]:.1%}')
                print(f'   💸 Expected profit (10 contracts): ${expected_profit:.2f}')
                
                print(f'\n   📋 EXECUTION STEPS:')
                print(f'   1. Go to Kalshi trading interface')
                print(f'   2. Search for: {opp["ticker"]}')
                print(f'   3. Select {opp["direction"]} side')
                print(f'   4. Enter limit order at {opp["entry_price"]}c')
                print(f'   5. Size: 10 contracts')
                print(f'   6. Expected profit: ${expected_profit:.2f}')
            
            # Total potential
            total_potential = sum(opp['profit'] * 10 / 100 for opp in best_opportunities[:3])
            print(f'\n💰 TOTAL POTENTIAL PROFIT (TOP 3): ${total_potential:.2f}')
            
            print(f'\n🎉 READY TO TRADE!')
            print(f'📋 Execute these trades immediately for maximum profit!')
            
            # Save opportunities
            with open('immediate_trading_opportunities.json', 'w') as f:
                json.dump(best_opportunities[:5], f, indent=2)
            
            print(f'💾 Opportunities saved to: immediate_trading_opportunities.json')
            
        else:
            print(f'❌ No immediate trading opportunities found')
            print(f'💡 Market conditions might be unfavorable right now')
            print(f'🔄 Try again in a few minutes')
        
    except Exception as e:
        print(f'❌ Trading scan failed: {e}')

if __name__ == "__main__":
    scan_trading_opportunities()

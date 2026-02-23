#!/usr/bin/env python3
"""
Current 15-Minute Scanner - Finds markets expiring NOW
Markets expire and re-open EVERY 15 MINUTES continuously
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

def find_current_15min_markets():
    """Find 15-minute crypto markets that are expiring NOW."""
    print('🚨 FINDING CURRENT 15-MINUTE MARKETS - EXPIRING NOW!')
    print('=' * 70)
    print('💡 Markets expire and re-open EVERY 15 MINUTES')
    print('⏰ Looking for markets expiring in next 15 minutes')
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Get all active markets
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = '/trade-api/v2/markets?limit=500&status=active'
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
            all_markets = data.get('markets', [])
            print(f'📊 Scanning {len(all_markets)} active markets...')
            
            # Find markets expiring in next 15 minutes
            current_15min = []
            now = dt.utcnow()
            
            for market in all_markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '').lower()
                close_time = market.get('close_time', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                yes_bid = market.get('yes_bid', 0)
                no_bid = market.get('no_bid', 0)
                volume = market.get('volume', 0)
                category = market.get('category', '').lower()
                
                # Check if it's a crypto market
                is_crypto = (category == 'crypto' or 
                           any(keyword in title for keyword in [
                               'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 
                               'xrp', 'doge', 'crypto', 'price', 'up', 'down'
                           ]) or
                           any(keyword in ticker.lower() for keyword in [
                               'btc', 'eth', 'sol', 'xrp', 'doge'
                           ]))
                
                if not is_crypto:
                    continue
                
                # Check if market has real pricing
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume > 0
                
                if not (has_pricing and has_volume):
                    continue
                
                # Check if expiring in next 15 minutes
                if close_time:
                    try:
                        close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                        
                        if close_dt > now:
                            time_to_close = (close_dt - now).total_seconds() / 60
                            
                            # THIS IS THE KEY: Markets expiring in next 15 minutes
                            if time_to_close <= 15:
                                current_15min.append({
                                    'ticker': ticker,
                                    'title': market.get('title', ''),
                                    'time_to_close': time_to_close,
                                    'close_time': close_time,
                                    'yes_ask': yes_ask,
                                    'no_ask': no_ask,
                                    'yes_bid': yes_bid,
                                    'no_bid': no_bid,
                                    'volume': volume
                                })
                                
                                print(f'🚨 FOUND: {ticker}')
                                print(f'   📊 {market.get("title", "")[:60]}')
                                print(f'   ⏰ EXPIRES IN: {time_to_close:.1f} MINUTES!')
                                print(f'   💰 YES: {yes_bid}c/{yes_ask}c | NO: {no_bid}c/{no_ask}c')
                                print(f'   📊 Volume: {volume}')
                                
                    except Exception:
                        continue
            
            print(f'\n🎯 CURRENT 15-MINUTE CRYPTO MARKETS: {len(current_15min)}')
            
            if current_15min:
                # Sort by time to close (most urgent first)
                current_15min.sort(key=lambda x: x['time_to_close'])
                
                print(f'\n🚨 IMMEDIATE 15-MINUTE TRADING OPPORTUNITIES:')
                print('=' * 80)
                
                total_potential = 0
                
                for i, market in enumerate(current_15min):
                    ticker = market['ticker']
                    time_to_close = market['time_to_close']
                    yes_ask = market['yes_ask']
                    no_ask = market['no_ask']
                    volume = market['volume']
                    
                    urgency = '🚨' if time_to_close <= 5 else '⚡' if time_to_close <= 10 else '🎯'
                    
                    print(f'\n{urgency} MARKET #{i+1}: {ticker}')
                    print(f'   📊 {market["title"]}')
                    print(f'   ⏰ EXPIRES IN: {time_to_close:.1f} MINUTES!')
                    print(f'   💰 YES: {market["yes_bid"]}c/{yes_ask}c | NO: {market["no_bid"]}c/{no_ask}c')
                    print(f'   📊 Volume: {volume}')
                    
                    # Trading opportunities
                    opportunities = []
                    
                    if yes_ask > 0 and yes_ask < 80:
                        profit = 100 - yes_ask
                        confidence = (100 - yes_ask) / 100
                        opportunities.append({
                            'direction': 'YES',
                            'entry': yes_ask,
                            'profit': profit,
                            'confidence': confidence
                        })
                        print(f'   🎯 YES: Buy at {yes_ask}c, profit {profit}c ({confidence:.1%})')
                    
                    if no_ask > 0 and no_ask < 80:
                        profit = 100 - no_ask
                        confidence = (100 - no_ask) / 100
                        opportunities.append({
                            'direction': 'NO',
                            'entry': no_ask,
                            'profit': profit,
                            'confidence': confidence
                        })
                        print(f'   🎯 NO: Buy at {no_ask}c, profit {profit}c ({confidence:.1%})')
                    
                    # Arbitrage check
                    if yes_ask > 0 and no_ask > 0:
                        combined = (yes_ask + no_ask) / 100
                        spread = round(1.0 - combined, 4)
                        if spread > 0.01:
                            arbitrage_profit = spread * 100
                            print(f'   💸 ARBITRAGE: {spread:.4f} spread, {arbitrage_profit:.1f}c profit')
                    
                    if opportunities:
                        best = max(opportunities, key=lambda x: x['profit'] * x['confidence'])
                        expected_profit = best['profit'] * 25 / 100  # 25 contracts for aggressive trading
                        total_potential += expected_profit
                        
                        print(f'   💸 BEST TRADE: {best["direction"]} at {best["entry"]}c')
                        print(f'   📋 Expected profit (25 contracts): ${expected_profit:.2f}')
                        print(f'   📋 EXECUTE NOW: Search "{ticker}" on Kalshi')
                        
                        print(f'\n   📋 EXECUTION STEPS:')
                        print(f'      1. Go to Kalshi IMMEDIATELY')
                        print(f'      2. Search for: {ticker}')
                        print(f'      3. Select {best["direction"]} side')
                        print(f'      4. Enter limit order at {best["entry"]}c')
                        print(f'      5. Size: 25 contracts')
                        print(f'      6. EXECUTE NOW - {time_to_close:.1f} minutes left!')
                
                print(f'\n💰 TOTAL POTENTIAL PROFIT: ${total_potential:.2f}')
                print(f'\n🎉 FOUND ACTIVE 15-MINUTE CRYPTO MARKETS!')
                print(f'⚡ These are the markets expiring RIGHT NOW!')
                print(f'🚨 EXECUTE IMMEDIATELY - Markets expire within 15 minutes!')
                
                # Save results
                with open('current_15min_markets.json', 'w') as f:
                    json.dump({
                        'timestamp': now.isoformat(),
                        'markets': current_15min,
                        'total_found': len(current_15min),
                        'total_potential': total_potential
                    }, f, indent=2)
                
                print(f'\n💾 Results saved to: current_15min_markets.json')
                
            else:
                print(f'\n❌ No current 15-minute crypto markets found')
                print(f'💡 This means:')
                print(f'   📊 All current 15-minute markets have expired')
                print(f'   ⏰ New markets will appear in next few minutes')
                print(f'   🔄 The 15-minute cycle is between markets')
                
                # Calculate when next markets should appear
                now = dt.utcnow()
                current_minute = now.minute
                current_second = now.second
                
                # Find next 15-minute boundary
                minutes_to_next = 15 - (current_minute % 15)
                if current_second > 0:
                    minutes_to_next = 15 - ((current_minute + 1) % 15)
                
                next_market_time = now + timedelta(minutes=minutes_to_next)
                
                print(f'\n⏰ NEXT 15-MINUTE MARKETS SHOULD APPEAR:')
                print(f'   📅 In: {minutes_to_next} minutes')
                print(f'   🕐 At: {next_market_time.strftime("%H:%M:%S")} UTC')
                print(f'\n💡 KEEP SCANNING - New markets appear continuously!')
        
        else:
            print(f'❌ API error: {resp.status_code}')
    
    except Exception as e:
        print(f'❌ Search failed: {e}')

if __name__ == "__main__":
    find_current_15min_markets()

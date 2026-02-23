#!/usr/bin/env python3
"""
Hourly 15-Minute Market Finder
Finds markets that re-open and expire at the bottom of the hour
Pattern: XX:45, XX:30, XX:15, XX:00 expiration times
"""

import os
import json
from datetime import datetime as dt, timedelta
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

def find_hourly_15min_markets():
    """Find markets that expire at the bottom of the hour (15-minute pattern)."""
    print('🔍 FINDING HOURLY 15-MINUTE MARKETS')
    print('=' * 60)
    print('💡 Pattern: Markets re-open and expire at bottom of hour')
    print('⏰ Looking for :00, :15, :30, :45 expiration times')
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
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
            print(f'📊 Found {len(all_markets)} total active markets')
            
            # Look for markets with 15-minute expiration pattern
            hourly_15min_markets = []
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
                               'btc', 'eth', 'sol', 'xrp', 'doge', 'crypto'
                           ]))
                
                if not is_crypto:
                    continue
                
                # Check if market has real pricing
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume > 0
                
                if not (has_pricing and has_volume):
                    continue
                
                # Check expiration time pattern
                if close_time:
                    try:
                        close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                        
                        if close_dt > now:
                            time_to_close = (close_dt - now).total_seconds() / 60
                            
                            # Check if it expires at quarter-hour intervals
                            minute = close_dt.minute
                            is_15min_pattern = minute in [0, 15, 30, 45]
                            
                            if is_15min_pattern and time_to_close <= 60:  # Within 1 hour
                                hourly_15min_markets.append({
                                    'ticker': ticker,
                                    'title': market.get('title', ''),
                                    'category': category,
                                    'time_to_close': time_to_close,
                                    'close_time': close_time,
                                    'close_minute': minute,
                                    'yes_ask': yes_ask,
                                    'no_ask': no_ask,
                                    'yes_bid': yes_bid,
                                    'no_bid': no_bid,
                                    'volume': volume
                                })
                                
                                print(f'🚀 FOUND: {ticker}')
                                print(f'   📊 {market.get(\"title\", \"\")[:60]}')
                                print(f'   ⏰ Closes at: {close_dt.strftime(\"%H:%M\")} (in {time_to_close:.1f}m)')
                                print(f'   💰 YES: {yes_bid}c/{yes_ask}c | NO: {no_bid}c/{no_ask}c')
                                print(f'   📊 Volume: {volume}')
                                
                    except Exception as e:
                        continue
            
            print(f'\\n🎯 HOURLY 15-MINUTE CRYPTO MARKETS: {len(hourly_15min_markets)}')
            
            if hourly_15min_markets:
                # Sort by time to close (most urgent first)
                hourly_15min_markets.sort(key=lambda x: x['time_to_close'])
                
                print(f'\\n🚨 IMMEDIATE TRADING OPPORTUNITIES:')
                print('=' * 70)
                
                for i, market in enumerate(hourly_15min_markets[:10]):
                    ticker = market['ticker']
                    time_to_close = market['time_to_close']
                    close_minute = market['close_minute']
                    yes_ask = market['yes_ask']
                    no_ask = market['no_ask']
                    volume = market['volume']
                    
                    urgency = '🚨' if time_to_close <= 5 else '⚡' if time_to_close <= 15 else '🎯'
                    
                    print(f'\\n{urgency} {i+1}. {ticker}')
                    print(f'   📊 {market[\"title\"]}')
                    print(f'   ⏰ EXPIRES: {close_minute:02d} minutes past hour (in {time_to_close:.1f}m)')
                    print(f'   💰 YES: {market[\"yes_bid\"]}c/{yes_ask}c | NO: {market[\"no_bid\"]}c/{no_ask}c')
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
                        expected_profit = best['profit'] * 20 / 100  # 20 contracts
                        print(f'   💸 BEST: {best[\"direction\"]} at {best[\"entry\"]}c')
                        print(f'   📋 Expected profit (20 contracts): ${expected_profit:.2f}')
                        print(f'   📋 EXECUTE: Search {ticker} on Kalshi NOW')
                
                # Calculate total potential
                total_opportunities = []
                for market in hourly_15min_markets[:5]:
                    if market['yes_ask'] > 0 and market['yes_ask'] < 80:
                        total_opportunities.append(100 - market['yes_ask'])
                    if market['no_ask'] > 0 and market['no_ask'] < 80:
                        total_opportunities.append(100 - market['no_ask'])
                
                total_potential = sum(total_opportunities[:5]) * 20 / 100
                print(f'\\n💰 TOP 5 OPPORTUNITIES POTENTIAL: ${total_potential:.2f}')
                
                # Save results
                with open('hourly_15min_markets.json', 'w') as f:
                    json.dump({
                        'timestamp': now.isoformat(),
                        'markets': hourly_15min_markets,
                        'total_found': len(hourly_15min_markets)
                    }, f, indent=2)
                
                print(f'\\n💾 Results saved to: hourly_15min_markets.json')
                print(f'\\n🎉 FOUND REAL HOURLY 15-MINUTE CRYPTO MARKETS!')
                print(f'⚡ These follow the bottom-of-hour expiration pattern!')
                print(f'🚨 EXECUTE IMMEDIATELY - Markets expire within the hour!')
                
            else:
                print(f'\\n❌ No hourly 15-minute crypto markets found')
                print(f'💡 This could mean:')
                print(f'   📊 Between expiration cycles')
                print(f'   ⏰ All current markets have expired')
                print(f'   🔄 New markets will appear at next quarter hour')
                
                # Show next quarter hour times
                now = dt.utcnow()
                current_minute = now.minute
                
                next_times = []
                for minute in [0, 15, 30, 45]:
                    if minute > current_minute:
                        next_time = now.replace(minute=minute, second=0, microsecond=0)
                        next_times.append(next_time)
                
                # If no times left this hour, check next hour
                if not next_times:
                    for minute in [0, 15, 30, 45]:
                        next_time = (now + timedelta(hours=1)).replace(minute=minute, second=0, microsecond=0)
                        next_times.append(next_time)
                
                print(f'\\n⏰ NEXT 15-MINUTE EXPIRATION TIMES:')
                for i, next_time in enumerate(next_times[:4]):
                    time_diff = (next_time - now).total_seconds() / 60
                    print(f'   {i+1}. {next_time.strftime(\"%H:%M\")} (in {time_diff:.1f} minutes)')
                
                print(f'\\n💡 NEW MARKETS SHOULD APPEAR AT THESE TIMES!')
        
        else:
            print(f'❌ API error: {resp.status_code}')
    
    except Exception as e:
        print(f'❌ Search failed: {e}')

if __name__ == "__main__":
    find_hourly_15min_markets()

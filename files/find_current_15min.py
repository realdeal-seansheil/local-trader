#!/usr/bin/env python3
"""
Find Current 15-Minute Crypto Markets
Looks for markets with today's date and real pricing
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
    """Find current 15-minute crypto markets with today's date."""
    print('🔍 FINDING CURRENT 15-MINUTE CRYPTO MARKETS')
    print('=' * 60)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Get all markets
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = '/trade-api/v2/markets?limit=500'
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
            markets = data.get('markets', [])
            print(f'📊 Scanning {len(markets)} markets for current 15-minute opportunities...')
            
            today_str = dt.utcnow().strftime('%y%m%d')  # Today's date
            current_time = dt.utcnow()
            
            current_15min = []
            
            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                volume = market.get('volume', 0)
                status = market.get('status', '')
                close_time = market.get('close_time', '')
                
                # Check if it's a 15-minute crypto market
                is_15min_crypto = ('15M' in ticker or '15m' in ticker) and any(keyword in ticker.lower() for keyword in [
                    'btc', 'eth', 'sol', 'xrp', 'doge'
                ])
                
                # Check if it has TODAY'S date
                has_todays_date = today_str in ticker
                
                # Check if it has pricing and volume
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume > 0
                is_active = status == 'active'
                
                if is_15min_crypto and has_todays_date and has_pricing and has_volume and is_active:
                    # Check time to close
                    time_to_close = 999
                    if close_time:
                        try:
                            close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                            if close_dt > current_time:
                                time_to_close = (close_dt - current_time).total_seconds() / 60
                        except:
                            pass
                    
                    current_15min.append({
                        'ticker': ticker,
                        'title': title,
                        'yes_ask': yes_ask,
                        'no_ask': no_ask,
                        'volume': volume,
                        'time_to_close': time_to_close,
                        'close_time': close_time
                    })
                    
                    print(f'🚨 FOUND CURRENT MARKET: {ticker}')
                    print(f'   📊 {title[:60]}')
                    print(f'   💰 YES: {yes_ask}c | NO: {no_ask}c')
                    print(f'   📊 Volume: {volume} | Closes in: {time_to_close:.1f}m')
                    
                    # Trading opportunities
                    if yes_ask > 0 and yes_ask < 80:
                        profit = 100 - yes_ask
                        print(f'   🎯 YES: Buy at {yes_ask}c, profit {profit}c')
                    
                    if no_ask > 0 and no_ask < 80:
                        profit = 100 - no_ask
                        print(f'   🎯 NO: Buy at {no_ask}c, profit {profit}c')
                    
                    print(f'   📋 TRADE NOW: Search {ticker} on Kalshi')
            
            print(f'\n🎯 CURRENT 15-MINUTE MARKETS: {len(current_15min)}')
            
            if current_15min:
                # Sort by time to close
                current_15min.sort(key=lambda x: x['time_to_close'])
                
                print(f'\n🚨 IMMEDIATE TRADING OPPORTUNITIES:')
                for i, market in enumerate(current_15min[:5]):
                    ticker = market['ticker']
                    time_to_close = market['time_to_close']
                    yes_ask = market['yes_ask']
                    no_ask = market['no_ask']
                    volume = market['volume']
                    
                    urgency = '🚨' if time_to_close <= 5 else '⚡' if time_to_close <= 15 else '🎯'
                    
                    print(f'\n{urgency} {i+1}. {ticker}')
                    print(f'   📊 {market["title"]}')
                    print(f'   ⏰ Closes in: {time_to_close:.1f} minutes!')
                    print(f'   💰 YES: {yes_ask}c | NO: {no_ask}c')
                    print(f'   📊 Volume: {volume}')
                    
                    # Best trade
                    best_trade = None
                    if yes_ask > 0 and yes_ask < 80:
                        profit = 100 - yes_ask
                        best_trade = ('YES', yes_ask, profit)
                    if no_ask > 0 and no_ask < 80:
                        profit = 100 - no_ask
                        if not best_trade or profit > best_trade[2]:
                            best_trade = ('NO', no_ask, profit)
                    
                    if best_trade:
                        direction, price, profit = best_trade
                        expected_profit = profit * 20 / 100  # 20 contracts
                        print(f'   💸 BEST TRADE: {direction} at {price}c')
                        print(f'   💸 Expected profit: ${expected_profit:.2f}')
                        print(f'   📋 EXECUTE: Search {ticker} on Kalshi NOW')
                
                # Save results
                with open('current_15min_markets.json', 'w') as f:
                    json.dump({
                        'timestamp': dt.now().isoformat(),
                        'markets': current_15min,
                        'total_found': len(current_15min)
                    }, f, indent=2)
                
                print(f'\n💾 Results saved to: current_15min_markets.json')
                
            else:
                print(f'\n❌ NO CURRENT 15-MINUTE MARKETS FOUND!')
                print(f'💡 This means:')
                print(f'   📊 All current 15-minute markets are determined')
                print(f'   ⏰ New markets will appear at next 15-minute boundary')
                
                # Calculate next 15-minute boundaries
                current_minute = current_time.minute
                next_minutes = []
                for minute in [0, 15, 30, 45]:
                    if minute > current_minute:
                        next_time = current_time.replace(minute=minute, second=0, microsecond=0)
                        next_minutes.append(next_time)
                
                if not next_minutes:
                    for minute in [0, 15, 30, 45]:
                        next_time = (current_time + dt.timedelta(hours=1)).replace(minute=minute, second=0, microsecond=0)
                        next_minutes.append(next_time)
                
                print(f'\n⏰ NEXT 15-MINUTE MARKETS SHOULD APPEAR AT:')
                for i, next_time in enumerate(next_minutes[:4]):
                    time_diff = (next_time - current_time).total_seconds() / 60
                    print(f'   {i+1}. {next_time.strftime("%H:%M")} (in {time_diff:.0f} minutes)')
                
                print(f'\n💡 KEEP SCANNING - NEW MARKETS APPEAR EVERY 15 MINUTES!')
        
        else:
            print(f'❌ Error: {resp.status_code}')
    
    except Exception as e:
        print(f'❌ Failed: {e}')

if __name__ == "__main__":
    find_current_15min_markets()

#!/usr/bin/env python3
"""
Check Real 15-Minute Crypto Markets
Found from Kalshi website: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M
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

def check_real_15min_markets():
    """Check the actual 15-minute crypto markets from the website."""
    print('🚨 FOUND THE REAL 15-MINUTE CRYPTO MARKETS!')
    print('=' * 60)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    try:
        # Initialize authentication
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # The actual 15-minute crypto markets from the website
        crypto_15min_markets = [
            'KXBTC15M-26FEB171515',  # Bitcoin 15-min
            'KXETH15M-26FEB171515',  # Ethereum 15-min
            'KXSOL15M-26FEB171515',  # Solana 15-min
            'KXXRP15M-26FEB171515'   # XRP 15-min
        ]
        
        print('📊 CHECKING CURRENT 15-MINUTE CRYPTO MARKETS:')
        
        active_opportunities = []
        
        for ticker in crypto_15min_markets:
            print(f'\n📈 {ticker}:')
            
            # Get market data
            timestamp = str(int(dt.now().timestamp() * 1000))
            path = f'/trade-api/v2/markets?ticker={ticker}&limit=1'
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
                if markets:
                    market = markets[0]
                    
                    yes_ask = market.get('yes_ask', 0)
                    no_ask = market.get('no_ask', 0)
                    yes_bid = market.get('yes_bid', 0)
                    no_bid = market.get('no_bid', 0)
                    volume = market.get('volume', 0)
                    status = market.get('status', 'unknown')
                    close_time = market.get('close_time', '')
                    title = market.get('title', '')
                    
                    print(f'   📊 Title: {title}')
                    print(f'   💰 Pricing: YES {yes_bid}c/{yes_ask}c | NO {no_bid}c/{no_ask}c')
                    print(f'   📊 Volume: {volume}')
                    print(f'   📈 Status: {status}')
                    print(f'   ⏰ Close time: {close_time}')
                    
                    # Check if this is an active trading opportunity
                    has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                    has_volume = volume > 0
                    is_active = status == 'active'
                    
                    print(f'   🔍 Analysis:')
                    print(f'      ✅ Has pricing: {has_pricing}')
                    print(f'      ✅ Has volume: {has_volume}')
                    print(f'      ✅ Is active: {is_active}')
                    
                    # Calculate time to close
                    if close_time:
                        try:
                            close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                            now = dt.utcnow()
                            
                            if close_dt > now:
                                time_to_close = (close_dt - now).total_seconds() / 60
                                print(f'      ⏰ Time to close: {time_to_close:.1f} minutes')
                                
                                # Check if it's a current 15-minute window
                                if time_to_close <= 15:
                                    print(f'      🚨 ACTIVE 15-MINUTE WINDOW!')
                                    
                                    # Look for trading opportunities
                                    if yes_ask > 0 and yes_ask < 80:
                                        profit = 100 - yes_ask
                                        confidence = (100 - yes_ask) / 100
                                        
                                        active_opportunities.append({
                                            'ticker': ticker,
                                            'direction': 'YES',
                                            'entry_price': yes_ask,
                                            'profit': profit,
                                            'confidence': confidence,
                                            'volume': volume,
                                            'time_to_close': time_to_close,
                                            'title': title
                                        })
                                        
                                        print(f'         🎯 YES Opportunity: Buy at {yes_ask}c, profit {profit}c')
                                    
                                    if no_ask > 0 and no_ask < 80:
                                        profit = 100 - no_ask
                                        confidence = (100 - no_ask) / 100
                                        
                                        active_opportunities.append({
                                            'ticker': ticker,
                                            'direction': 'NO',
                                            'entry_price': no_ask,
                                            'profit': profit,
                                            'confidence': confidence,
                                            'volume': volume,
                                            'time_to_close': time_to_close,
                                            'title': title
                                        })
                                        
                                        print(f'         🎯 NO Opportunity: Buy at {no_ask}c, profit {profit}c')
                                else:
                                    print(f'      📊 Not in current 15-min window (closes in {time_to_close:.1f}m)')
                            else:
                                print(f'      ❌ Market already closed')
                        except Exception as e:
                            print(f'      ❓ Cannot parse close time: {e}')
                    else:
                        print(f'      ❓ No close time provided')
                else:
                    print(f'   ❌ No market data found')
            else:
                print(f'   ❌ API error: {resp.status_code}')
        
        print(f'\n🎯 15-MINUTE TRADING OPPORTUNITIES:')
        print('=' * 60)
        
        if active_opportunities:
            # Sort by time to close (most urgent first)
            active_opportunities.sort(key=lambda x: x['time_to_close'])
            
            for i, opp in enumerate(active_opportunities):
                expected_profit = opp['profit'] * 15 / 100  # 15 contracts
                
                print(f'\n{i+1}. 🚨 {opp["ticker"]} ({opp["direction"]})')
                print(f'   📊 {opp["title"]}')
                print(f'   ⏰ CLOSES IN: {opp["time_to_close"]:.1f} MINUTES!')
                print(f'   💰 BUY at {opp["entry_price"]}c | Profit: {opp["profit"]}c per contract')
                print(f'   📊 Volume: {opp["volume"]} | Confidence: {opp["confidence"]:.1%}')
                print(f'   💸 Expected profit (15 contracts): ${expected_profit:.2f}')
                
                print(f'\n   📋 IMMEDIATE EXECUTION:')
                print(f'   1. Go to Kalshi NOW')
                print(f'   2. Search: {opp["ticker"]}')
                print(f'   3. Select {opp["direction"]} side')
                print(f'   4. Enter limit order at {opp["entry_price"]}c')
                print(f'   5. Size: 15 contracts')
                print(f'   6. EXECUTE IMMEDIATELY!')
            
            total_potential = sum(opp['profit'] * 15 / 100 for opp in active_opportunities)
            print(f'\n💰 TOTAL POTENTIAL PROFIT: ${total_potential:.2f}')
            print(f'\n🎉 FOUND REAL 15-MINUTE CRYPTO OPPORTUNITIES!')
            print(f'⚡ DISTINCT-BAGUETTE STYLE TRADING AVAILABLE!')
            
        else:
            print(f'❌ No active 15-minute opportunities found')
            print(f'💡 This could mean:')
            print(f'   📊 Markets are between 15-minute intervals')
            print(f'   ⏰ Current markets have already closed')
            print(f'   🔄 New markets will appear soon')
            
            print(f'\n🔍 SOLUTION: Create a continuous scanner that:')
            print(f'   ⚡ Scans every 30 seconds for new 15-minute markets')
            print(f'   🚨 Alerts immediately when active markets appear')
            print(f'   💰 Executes trades within the 15-minute window')
            print(f'   📈 Focuses on these 4 series: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M')
        
        # Save results
        with open('real_15min_check.json', 'w') as f:
            json.dump({
                'timestamp': dt.now().isoformat(),
                'active_opportunities': active_opportunities,
                'markets_checked': crypto_15min_markets
            }, f, indent=2)
        
        print(f'\n💾 Results saved to: real_15min_check.json')
        
    except Exception as e:
        print(f'❌ Analysis failed: {e}')

if __name__ == "__main__":
    check_real_15min_markets()

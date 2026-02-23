#!/usr/bin/env python3
"""
Dynamic 15-Minute Crypto Trader
Finds and trades CURRENT active 15-minute crypto markets
"""

import os
import json
import time
from datetime import datetime as dt, timedelta
from kalshi_executor import KalshiAuth, KalshiClient
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# DYNAMIC 15-MINUTE TRADER CONFIGURATION
# ============================================================

# 15-minute series to monitor
MINUTE_15_SERIES = ['KXBTC15M', 'KXETH15M']

# Trading parameters
SCAN_INTERVAL = 30              # 30-second scans
POSITION_SIZE = 15             # 15 contracts per trade
MAX_POSITIONS = 3              # Max concurrent positions
MIN_PRICE = 10                # Minimum price to consider
MAX_PRICE = 80                # Maximum price to consider
MIN_VOLUME = 100              # Minimum volume threshold
TARGET_PROFIT = 5              # 5 cent target profit

# ============================================================
# API FUNCTIONS
# ============================================================

def get_current_15min_markets(auth, series_ticker, limit=50):
    """Get CURRENT 15-minute markets for a series."""
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

def find_active_15min_markets(auth):
    """Find CURRENTLY ACTIVE 15-minute markets."""
    print("🔍 Finding CURRENT active 15-minute markets...")
    
    active_markets = []
    now = dt.utcnow()
    
    for series_ticker in MINUTE_15_SERIES:
        print(f"\\n📊 Checking {series_ticker}...")
        
        markets = get_current_15min_markets(auth, series_ticker, limit=100)
        print(f"   📈 Found {len(markets)} total markets")
        
        series_active = []
        
        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            yes_ask = market.get('yes_ask', 0)
            no_ask = market.get('no_ask', 0)
            yes_bid = market.get('yes_bid', 0)
            no_bid = market.get('no_bid', 0)
            volume = market.get('volume', 0)
            status = market.get('status', 'unknown')
            close_time = market.get('close_time', '')
            
            # Check if market has real pricing (not determined)
            has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
            
            # Check if market has volume
            has_volume = volume > 0
            
            # Check if market is active
            is_active = status == 'active'
            
            # Check if market closes in the future
            closes_future = False
            time_to_close = 0
            
            if close_time:
                try:
                    # Parse close time
                    close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                    
                    if close_dt > now:
                        closes_future = True
                        time_to_close = (close_dt - now).total_seconds() / 60
                except:
                    # Try alternative format
                    try:
                        close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%SZ')
                        if close_dt > now:
                            closes_future = True
                            time_to_close = (close_dt - now).total_seconds() / 60
                    except:
                        pass
            
            # Market is viable if it meets all criteria
            if has_pricing and has_volume and is_active and closes_future:
                series_active.append({
                    'ticker': ticker,
                    'title': title,
                    'series': series_ticker,
                    'yes_ask': yes_ask,
                    'no_ask': no_ask,
                    'yes_bid': yes_bid,
                    'no_bid': no_bid,
                    'volume': volume,
                    'status': status,
                    'close_time': close_time,
                    'time_to_close': time_to_close
                })
                
                print(f"      🚀 ACTIVE: {ticker}")
                print(f"         💰 YES: {yes_bid}c/{yes_ask}c | NO: {no_bid}c/{no_ask}c")
                print(f"         📊 Volume: {volume} | Closes in: {time_to_close:.1f}m")
        
        print(f"   ✅ Active markets in {series_ticker}: {len(series_active)}")
        active_markets.extend(series_active)
    
    # Sort by time to close (soonest first)
    active_markets.sort(key=lambda x: x['time_to_close'])
    
    print(f"\\n🎯 TOTAL ACTIVE 15-MINUTE MARKETS: {len(active_markets)}")
    
    return active_markets

def analyze_15min_opportunities(active_markets):
    """Analyze trading opportunities in active 15-minute markets."""
    opportunities = []
    
    print("🔍 Analyzing 15-minute trading opportunities...")
    
    for market in active_markets:
        ticker = market['ticker']
        yes_ask = market['yes_ask']
        no_ask = market['no_ask']
        yes_bid = market['yes_bid']
        no_bid = market['no_bid']
        volume = market['volume']
        time_to_close = market['time_to_close']
        
        print(f"\\n📊 {ticker} (closes in {time_to_close:.1f}m):")
        print(f"   💰 YES: {yes_bid}c/{yes_ask}c | NO: {no_bid}c/{no_ask}c")
        print(f"   📊 Volume: {volume}")
        
        # Opportunity 1: Underpriced YES contracts
        if yes_ask > 0 and yes_ask < MAX_PRICE and volume >= MIN_VOLUME:
            profit_potential = 100 - yes_ask
            confidence = (100 - yes_ask) / 100
            
            if profit_potential >= TARGET_PROFIT:
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'YES',
                    'entry_price': yes_ask,
                    'target_price': 100,
                    'profit_potential': profit_potential,
                    'confidence': confidence,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'underpriced_yes',
                    'reasoning': f'YES underpriced at {yes_ask}c, {profit_potential}c profit potential'
                })
                
                print(f"      🎯 YES Opportunity: Buy at {yes_ask}c, profit {profit_potential}c")
        
        # Opportunity 2: Underpriced NO contracts
        if no_ask > 0 and no_ask < MAX_PRICE and volume >= MIN_VOLUME:
            profit_potential = 100 - no_ask
            confidence = (100 - no_ask) / 100
            
            if profit_potential >= TARGET_PROFIT:
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'NO',
                    'entry_price': no_ask,
                    'target_price': 100,
                    'profit_potential': profit_potential,
                    'confidence': confidence,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'underpriced_no',
                    'reasoning': f'NO underpriced at {no_ask}c, {profit_potential}c profit potential'
                })
                
                print(f"      🎯 NO Opportunity: Buy at {no_ask}c, profit {profit_potential}c")
        
        # Opportunity 3: Momentum plays (quick flips)
        if time_to_close < 10:  # Less than 10 minutes left
            if yes_ask > 0 and yes_ask < 50 and volume >= MIN_VOLUME * 2:
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'YES',
                    'entry_price': yes_ask,
                    'target_price': yes_ask + TARGET_PROFIT,
                    'profit_potential': TARGET_PROFIT,
                    'confidence': 0.7,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'momentum_yes',
                    'reasoning': f'Momentum play: {time_to_close:.1f}m left, YES at {yes_ask}c'
                })
                
                print(f"      ⚡ Momentum YES: Quick flip in {time_to_close:.1f}m")
            
            if no_ask > 0 and no_ask < 50 and volume >= MIN_VOLUME * 2:
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'NO',
                    'entry_price': no_ask,
                    'target_price': no_ask + TARGET_PROFIT,
                    'profit_potential': TARGET_PROFIT,
                    'confidence': 0.7,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'momentum_no',
                    'reasoning': f'Momentum play: {time_to_close:.1f}m left, NO at {no_ask}c'
                })
                
                print(f"      ⚡ Momentum NO: Quick flip in {time_to_close:.1f}m")
        
        # Opportunity 4: Arbitrage (if both sides have pricing)
        if yes_ask > 0 and no_ask > 0:
            combined = (yes_ask + no_ask) / 100
            spread = round(1.0 - combined, 4)
            
            if spread > 0.02:  # 2 cent spread
                arbitrage_profit = spread * 100
                
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'BOTH',
                    'yes_price': yes_ask,
                    'no_price': no_ask,
                    'combined': combined,
                    'spread': spread,
                    'arbitrage_profit': arbitrage_profit,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'arbitrage',
                    'reasoning': f'Arbitrage: {spread:.4f} spread, {arbitrage_profit:.1f}c profit'
                })
                
                print(f"      💸 Arbitrage: {spread:.4f} spread, {arbitrage_profit:.1f}c profit")
    
    # Sort by confidence * volume (priority to high-confidence, high-volume)
    opportunities.sort(key=lambda x: x['confidence'] * x['volume'], reverse=True)
    
    print(f"\\n🎯 15-MINUTE OPPORTUNITIES FOUND: {len(opportunities)}")
    
    return opportunities

def generate_15min_execution_guide(opportunities):
    """Generate execution guide for 15-minute trading."""
    if not opportunities:
        print("📊 No 15-minute opportunities found")
        return
    
    print(f"\\n📋 15-MINUTE TRADING EXECUTION GUIDE:")
    print("=" * 70)
    
    top_opps = opportunities[:5]
    
    for i, opp in enumerate(top_opps):
        print(f"\\n{'='*50}")
        print(f"15-MIN TRADE #{i+1}: {opp['ticker']}")
        print(f"{'='*50}")
        
        print(f"⏰ Time to close: {opp['time_to_close']:.1f} minutes")
        print(f"📊 Strategy: {opp['strategy']}")
        print(f"💡 Reasoning: {opp['reasoning']}")
        
        if opp['strategy'] in ['underpriced_yes', 'underpriced_no']:
            print(f"💰 Action: BUY {opp['direction']} contracts")
            print(f"📈 Entry: {opp['entry_price']}c | Target: {opp['target_price']}c")
            print(f"📈 Profit: {opp['profit_potential']}c per contract")
            print(f"🎯 Confidence: {opp['confidence']:.1%}")
            print(f"📊 Volume: {opp['volume']}")
            
            print(f"\\n📋 EXECUTION STEPS:")
            print(f"   1. Go to Kalshi and search: {opp['ticker']}")
            print(f"   2. Select {opp['direction']} side")
            print(f"   3. Enter limit order at {opp['entry_price']}c")
            print(f"   4. Size: {POSITION_SIZE} contracts")
            print(f"   5. Expected profit: ${opp['profit_potential'] * POSITION_SIZE / 100:.2f}")
            print(f"   6. Monitor until close ({opp['time_to_close']:.1f}m)")
            
        elif opp['strategy'] in ['momentum_yes', 'momentum_no']:
            print(f"⚡ Action: MOMENTUM PLAY - BUY {opp['direction']}")
            print(f"📈 Entry: {opp['entry_price']}c | Target: {opp['target_price']}c")
            print(f"📈 Quick profit: {opp['profit_potential']}c per contract")
            print(f"⏰ Time pressure: {opp['time_to_close']:.1f} minutes left")
            print(f"📊 Volume: {opp['volume']}")
            
            print(f"\\n📋 EXECUTION STEPS:")
            print(f"   1. Quick search: {opp['ticker']}")
            print(f"   2. Market order {opp['direction']} (momentum play)")
            print(f"   3. Size: {POSITION_SIZE} contracts")
            print(f"   4. Target exit: {opp['target_price']}c within 5 minutes")
            print(f"   5. Quick profit: ${opp['profit_potential'] * POSITION_SIZE / 100:.2f}")
            
        elif opp['strategy'] == 'arbitrage':
            print(f"💸 Action: ARBITRAGE - BUY BOTH SIDES")
            print(f"📈 YES: {opp['yes_price']}c | NO: {opp['no_price']}c")
            print(f"📊 Combined: {opp['combined']:.4f}")
            print(f"💸 Spread: {opp['spread']:.4f}")
            print(f"📈 Profit: {opp['arbitrage_profit']:.1f}c per contract")
            print(f"📊 Volume: {opp['volume']}")
            
            print(f"\\n📋 EXECUTION STEPS:")
            print(f"   1. Search: {opp['ticker']}")
            print(f"   2. Buy YES at {opp['yes_price']}c ({POSITION_SIZE//2} contracts)")
            print(f"   3. Buy NO at {opp['no_price']}c ({POSITION_SIZE//2} contracts)")
            print(f"   4. Hold until close ({opp['time_to_close']:.1f}m)")
            print(f"   5. Guaranteed profit: ${opp['arbitrage_profit'] * POSITION_SIZE // 200:.2f}")

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_dynamic_15min_trader():
    """Run the dynamic 15-minute crypto trader."""
    print("=" * 80)
    print("🚀 DYNAMIC 15-MINUTE CRYPTO TRADER")
    print("⚡ Finds and Trades CURRENT Active 15-Minute Markets")
    print("💰 Real-Time Market Discovery + Quick Execution")
    print("=" * 80)
    
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
        
        print(f"✅ Authentication successful")
        print(f"🎯 Monitoring 15-minute series: {', '.join(MINUTE_15_SERIES)}")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        print(f"🎯 Target profit: {TARGET_PROFIT}c per contract")
        
        # Trading loop
        scan_count = 0
        
        while True:  # Continuous scanning
            try:
                scan_count += 1
                current_time = dt.now()
                
                print(f"\\n{'='*70}")
                print(f"📊 SCAN #{scan_count} | {current_time.strftime('%H:%M:%S')}")
                
                # Find currently active 15-minute markets
                active_markets = find_active_15min_markets(auth)
                
                if active_markets:
                    # Analyze opportunities
                    opportunities = analyze_15min_opportunities(active_markets)
                    
                    if opportunities:
                        # Generate execution guide
                        generate_15min_execution_guide(opportunities)
                        
                        # Save opportunities
                        with open('active_15min_opportunities.json', 'w') as f:
                            json.dump({
                                'timestamp': current_time.isoformat(),
                                'scan': scan_count,
                                'active_markets': active_markets,
                                'opportunities': opportunities
                            }, f, indent=2)
                        
                        print(f"\\n💾 Opportunities saved to: active_15min_opportunities.json")
                        print(f"🎉 READY FOR 15-MINUTE TRADING!")
                        
                        # Calculate total potential profit
                        total_potential = sum(opp['profit_potential'] * POSITION_SIZE / 100 for opp in opportunities[:3])
                        print(f"💰 Top 3 opportunities potential: ${total_potential:.2f}")
                    else:
                        print(f"📊 No trading opportunities in current 15-minute markets")
                else:
                    print(f"📊 No currently active 15-minute markets found")
                    print(f"💡 This could be because:")
                    print(f"   📊 Market is closed (weekends/holidays)")
                    print(f"   ⏰ Between 15-minute intervals")
                    print(f"   🚫 No new markets created yet")
                    print(f"\\n🔄 Continuing to scan for new markets...")
                
                # Wait for next scan
                print(f"\\n⏳ Waiting {SCAN_INTERVAL} seconds for next scan...")
                time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\\n🛑 Manual shutdown")
                break
            except Exception as e:
                print(f"❌ Error in trading loop: {e}")
                time.sleep(30)
        
    except Exception as e:
        print(f"❌ Trader initialization failed: {e}")

if __name__ == "__main__":
    run_dynamic_15min_trader()

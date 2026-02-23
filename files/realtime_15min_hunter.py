#!/usr/bin/env python3
"""
Real-Time 15-Minute Market Hunter
Continuously scans for active 15-minute crypto markets and alerts immediately
Distinct-Baguette Style: Sub-second execution when markets appear
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
# REAL-TIME 15-MINUTE HUNTER CONFIGURATION
# ============================================================

# 15-minute series to hunt
MINUTE_15_SERIES = ['KXBTC15M', 'KXETH15M']

# Hunting parameters
SCAN_INTERVAL = 15              # 15-second scans (very fast)
ALERT_THRESHOLD = 1            # Alert immediately on any active market
POSITION_SIZE = 20             # 20 contracts for quick scalping
MIN_VOLUME = 50               # Low volume threshold (15-min markets are thin)
MAX_PRICE = 80                # Maximum entry price
MIN_PRICE = 5                 # Minimum price for meaningful profit

# Alert system
ALERT_SOUND = True             # Terminal alerts
SAVE_ALERTS = True             # Save to file
AUTO_EXECUTE = False           # Manual execution (safer)

# ============================================================
# API FUNCTIONS
# ============================================================

def get_15min_markets(auth, series_ticker, limit=20):
    """Get 15-minute markets for a series."""
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
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            return data.get('markets', [])
        else:
            return []
            
    except Exception as e:
        return []

def find_active_15min_markets(auth):
    """Find currently active 15-minute markets."""
    active_markets = []
    now = dt.utcnow()
    
    for series_ticker in MINUTE_15_SERIES:
        markets = get_15min_markets(auth, series_ticker, limit=30)
        
        for market in markets:
            ticker = market.get('ticker', '')
            yes_ask = market.get('yes_ask', 0)
            no_ask = market.get('no_ask', 0)
            yes_bid = market.get('yes_bid', 0)
            no_bid = market.get('no_bid', 0)
            volume = market.get('volume', 0)
            status = market.get('status', 'unknown')
            close_time = market.get('close_time', '')
            
            # Check if market is truly active
            has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
            has_volume = volume >= MIN_VOLUME
            is_active = status == 'active'
            
            # Check if market closes soon (within 30 minutes)
            closes_soon = False
            time_to_close = 0
            
            if close_time:
                try:
                    close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                    if close_dt > now:
                        time_to_close = (close_dt - now).total_seconds() / 60
                        closes_soon = time_to_close <= 30  # Within 30 minutes
                except:
                    try:
                        close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%SZ')
                        if close_dt > now:
                            time_to_close = (close_dt - now).total_seconds() / 60
                            closes_soon = time_to_close <= 30
                    except:
                        pass
            
            # Market is huntable if it meets criteria
            if has_pricing and is_active and closes_soon:
                active_markets.append({
                    'ticker': ticker,
                    'series': series_ticker,
                    'yes_ask': yes_ask,
                    'no_ask': no_ask,
                    'yes_bid': yes_bid,
                    'no_bid': no_bid,
                    'volume': volume,
                    'status': status,
                    'close_time': close_time,
                    'time_to_close': time_to_close,
                    'discovered_at': now.isoformat()
                })
    
    return active_markets

def analyze_15min_opportunities(active_markets):
    """Analyze trading opportunities in active 15-minute markets."""
    opportunities = []
    
    for market in active_markets:
        ticker = market['ticker']
        yes_ask = market['yes_ask']
        no_ask = market['no_ask']
        yes_bid = market['yes_bid']
        no_bid = market['no_bid']
        volume = market['volume']
        time_to_close = market['time_to_close']
        
        # Distinct-Baguette Strategy 1: Quick Scalps
        if yes_ask > 0 and MIN_PRICE <= yes_ask <= MAX_PRICE:
            profit_potential = 100 - yes_ask
            confidence = (100 - yes_ask) / 100
            
            # Quick flip opportunity (5-10 minute trades)
            if time_to_close <= 10:
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'YES',
                    'entry_price': yes_ask,
                    'target_price': yes_ask + 10,  # Quick 10c profit
                    'profit_potential': 10,
                    'confidence': confidence * 0.8,  # Lower confidence for quick flips
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'quick_scalp_yes',
                    'urgency': 'HIGH',
                    'reasoning': f'Quick scalp: {time_to_close:.1f}m left, YES at {yes_ask}c'
                })
        
        if no_ask > 0 and MIN_PRICE <= no_ask <= MAX_PRICE:
            profit_potential = 100 - no_ask
            confidence = (100 - no_ask) / 100
            
            if time_to_close <= 10:
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'NO',
                    'entry_price': no_ask,
                    'target_price': no_ask + 10,  # Quick 10c profit
                    'profit_potential': 10,
                    'confidence': confidence * 0.8,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'quick_scalp_no',
                    'urgency': 'HIGH',
                    'reasoning': f'Quick scalp: {time_to_close:.1f}m left, NO at {no_ask}c'
                })
        
        # Distinct-Baguette Strategy 2: Momentum Plays
        if volume > 100:  # Higher volume for momentum
            if yes_ask > 0 and yes_ask < 50:
                momentum_confidence = min(0.9, (50 - yes_ask) / 50)
                
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'YES',
                    'entry_price': yes_ask,
                    'target_price': 50,
                    'profit_potential': 50 - yes_ask,
                    'confidence': momentum_confidence,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'momentum_yes',
                    'urgency': 'MEDIUM' if time_to_close > 5 else 'HIGH',
                    'reasoning': f'Momentum: YES cheap at {yes_ask}c, volume {volume}'
                })
            
            if no_ask > 0 and no_ask < 50:
                momentum_confidence = min(0.9, (50 - no_ask) / 50)
                
                opportunities.append({
                    'ticker': ticker,
                    'direction': 'NO',
                    'entry_price': no_ask,
                    'target_price': 50,
                    'profit_potential': 50 - no_ask,
                    'confidence': momentum_confidence,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'momentum_no',
                    'urgency': 'MEDIUM' if time_to_close > 5 else 'HIGH',
                    'reasoning': f'Momentum: NO cheap at {no_ask}c, volume {volume}'
                })
        
        # Distinct-Baguette Strategy 3: Arbitrage (if both sides have pricing)
        if yes_ask > 0 and no_ask > 0:
            combined = (yes_ask + no_ask) / 100
            spread = round(1.0 - combined, 4)
            
            if spread > 0.01:  # 1 cent spread
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
                    'urgency': 'HIGH' if time_to_close < 5 else 'MEDIUM',
                    'reasoning': f'Arbitrage: {spread:.4f} spread, {arbitrage_profit:.1f}c profit'
                })
    
    # Sort by urgency and confidence
    urgency_order = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1}
    opportunities.sort(key=lambda x: (urgency_order.get(x['urgency'], 0), x['confidence']), reverse=True)
    
    return opportunities

def send_alert(opportunity):
    """Send immediate alert for 15-minute opportunity."""
    ticker = opportunity['ticker']
    strategy = opportunity['strategy']
    urgency = opportunity['urgency']
    time_to_close = opportunity['time_to_close']
    
    # Create alert message
    alert_msg = f"\n{'!' * 80}"
    alert_msg += f"\n🚨 15-MINUTE MARKET ALERT - {urgency} PRIORITY 🚨"
    alert_msg += f"\n{'!' * 80}"
    alert_msg += f"\n📈 TICKER: {ticker}"
    alert_msg += f"\n⏰ TIME TO CLOSE: {time_to_close:.1f} MINUTES"
    alert_msg += f"\n🎯 STRATEGY: {strategy}"
    alert_msg += f"\n💡 REASONING: {opportunity['reasoning']}"
    
    if opportunity['direction'] != 'BOTH':
        alert_msg += f"\n💰 ACTION: BUY {opportunity['direction']} at {opportunity['entry_price']}c"
        alert_msg += f"\n📈 TARGET: {opportunity['target_price']}c"
        alert_msg += f"\n💸 PROFIT: {opportunity['profit_potential']}c per contract"
    else:
        alert_msg += f"\n💸 ACTION: ARBITRAGE - BUY BOTH SIDES"
        alert_msg += f"\n📈 YES: {opportunity['yes_price']}c | NO: {opportunity['no_price']}c"
        alert_msg += f"\n💸 PROFIT: {opportunity['arbitrage_profit']:.1f}c per contract"
    
    alert_msg += f"\n📊 VOLUME: {opportunity['volume']}"
    alert_msg += f"\n🎯 CONFIDENCE: {opportunity['confidence']:.1%}"
    alert_msg += f"\n{'!' * 80}"
    alert_msg += f"\n⚡ EXECUTE IMMEDIATELY - DISTINCT-BAGUETTE STYLE ⚡"
    alert_msg += f"\n{'!' * 80}\n"
    
    # Print alert
    print(alert_msg)
    
    # Terminal bell (if enabled)
    if ALERT_SOUND:
        print('\a')  # Terminal bell
    
    # Save alert
    if SAVE_ALERTS:
        os.makedirs('data', exist_ok=True)
        with open('data/15min_alerts.jsonl', 'a') as f:
            alert_data = {
                'timestamp': dt.now().isoformat(),
                'alert': opportunity,
                'message': alert_msg
            }
            f.write(json.dumps(alert_data) + '\n')

def generate_execution_guide(opportunities):
    """Generate immediate execution guide."""
    print(f"\n📋 IMMEDIATE EXECUTION GUIDE - DISTINCT-BAGUETTE STYLE")
    print("=" * 70)
    
    for i, opp in enumerate(opportunities[:3]):
        print(f"\n{'🚀' if opp['urgency'] == 'HIGH' else '⚡'} TRADE #{i+1}: {opp['ticker']}")
        print(f"   ⏰ URGENCY: {opp['urgency']} | Time left: {opp['time_to_close']:.1f}m")
        print(f"   🎯 Strategy: {opp['strategy']}")
        print(f"   💡 {opp['reasoning']}")
        
        if opp['direction'] != 'BOTH':
            print(f"   💰 BUY {opp['direction']} at {opp['entry_price']}c")
            print(f"   📈 Target: {opp['target_price']}c | Profit: {opp['profit_potential']}c")
            expected_profit = opp['profit_potential'] * POSITION_SIZE / 100
            print(f"   💸 Expected profit: ${expected_profit:.2f} ({POSITION_SIZE} contracts)")
        else:
            print(f"   💸 ARBITRAGE: Buy YES at {opp['yes_price']}c, NO at {opp['no_price']}c")
            expected_profit = opp['arbitrage_profit'] * POSITION_SIZE // 200
            print(f"   💸 Expected profit: ${expected_profit:.2f} ({POSITION_SIZE} contracts)")
        
        print(f"   📊 Volume: {opp['volume']} | Confidence: {opp['confidence']:.1%}")
        
        print(f"\n   📋 EXECUTION STEPS:")
        print(f"   1. Go to Kalshi IMMEDIATELY")
        print(f"   2. Search: {opp['ticker']}")
        if opp['direction'] != 'BOTH':
            print(f"   3. Select {opp['direction']} side")
            print(f"   4. Enter limit order at {opp['entry_price']}c")
            print(f"   5. Size: {POSITION_SIZE} contracts")
        else:
            print(f"   3. Buy YES at {opp['yes_price']}c ({POSITION_SIZE//2} contracts)")
            print(f"   4. Buy NO at {opp['no_price']}c ({POSITION_SIZE//2} contracts)")
        print(f"   6. EXECUTE NOW - {opp['time_to_close']:.1f} minutes left!")

# ============================================================
# MAIN HUNTING LOOP
# ============================================================

def run_realtime_15min_hunter():
    """Run the real-time 15-minute market hunter."""
    print("=" * 80)
    print("🚨 REAL-TIME 15-MINUTE MARKET HUNTER")
    print("⚡ Distinct-Baguette Style: Sub-second Execution When Markets Appear")
    print("🎯 Continuous Scanning for Active 15-Minute Crypto Markets")
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
        print(f"🎯 Hunting 15-minute series: {', '.join(MINUTE_15_SERIES)}")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        print(f"🚨 Alert threshold: {ALERT_THRESHOLD} active market")
        print(f"📊 Volume threshold: {MIN_VOLUME} contracts")
        
        # Hunting loop
        scan_count = 0
        last_alert_time = None
        recent_alerts = []
        
        print(f"\n🚨 STARTING REAL-TIME HUNT...")
        print(f"⏰ Scanning every {SCAN_INTERVAL} seconds for 15-minute opportunities")
        print(f"🎯 Will alert IMMEDIATELY when active markets appear")
        
        while True:  # Continuous hunting
            try:
                scan_count += 1
                current_time = dt.now()
                
                print(f"\n{'🔍' if scan_count % 4 == 1 else '⚡' if scan_count % 4 == 2 else '🎯' if scan_count % 4 == 3 else '🚀'} SCAN #{scan_count} | {current_time.strftime('%H:%M:%S')}")
                
                # Hunt for active 15-minute markets
                active_markets = find_active_15min_markets(auth)
                
                if active_markets:
                    print(f"🎯 FOUND {len(active_markets)} ACTIVE 15-MINUTE MARKETS!")
                    
                    # Analyze opportunities
                    opportunities = analyze_15min_opportunities(active_markets)
                    
                    if opportunities:
                        print(f"🚨 {len(opportunities)} TRADING OPPORTUNITIES FOUND!")
                        
                        # Check for new alerts (avoid spam)
                        for opp in opportunities:
                            alert_key = f"{opp['ticker']}_{opp['strategy']}"
                            current_time_str = current_time.strftime('%H:%M')
                            
                            # Only alert if this is a new opportunity or hasn't been alerted recently
                            if (alert_key not in recent_alerts or 
                                last_alert_time is None or 
                                (current_time - last_alert_time).total_seconds() > 60):
                                
                                send_alert(opp)
                                recent_alerts.append(alert_key)
                                last_alert_time = current_time
                                
                                # Keep only recent alerts (last 10)
                                if len(recent_alerts) > 10:
                                    recent_alerts = recent_alerts[-10:]
                        
                        # Generate execution guide
                        generate_execution_guide(opportunities)
                        
                        # Save opportunities
                        with open('data/active_15min_opportunities.json', 'w') as f:
                            json.dump({
                                'timestamp': current_time.isoformat(),
                                'scan': scan_count,
                                'active_markets': active_markets,
                                'opportunities': opportunities
                            }, f, indent=2)
                        
                        # Calculate total potential
                        total_potential = sum(opp.get('profit_potential', 0) * POSITION_SIZE / 100 
                                              for opp in opportunities if opp['direction'] != 'BOTH')
                        print(f"\n💰 TOTAL POTENTIAL PROFIT: ${total_potential:.2f}")
                        
                    else:
                        print(f"📊 Active markets found but no trading opportunities")
                else:
                    print(f"📊 No active 15-minute markets found")
                    print(f"💡 Continuing to hunt...")
                
                # Wait for next scan
                time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Manual shutdown - Hunter stopped")
                break
            except Exception as e:
                print(f"❌ Error in hunting loop: {e}")
                time.sleep(30)
        
    except Exception as e:
        print(f"❌ Hunter initialization failed: {e}")

if __name__ == "__main__":
    run_realtime_15min_hunter()

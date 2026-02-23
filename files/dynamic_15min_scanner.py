#!/usr/bin/env python3
"""
Dynamic 15-Minute Scanner - Finds CURRENT Active Markets
Scans for TODAY'S 15-minute crypto markets with real pricing
Distinct-Baguette Style: Sub-second execution on current markets
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
# DYNAMIC 15-MINUTE SCANNER CONFIGURATION
# ============================================================

# 15-minute crypto series to hunt
MINUTE_15_SERIES = ['KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXXRP15M']

# Scanning parameters
SCAN_INTERVAL = 30              # 30-second scans
POSITION_SIZE = 20             # 20 contracts for quick scalping
MIN_VOLUME = 10                # Low volume threshold (15-min markets are thin)
MAX_PRICE = 80                # Maximum entry price
MIN_PRICE = 5                 # Minimum price for meaningful profit

# Alert system
ALERT_THRESHOLD = 1            # Alert on any active market
SAVE_ALERTS = True             # Save to file
CONTINUOUS_SCAN = True         # Keep scanning

# ============================================================
# API FUNCTIONS
# ============================================================

def get_all_15min_markets(auth, series_ticker, limit=100):
    """Get ALL 15-minute markets for a series to find current ones."""
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

def find_current_15min_markets(auth):
    """Find CURRENT 15-minute markets with today's date and real pricing."""
    current_markets = []
    now = dt.utcnow()
    today_str = now.strftime('%y%m%d')  # Today's date in YYMMDD format
    
    print(f"🔍 Looking for markets with today's date: {today_str}")
    
    for series_ticker in MINUTE_15_SERIES:
        print(f"\n📊 Scanning {series_ticker} for current markets...")
        
        markets = get_all_15min_markets(auth, series_ticker, limit=100)
        print(f"   📈 Found {len(markets)} total markets")
        
        current_series_markets = []
        
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
            
            # Check if ticker contains today's date
            if today_str in ticker:
                print(f"      🎯 FOUND TODAY'S MARKET: {ticker}")
                
                # Check if market has real pricing (not determined)
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume >= MIN_VOLUME
                is_active = status == 'active'
                
                # Check if market closes soon (within 30 minutes)
                closes_soon = False
                time_to_close = 0
                
                if close_time:
                    try:
                        # Try different date formats
                        try:
                            close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%S.%fZ')
                        except:
                            close_dt = dt.strptime(close_time, '%Y-%m-%dT%H:%M:%SZ')
                        
                        if close_dt > now:
                            time_to_close = (close_dt - now).total_seconds() / 60
                            closes_soon = time_to_close <= 30  # Within 30 minutes
                    except:
                        pass
                
                print(f"         💰 Pricing: YES {yes_bid}c/{yes_ask}c | NO {no_bid}c/{no_ask}c")
                print(f"         📊 Volume: {volume} | Status: {status}")
                print(f"         ⏰ Time to close: {time_to_close:.1f}m")
                
                # Market is tradeable if it meets criteria
                if has_pricing and is_active and closes_soon:
                    current_series_markets.append({
                        'ticker': ticker,
                        'series': series_ticker,
                        'title': title,
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
                    
                    print(f"         🚨 TRADEABLE MARKET FOUND!")
                else:
                    print(f"         📊 Not tradeable: Pricing={has_pricing}, Active={is_active}, Soon={closes_soon}")
        
        print(f"   ✅ Current tradeable markets in {series_ticker}: {len(current_series_markets)}")
        current_markets.extend(current_series_markets)
    
    # Sort by time to close (most urgent first)
    current_markets.sort(key=lambda x: x['time_to_close'])
    
    print(f"\n🎯 TOTAL CURRENT 15-MINUTE MARKETS: {len(current_markets)}")
    
    return current_markets

def analyze_current_opportunities(current_markets):
    """Analyze trading opportunities in current 15-minute markets."""
    opportunities = []
    
    for market in current_markets:
        ticker = market['ticker']
        yes_ask = market['yes_ask']
        no_ask = market['no_ask']
        yes_bid = market['yes_bid']
        no_bid = market['no_bid']
        volume = market['volume']
        time_to_close = market['time_to_close']
        series = market['series']
        
        print(f"\n📈 Analyzing {ticker} ({series}):")
        print(f"   ⏰ Time to close: {time_to_close:.1f} minutes")
        print(f"   💰 YES: {yes_bid}c/{yes_ask}c | NO: {no_bid}c/{no_ask}c")
        print(f"   📊 Volume: {volume}")
        
        # Distinct-Baguette Strategy 1: Quick Scalps (under 10 minutes)
        if time_to_close <= 10:
            if yes_ask > 0 and MIN_PRICE <= yes_ask <= MAX_PRICE:
                quick_profit = min(15, 100 - yes_ask)  # Quick 15c profit or max available
                confidence = (100 - yes_ask) / 100
                
                opportunities.append({
                    'ticker': ticker,
                    'series': series,
                    'direction': 'YES',
                    'entry_price': yes_ask,
                    'target_price': yes_ask + quick_profit,
                    'profit_potential': quick_profit,
                    'confidence': confidence * 0.8,  # Lower confidence for quick flips
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'quick_scalp_yes',
                    'urgency': 'CRITICAL',
                    'reasoning': f'CRITICAL: {time_to_close:.1f}m left, YES quick scalp at {yes_ask}c'
                })
                
                print(f"      🚨 CRITICAL: YES quick scalp - {quick_profit}c profit in {time_to_close:.1f}m")
            
            if no_ask > 0 and MIN_PRICE <= no_ask <= MAX_PRICE:
                quick_profit = min(15, 100 - no_ask)
                confidence = (100 - no_ask) / 100
                
                opportunities.append({
                    'ticker': ticker,
                    'series': series,
                    'direction': 'NO',
                    'entry_price': no_ask,
                    'target_price': no_ask + quick_profit,
                    'profit_potential': quick_profit,
                    'confidence': confidence * 0.8,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'quick_scalp_no',
                    'urgency': 'CRITICAL',
                    'reasoning': f'CRITICAL: {time_to_close:.1f}m left, NO quick scalp at {no_ask}c'
                })
                
                print(f"      🚨 CRITICAL: NO quick scalp - {quick_profit}c profit in {time_to_close:.1f}m")
        
        # Distinct-Baguette Strategy 2: Momentum Plays (10-20 minutes)
        elif time_to_close <= 20:
            if yes_ask > 0 and yes_ask < 50:
                momentum_profit = 50 - yes_ask
                confidence = min(0.9, (50 - yes_ask) / 50)
                
                opportunities.append({
                    'ticker': ticker,
                    'series': series,
                    'direction': 'YES',
                    'entry_price': yes_ask,
                    'target_price': 50,
                    'profit_potential': momentum_profit,
                    'confidence': confidence,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'momentum_yes',
                    'urgency': 'HIGH',
                    'reasoning': f'Momentum: YES cheap at {yes_ask}c, {time_to_close:.1f}m left'
                })
                
                print(f"      ⚡ HIGH: YES momentum play - {momentum_profit}c profit in {time_to_close:.1f}m")
            
            if no_ask > 0 and no_ask < 50:
                momentum_profit = 50 - no_ask
                confidence = min(0.9, (50 - no_ask) / 50)
                
                opportunities.append({
                    'ticker': ticker,
                    'series': series,
                    'direction': 'NO',
                    'entry_price': no_ask,
                    'target_price': 50,
                    'profit_potential': momentum_profit,
                    'confidence': confidence,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'momentum_no',
                    'urgency': 'HIGH',
                    'reasoning': f'Momentum: NO cheap at {no_ask}c, {time_to_close:.1f}m left'
                })
                
                print(f"      ⚡ HIGH: NO momentum play - {momentum_profit}c profit in {time_to_close:.1f}m")
        
        # Distinct-Baguette Strategy 3: Arbitrage (if both sides have pricing)
        if yes_ask > 0 and no_ask > 0:
            combined = (yes_ask + no_ask) / 100
            spread = round(1.0 - combined, 4)
            
            if spread > 0.01:  # 1 cent spread
                arbitrage_profit = spread * 100
                
                opportunities.append({
                    'ticker': ticker,
                    'series': series,
                    'direction': 'BOTH',
                    'yes_price': yes_ask,
                    'no_price': no_ask,
                    'combined': combined,
                    'spread': spread,
                    'arbitrage_profit': arbitrage_profit,
                    'volume': volume,
                    'time_to_close': time_to_close,
                    'strategy': 'arbitrage',
                    'urgency': 'HIGH' if time_to_close < 10 else 'MEDIUM',
                    'reasoning': f'Arbitrage: {spread:.4f} spread, {arbitrage_profit:.1f}c profit'
                })
                
                print(f"      💸 ARBITRAGE: {spread:.4f} spread, {arbitrage_profit:.1f}c profit")
    
    # Sort by urgency and confidence
    urgency_order = {'CRITICAL': 3, 'HIGH': 2, 'MEDIUM': 1, 'LOW': 0}
    opportunities.sort(key=lambda x: (urgency_order.get(x['urgency'], 0), x['confidence']), reverse=True)
    
    return opportunities

def send_immediate_alert(opportunity):
    """Send immediate alert for current 15-minute opportunity."""
    ticker = opportunity['ticker']
    series = opportunity['series']
    strategy = opportunity['strategy']
    urgency = opportunity['urgency']
    time_to_close = opportunity['time_to_close']
    
    # Create alert message
    alert_msg = f"\n{'!' * 80}"
    alert_msg += f"\n🚨 CURRENT 15-MINUTE MARKET ALERT - {urgency} PRIORITY 🚨"
    alert_msg += f"\n{'!' * 80}"
    alert_msg += f"\n📈 TICKER: {ticker} ({series})"
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
    
    # Terminal bell
    print('\a')
    
    # Save alert
    if SAVE_ALERTS:
        os.makedirs('data', exist_ok=True)
        with open('data/current_15min_alerts.jsonl', 'a') as f:
            alert_data = {
                'timestamp': dt.now().isoformat(),
                'alert': opportunity,
                'message': alert_msg
            }
            f.write(json.dumps(alert_data) + '\n')

def generate_execution_guide(opportunities):
    """Generate immediate execution guide."""
    print(f"\n📋 IMMEDIATE EXECUTION GUIDE - CURRENT 15-MINUTE MARKETS")
    print("=" * 70)
    
    for i, opp in enumerate(opportunities[:3]):
        urgency_emoji = {'CRITICAL': '🚨', 'HIGH': '⚡', 'MEDIUM': '🎯', 'LOW': '📊'}
        emoji = urgency_emoji.get(opp['urgency'], '📊')
        
        print(f"\n{emoji} TRADE #{i+1}: {opp['ticker']} ({opp['series']})")
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
# MAIN DYNAMIC SCANNER
# ============================================================

def run_dynamic_15min_scanner():
    """Run the dynamic 15-minute scanner for current markets."""
    print("=" * 80)
    print("🚨 DYNAMIC 15-MINUTE SCANNER - CURRENT MARKETS")
    print("⚡ Finds TODAY'S 15-minute crypto markets with real pricing")
    print("🎯 Distinct-Baguette Style: Sub-second execution on current markets")
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
        print(f"🎯 Scanning 15-minute series: {', '.join(MINUTE_15_SERIES)}")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        print(f"📊 Today's date: {dt.utcnow().strftime('%y%m%d')}")
        
        # Scanning loop
        scan_count = 0
        last_alert_time = None
        recent_alerts = []
        
        print(f"\n🚨 STARTING DYNAMIC SCAN FOR CURRENT MARKETS...")
        print(f"⏰ Looking for markets with today's date and real pricing")
        
        while CONTINUOUS_SCAN:
            try:
                scan_count += 1
                current_time = dt.now()
                
                print(f"\n{'🔍' if scan_count % 4 == 1 else '⚡' if scan_count % 4 == 2 else '🎯' if scan_count % 4 == 3 else '🚀'} SCAN #{scan_count} | {current_time.strftime('%H:%M:%S')}")
                
                # Find current 15-minute markets
                current_markets = find_current_15min_markets(auth)
                
                if current_markets:
                    print(f"🎯 FOUND {len(current_markets)} CURRENT 15-MINUTE MARKETS!")
                    
                    # Analyze opportunities
                    opportunities = analyze_current_opportunities(current_markets)
                    
                    if opportunities:
                        print(f"🚨 {len(opportunities)} TRADING OPPORTUNITIES FOUND!")
                        
                        # Check for new alerts
                        for opp in opportunities:
                            alert_key = f"{opp['ticker']}_{opp['strategy']}"
                            current_time_str = current_time.strftime('%H:%M')
                            
                            # Only alert if this is a new opportunity
                            if (alert_key not in recent_alerts or 
                                last_alert_time is None or 
                                (current_time - last_alert_time).total_seconds() > 60):
                                
                                send_immediate_alert(opp)
                                recent_alerts.append(alert_key)
                                last_alert_time = current_time
                                
                                # Keep only recent alerts
                                if len(recent_alerts) > 10:
                                    recent_alerts = recent_alerts[-10:]
                        
                        # Generate execution guide
                        generate_execution_guide(opportunities)
                        
                        # Save opportunities
                        with open('data/current_15min_opportunities.json', 'w') as f:
                            json.dump({
                                'timestamp': current_time.isoformat(),
                                'scan': scan_count,
                                'current_markets': current_markets,
                                'opportunities': opportunities
                            }, f, indent=2)
                        
                        # Calculate total potential
                        total_potential = sum(opp.get('profit_potential', 0) * POSITION_SIZE / 100 
                                              for opp in opportunities if opp['direction'] != 'BOTH')
                        print(f"\n💰 TOTAL POTENTIAL PROFIT: ${total_potential:.2f}")
                        
                    else:
                        print(f"📊 Current markets found but no trading opportunities")
                else:
                    print(f"📊 No current 15-minute markets found")
                    print(f"💡 Continuing to scan for new markets...")
                
                # Wait for next scan
                time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Manual shutdown - Scanner stopped")
                break
            except Exception as e:
                print(f"❌ Error in scanning loop: {e}")
                time.sleep(30)
        
    except Exception as e:
        print(f"❌ Scanner initialization failed: {e}")

if __name__ == "__main__":
    run_dynamic_15min_scanner()

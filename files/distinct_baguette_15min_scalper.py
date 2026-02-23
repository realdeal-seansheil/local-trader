#!/usr/bin/env python3
"""
Distinct-Baguette Style 15-Minute Crypto Scalper
Replicates the successful Polymarket strategy on Kalshi's 15-minute crypto markets
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
# DISTINCT-BAGUETTE CONFIGURATION
# ============================================================

# 15-Minute Crypto Markets (Exactly what we found!)
CRYPTO_15MIN_MARKETS = [
    'KXBTC15M-26FEB171500-00',  # Bitcoin 15-min up/down
    'KXETH15M-26FEB171500-00',  # Ethereum 15-min up/down
]

# Distinct-Baguette Style Parameters
SCAN_INTERVAL = 10              # 10-second scans (sub-second execution)
POSITION_SIZE = 20             # 20 contracts per trade (aggressive)
MAX_POSITIONS = 5              # Max concurrent positions
MIN_SPREAD = 0.02             # 2 cent minimum spread
TARGET_PROFIT = 0.05           # 5 cent target profit
STOP_LOSS = 0.10              # 10 cent stop loss

# Risk Management
MAX_DAILY_TRADES = 100         # High frequency trading
SESSION_DURATION_HOURS = 4     # Extended session
MIN_VOLUME = 1000             # Minimum volume threshold

# Logging
SCALPER_LOG = "data/distinct_baguette_scalper.jsonl"
POSITIONS_FILE = "data/scalper_positions.json"

# ============================================================
# GLOBAL STATE
# ============================================================

active_positions = {}
daily_stats = {
    "trades_executed": 0,
    "scalping_profits": 0.0,
    "arbitrage_profits": 0.0,
    "total_volume": 0,
    "successful_flips": 0,
    "stopped_out": 0,
    "scans": 0,
    "opportunities": 0
}

# ============================================================
# API FUNCTIONS
# ============================================================

def get_market_data(auth, ticker):
    """Get real-time market data for a specific ticker."""
    try:
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
        resp = requests.get(url, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get('markets', [])
            if markets:
                return markets[0]
        return None
        
    except Exception as e:
        print(f"❌ Error getting market data for {ticker}: {e}")
        return None

def get_orderbook(auth, ticker):
    """Get orderbook data for precise pricing."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/orderbook?ticker={ticker}'
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
            return resp.json()
        return None
        
    except Exception as e:
        print(f"❌ Error getting orderbook for {ticker}: {e}")
        return None

# ============================================================
# DISTINCT-BAGUETTE STRATEGY FUNCTIONS
# ============================================================

def analyze_scalping_opportunities(auth):
    """Analyze 15-minute crypto markets for scalping opportunities."""
    opportunities = []
    
    print("🔍 Analyzing 15-minute crypto scalping opportunities...")
    
    for ticker in CRYPTO_15MIN_MARKETS:
        print(f"\\n📊 Analyzing {ticker}...")
        
        # Get market data
        market = get_market_data(auth, ticker)
        if not market:
            print(f"   ❌ No market data available")
            continue
        
        # Get orderbook for precise pricing
        orderbook = get_orderbook(auth, ticker)
        
        yes_ask = market.get('yes_ask', 0)
        no_ask = market.get('no_ask', 0)
        yes_bid = market.get('yes_bid', 0)
        no_bid = market.get('no_bid', 0)
        volume = market.get('volume', 0)
        
        print(f"   📈 YES: {yes_bid}c/{yes_ask}c")
        print(f"   📈 NO: {no_bid}c/{no_ask}c")
        print(f"   📊 Volume: {volume}")
        
        # Skip if insufficient volume
        if volume < MIN_VOLUME:
            print(f"   ❌ Insufficient volume: {volume} < {MIN_VOLUME}")
            continue
        
        # Distinct-Baguette Strategy 1: Scalping Underpriced Contracts
        if yes_ask > 0 and yes_ask < 50:
            potential_profit = 50 - yes_ask
            confidence = (50 - yes_ask) / 50
            
            if potential_profit >= TARGET_PROFIT * 100:
                opportunities.append({
                    "type": "scalp_yes",
                    "ticker": ticker,
                    "direction": "YES",
                    "entry_price": yes_ask,
                    "target_price": 50,
                    "stop_loss": yes_ask + STOP_LOSS * 100,
                    "potential_profit": potential_profit,
                    "confidence": confidence,
                    "volume": volume,
                    "reasoning": f"Underpriced YES at {yes_ask}c, target 50c"
                })
        
        if no_ask > 0 and no_ask < 50:
            potential_profit = 50 - no_ask
            confidence = (50 - no_ask) / 50
            
            if potential_profit >= TARGET_PROFIT * 100:
                opportunities.append({
                    "type": "scalp_no",
                    "ticker": ticker,
                    "direction": "NO",
                    "entry_price": no_ask,
                    "target_price": 50,
                    "stop_loss": no_ask + STOP_LOSS * 100,
                    "potential_profit": potential_profit,
                    "confidence": confidence,
                    "volume": volume,
                    "reasoning": f"Underpriced NO at {no_ask}c, target 50c"
                })
        
        # Distinct-Baguette Strategy 2: Quick Arbitrage
        if yes_ask > 0 and no_ask > 0:
            combined = (yes_ask + no_ask) / 100
            spread = round(1.0 - combined, 4)
            
            if spread > MIN_SPREAD:
                arbitrage_profit = spread * 100
                
                opportunities.append({
                    "type": "arbitrage",
                    "ticker": ticker,
                    "combined": combined,
                    "spread": spread,
                    "arbitrage_profit": arbitrage_profit,
                    "yes_price": yes_ask,
                    "no_price": no_ask,
                    "volume": volume,
                    "reasoning": f"Arbitrage: {spread:.4f} spread, {arbitrage_profit:.1f}c profit"
                })
        
        # Distinct-Baguette Strategy 3: Momentum Scalping
        if orderbook:
            yes_orders = orderbook.get('orderbook', {}).get('yes', [])
            no_orders = orderbook.get('orderbook', {}).get('no', [])
            
            # Check for order imbalances
            yes_volume = sum(order[1] for order in yes_orders[:5]) if yes_orders else 0
            no_volume = sum(order[1] for order in no_orders[:5]) if no_orders else 0
            
            if yes_volume > no_volume * 2 and yes_ask < 60:
                opportunities.append({
                    "type": "momentum_yes",
                    "ticker": ticker,
                    "direction": "YES",
                    "entry_price": yes_ask,
                    "confidence": min(0.8, yes_volume / (yes_volume + no_volume)),
                    "volume": volume,
                    "order_imbalance": f"YES:{yes_volume} vs NO:{no_volume}",
                    "reasoning": f"Strong YES momentum: {yes_volume} vs {no_volume}"
                })
            
            if no_volume > yes_volume * 2 and no_ask < 60:
                opportunities.append({
                    "type": "momentum_no",
                    "ticker": ticker,
                    "direction": "NO",
                    "entry_price": no_ask,
                    "confidence": min(0.8, no_volume / (yes_volume + no_volume)),
                    "volume": volume,
                    "order_imbalance": f"YES:{yes_volume} vs NO:{no_volume}",
                    "reasoning": f"Strong NO momentum: {no_volume} vs {yes_volume}"
                })
    
    # Sort by confidence/profit
    opportunities.sort(key=lambda x: x.get('confidence', 0) * x.get('potential_profit', 0), reverse=True)
    
    daily_stats["opportunities"] += len(opportunities)
    
    print(f"\\n🎯 SCALPING OPPORTUNITIES FOUND: {len(opportunities)}")
    
    if opportunities:
        print(f"\\n🚀 TOP SCALPING OPPORTUNITIES:")
        for i, opp in enumerate(opportunities[:5]):
            print(f"\\n{i+1}. {opp['ticker']} ({opp.get('type', 'unknown')})")
            print(f"   📊 {opp['reasoning']}")
            if 'potential_profit' in opp:
                print(f"   💰 Entry: {opp['entry_price']}c | Target: {opp['target_price']}c")
                print(f"   📈 Profit: {opp['potential_profit']}c | Confidence: {opp['confidence']:.1%}")
            if 'spread' in opp:
                print(f"   💰 Spread: {opp['spread']:.4f} | Profit: {opp['arbitrage_profit']:.1f}c")
            print(f"   📊 Volume: {opp['volume']}")
    
    return opportunities

def generate_manual_execution_guide(opportunities):
    """Generate manual execution guide for distinct-baguette trading."""
    if not opportunities:
        return
    
    print(f"\\n📋 DISTINCT-BAGUETTE MANUAL EXECUTION GUIDE:")
    print("=" * 70)
    
    top_opps = opportunities[:3]
    
    for i, opp in enumerate(top_opps):
        print(f"\\n{'='*50}")
        print(f"SCALP TRADE #{i+1}: {opp['ticker']}")
        print(f"{'='*50}")
        
        if opp['type'] in ['scalp_yes', 'scalp_no']:
            print(f"📊 Strategy: Quick Scalping")
            print(f"💰 Action: BUY {opp['direction']} contracts")
            print(f"📈 Entry Price: {opp['entry_price']}c")
            print(f"🎯 Target Price: {opp['target_price']}c")
            print(f"🛑 Stop Loss: {opp['stop_loss']:.0f}c")
            print(f"📈 Potential Profit: {opp['potential_profit']}c per contract")
            print(f"🎯 Confidence: {opp['confidence']:.1%}")
            print(f"📊 Volume: {opp['volume']}")
            print(f"💡 Reasoning: {opp['reasoning']}")
            
            print(f"\\n📋 EXECUTION STEPS:")
            print(f"   1. Go to Kalshi and search: {opp['ticker']}")
            print(f"   2. Select {opp['direction']} side")
            print(f"   3. Enter limit order at {opp['entry_price']}c")
            print(f"   4. Size: {POSITION_SIZE} contracts (aggressive)")
            print(f"   5. Set stop-loss at {opp['stop_loss']:.0f}c")
            print(f"   6. Take profit at {opp['target_price']}c")
            print(f"   7. Monitor for 15-minute expiry")
            
        elif opp['type'] == 'arbitrage':
            print(f"📊 Strategy: Arbitrage")
            print(f"💰 Action: BUY both YES and NO")
            print(f"📈 YES Price: {opp['yes_price']}c")
            print(f"📈 NO Price: {opp['no_price']}c")
            print(f"📊 Combined: {opp['combined']:.4f}")
            print(f"💸 Spread: {opp['spread']:.4f}")
            print(f"📈 Profit: {opp['arbitrage_profit']:.1f}c per contract")
            print(f"📊 Volume: {opp['volume']}")
            print(f"💡 Reasoning: {opp['reasoning']}")
            
            print(f"\\n📋 EXECUTION STEPS:")
            print(f"   1. Go to Kalshi and search: {opp['ticker']}")
            print(f"   2. Buy YES at {opp['yes_price']}c ({POSITION_SIZE//2} contracts)")
            print(f"   3. Buy NO at {opp['no_price']}c ({POSITION_SIZE//2} contracts)")
            print(f"   4. Hold until expiry (15 minutes)")
            print(f"   5. Guaranteed profit: ${opp['arbitrage_profit'] * POSITION_SIZE // 200:.2f}")
        
        elif opp['type'] in ['momentum_yes', 'momentum_no']:
            print(f"📊 Strategy: Momentum Scalping")
            print(f"💰 Action: BUY {opp['direction']} contracts")
            print(f"📈 Entry Price: {opp['entry_price']}c")
            print(f"🎯 Confidence: {opp['confidence']:.1%}")
            print(f"📊 Order Imbalance: {opp['order_imbalance']}")
            print(f"📊 Volume: {opp['volume']}")
            print(f"💡 Reasoning: {opp['reasoning']}")
            
            print(f"\\n📋 EXECUTION STEPS:")
            print(f"   1. Go to Kalshi and search: {opp['ticker']}")
            print(f"   2. Select {opp['direction']} side")
            print(f"   3. Enter market order (momentum play)")
            print(f"   4. Size: {POSITION_SIZE} contracts")
            print(f"   5. Quick exit within 5-10 minutes")
            print(f"   6. Target 2-5 cent profit per contract")

# ============================================================
# MAIN SCALPING LOOP
# ============================================================

def run_distinct_baguette_scalper():
    """Run the distinct-baguette style 15-minute crypto scalper."""
    print("=" * 80)
    print("🚀 DISTINCT-BAGUETTE STYLE 15-MINUTE CRYPTO SCALPER")
    print("⚡ High-Frequency Trading on Bitcoin & Ethereum 15-Min Markets")
    print("💰 Replicating Successful Polymarket Strategy")
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
        print(f"🎯 Monitoring {len(CRYPTO_15MIN_MARKETS)} 15-minute crypto markets")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds (sub-second execution)")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        print(f"📊 Target profit: {TARGET_PROFIT*100}c per contract")
        print(f"🛑 Stop loss: {STOP_LOSS*100}c per contract")
        print(f"📈 Max daily trades: {MAX_DAILY_TRADES}")
        
        # Trading loop
        start_time = dt.now()
        end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
        scan_count = 0
        
        print(f"\\n🚀 Starting distinct-baguette scalping session...")
        print(f"⏰ Session ends: {end_time.strftime('%H:%M:%S')}")
        
        while dt.now() < end_time:
            try:
                scan_count += 1
                daily_stats["scans"] = scan_count
                current_time = dt.now()
                elapsed = current_time - start_time
                remaining = end_time - current_time
                
                print(f"\\n{'='*70}")
                print(f"📊 SCAN #{scan_count} | Elapsed: {elapsed.total_seconds()/60:.1f}m | Remaining: {remaining.total_seconds()/60:.1f}m")
                print(f"💰 Trades executed: {daily_stats['trades_executed']}")
                print(f"📈 Scalping profits: {daily_stats['scalping_profits']:.1f}c")
                print(f"💸 Arbitrage profits: {daily_stats['arbitrage_profits']:.1f}c")
                print(f"🎯 Opportunities found: {daily_stats['opportunities']}")
                
                # Check daily trade limit
                if daily_stats["trades_executed"] >= MAX_DAILY_TRADES:
                    print(f"🎯 Daily trade limit reached ({MAX_DAILY_TRADES})")
                    time.sleep(60)
                    continue
                
                # Analyze scalping opportunities
                opportunities = analyze_scalping_opportunities(auth)
                
                if opportunities:
                    # Generate manual execution guide
                    generate_manual_execution_guide(opportunities)
                    
                    # Save opportunities
                    os.makedirs(os.path.dirname(SCALPER_LOG), exist_ok=True)
                    with open(SCALPER_LOG, "a") as f:
                        timestamp = dt.now().isoformat()
                        log_entry = {
                            "timestamp": timestamp,
                            "scan": scan_count,
                            "opportunities": opportunities
                        }
                        f.write(json.dumps(log_entry) + "\\n")
                    
                    print(f"\\n💾 Opportunities logged to: {SCALPER_LOG}")
                    print(f"🎉 READY FOR DISTINCT-BAGUETTE EXECUTION!")
                else:
                    print(f"📊 No scalping opportunities found")
                
                # Wait for next scan (15-minute markets update frequently)
                if dt.now() < end_time:
                    print(f"\\n⚡ Waiting {SCAN_INTERVAL} seconds for next scan...")
                    time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\\n🛑 Manual shutdown")
                break
            except Exception as e:
                print(f"❌ Error in scalping loop: {e}")
                time.sleep(30)
        
        # Final summary
        print(f"\\n{'='*80}")
        print(f"🏁 DISTINCT-BAGUETTE SCALPING SESSION COMPLETE")
        print(f"{'='*80}")
        print(f"📊 Total scans: {scan_count}")
        print(f"📈 Trades executed: {daily_stats['trades_executed']}")
        print(f"💰 Scalping profits: {daily_stats['scalping_profits']:.1f}c")
        print(f"💸 Arbitrage profits: {daily_stats['arbitrage_profits']:.1f}c")
        print(f"🎯 Opportunities found: {daily_stats['opportunities']}")
        print(f"📊 Total volume analyzed: {daily_stats['total_volume']}")
        
        print(f"\\n🎉 DISTINCT-BAGUETTE STRATEGY COMPLETE!")
        print(f"📋 Check the log file for execution opportunities")
        
    except Exception as e:
        print(f"❌ Scalper initialization failed: {e}")

if __name__ == "__main__":
    run_distinct_baguette_scalper()

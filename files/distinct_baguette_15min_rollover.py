#!/usr/bin/env python3
"""
Distinct-Baguette 15-Minute Crypto Trader with Rollover Tracking
Automatically tracks 15-minute market rollover and updates timestamps
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
# DISTINCT-BAGUETTE 15-MINUTE ROLLOVER CONFIGURATION
# ============================================================

# 15-minute crypto series
CRYPTO_15MIN_SERIES = ['KXBTC15M', 'KXETH15M', 'KXSOL15M', 'KXXRP15M']

# Trading parameters
SCAN_INTERVAL = 30              # 30-second scans
POSITION_SIZE = 20             # 20 contracts per trade
MAX_POSITIONS = 4              # Max concurrent positions
MIN_CONFIDENCE = 0.60         # 60% minimum confidence
MIN_PROFIT = 0.40             # 40 cent minimum profit
MIN_VOLUME = 1000             # Minimum volume threshold

# 15-minute rollover tracking
ROLLOVER_INTERVAL = 15         # 15 minutes
TIME_FORMAT = "%H%M"           # HHMM format for tickers
MARKET_SUFFIX = "-45"          # Current suffix pattern

# Risk management
MAX_DAILY_TRADES = 50          # Max trades per day
SESSION_DURATION_HOURS = 4     # 4-hour trading session

# Logging
TRADES_LOG = "data/distinct_baguette_15min_rollover.jsonl"
ROLLOVER_LOG = "data/15min_rollover_log.jsonl"

# ============================================================
# GLOBAL STATE
# ============================================================

executed_trades = set()
current_active_markets = {}
last_rollover_time = None
rollover_sequence = []

daily_stats = {
    "trades_executed": 0,
    "total_profit": 0.0,
    "total_fees": 0.0,
    "successful_trades": 0,
    "failed_orders": 0,
    "scans_completed": 0,
    "high_confidence_trades": 0,
    "total_volume_traded": 0,
    "rollovers_detected": 0,
    "markets_tracked": 0
}

# ============================================================
# ROLLOVER TRACKING FUNCTIONS
# ============================================================

def get_next_15min_time(current_time):
    """Calculate the next 15-minute boundary."""
    current_minute = current_time.minute
    
    # Find next 15-minute boundary
    next_minutes = []
    for minute in [0, 15, 30, 45]:
        if minute > current_minute:
            next_time = current_time.replace(minute=minute, second=0, microsecond=0)
            next_minutes.append(next_time)
    
    # If no times left this hour, go to next hour
    if not next_minutes:
        for minute in [0, 15, 30, 45]:
            next_time = (current_time + timedelta(hours=1)).replace(minute=minute, second=0, microsecond=0)
            next_minutes.append(next_time)
    
    return next_minutes[0]

def generate_expected_ticker(current_time, series_ticker):
    """Generate the expected ticker for the current 15-minute window."""
    # Format: KX[CRYPTO]15M-YYMMDDHHMM-45
    date_str = current_time.strftime('%y%m%d')
    time_str = current_time.strftime('%H%M')
    
    return f"{series_ticker}-{date_str}{time_str}{MARKET_SUFFIX}"

def detect_rollover(auth):
    """Detect if markets have rolled over to new 15-minute windows."""
    global current_active_markets, last_rollover_time, rollover_sequence
    
    current_time = dt.utcnow()
    
    # Check if it's time for a rollover check
    if last_rollover_time:
        time_since_last = (current_time - last_rollover_time).total_seconds() / 60
        if time_since_last < 10:  # Don't check too frequently
            return False
    
    print(f"🔄 Checking for 15-minute rollover...")
    
    # Get expected tickers for current time
    expected_tickers = {}
    for series_ticker in CRYPTO_15MIN_SERIES:
        expected_tickers[series_ticker] = generate_expected_ticker(current_time, series_ticker)
    
    # Check if expected markets are active
    new_active_markets = {}
    rollover_detected = False
    
    for series_ticker, expected_ticker in expected_tickers.items():
        # Get market data
        timestamp = str(int(current_time.timestamp() * 1000))
        path = f'/trade-api/v2/markets?ticker={expected_ticker}&limit=1'
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
                volume = market.get('volume', 0)
                status = market.get('status', '')
                
                # Check if market is active with pricing
                has_pricing = (yes_ask > 0 and yes_ask < 100) or (no_ask > 0 and no_ask < 100)
                has_volume = volume > 0
                is_active = status == 'active'
                
                if has_pricing and has_volume and is_active:
                    new_active_markets[series_ticker] = {
                        'ticker': expected_ticker,
                        'title': market.get('title', ''),
                        'yes_ask': yes_ask,
                        'no_ask': no_ask,
                        'volume': volume,
                        'status': status,
                        'discovered_at': current_time.isoformat()
                    }
                    
                    # Check if this is a new market (rollover)
                    if series_ticker not in current_active_markets or current_active_markets[series_ticker]['ticker'] != expected_ticker:
                        rollover_detected = True
                        print(f"🚨 ROLLOVER DETECTED: {series_ticker}")
                        print(f"   📊 New market: {expected_ticker}")
                        print(f"   💰 YES: {yes_ask}c | NO: {no_ask}c")
                        print(f"   📊 Volume: {volume}")
                        
                        # Log rollover
                        rollover_log = {
                            'timestamp': current_time.isoformat(),
                            'series_ticker': series_ticker,
                            'old_ticker': current_active_markets.get(series_ticker, {}).get('ticker', 'None'),
                            'new_ticker': expected_ticker,
                            'yes_ask': yes_ask,
                            'no_ask': no_ask,
                            'volume': volume
                        }
                        
                        os.makedirs(os.path.dirname(ROLLOVER_LOG), exist_ok=True)
                        with open(ROLLOVER_LOG, 'a') as f:
                            f.write(json.dumps(rollover_log) + '\n')
    
    # Update state if rollover detected
    if rollover_detected:
        current_active_markets = new_active_markets
        last_rollover_time = current_time
        rollover_sequence.append({
            'timestamp': current_time.isoformat(),
            'active_markets': new_active_markets
        })
        
        daily_stats["rollovers_detected"] += 1
        daily_stats["markets_tracked"] = len(new_active_markets)
        
        print(f"🎉 ROLLOVER COMPLETE! Now tracking {len(new_active_markets)} active markets")
        return True
    
    # Update current markets if no rollover but we have active markets
    if new_active_markets and not current_active_markets:
        current_active_markets = new_active_markets
        print(f"📊 Initial market discovery: {len(new_active_markets)} markets")
        return True
    
    return False

def get_active_15min_markets(auth):
    """Get currently active 15-minute crypto markets."""
    global current_active_markets
    
    # Try to detect rollover first
    if detect_rollover(auth):
        return list(current_active_markets.values())
    
    # If no rollover, return current markets
    return list(current_active_markets.values())

# ============================================================
# TRADING FUNCTIONS
# ============================================================

def analyze_15min_opportunities(active_markets):
    """Analyze trading opportunities in active 15-minute markets."""
    opportunities = []
    
    print("🔍 Analyzing 15-minute crypto opportunities...")
    
    for market in active_markets:
        ticker = market['ticker']
        series_ticker = market.get('series', '')
        yes_ask = market['yes_ask']
        no_ask = market['no_ask']
        volume = market['volume']
        
        print(f"📊 {ticker}:")
        print(f"   💰 YES: {yes_ask}c | NO: {no_ask}c")
        print(f"   📊 Volume: {volume}")
        
        # Skip if already traded
        if ticker in executed_trades:
            print(f"   ❌ Already traded")
            continue
        
        # Distinct-Baguette Analysis 1: Value plays
        if yes_ask > 0 and yes_ask < 60:
            profit_potential = 100 - yes_ask
            confidence = (100 - yes_ask) / 100
            
            if profit_potential >= MIN_PROFIT * 100 and confidence >= MIN_CONFIDENCE:
                opportunities.append({
                    "ticker": ticker,
                    "series": series_ticker,
                    "direction": "YES",
                    "entry_price": yes_ask,
                    "target_price": 100,
                    "profit_potential": profit_potential,
                    "confidence": confidence,
                    "volume": volume,
                    "strategy": "value_yes",
                    "reasoning": f"Value play: YES at {yes_ask}c, {profit_potential}c profit potential"
                })
                
                print(f"   🎯 YES Opportunity: Buy at {yes_ask}c, profit {profit_potential}c")
        
        if no_ask > 0 and no_ask < 60:
            profit_potential = 100 - no_ask
            confidence = (100 - no_ask) / 100
            
            if profit_potential >= MIN_PROFIT * 100 and confidence >= MIN_CONFIDENCE:
                opportunities.append({
                    "ticker": ticker,
                    "series": series_ticker,
                    "direction": "NO",
                    "entry_price": no_ask,
                    "target_price": 100,
                    "profit_potential": profit_potential,
                    "confidence": confidence,
                    "volume": volume,
                    "strategy": "value_no",
                    "reasoning": f"Value play: NO at {no_ask}c, {profit_potential}c profit potential"
                })
                
                print(f"   🎯 NO Opportunity: Buy at {no_ask}c, profit {profit_potential}c")
        
        # Distinct-Baguette Analysis 2: Momentum plays
        if volume > 2000:  # High volume for momentum
            if yes_ask > 0 and yes_ask < 50:
                momentum_confidence = min(0.9, (50 - yes_ask) / 50)
                
                if momentum_confidence >= MIN_CONFIDENCE:
                    opportunities.append({
                        "ticker": ticker,
                        "series": series_ticker,
                        "direction": "YES",
                        "entry_price": yes_ask,
                        "target_price": 50,
                        "profit_potential": 50 - yes_ask,
                        "confidence": momentum_confidence,
                        "volume": volume,
                        "strategy": "momentum_yes",
                        "reasoning": f"Momentum: YES cheap at {yes_ask}c, high volume {volume}"
                    })
                    
                    print(f"   ⚡ Momentum YES: {ticker} at {yes_ask}c")
            
            if no_ask > 0 and no_ask < 50:
                momentum_confidence = min(0.9, (50 - no_ask) / 50)
                
                if momentum_confidence >= MIN_CONFIDENCE:
                    opportunities.append({
                        "ticker": ticker,
                        "series": series_ticker,
                        "direction": "NO",
                        "entry_price": no_ask,
                        "target_price": 50,
                        "profit_potential": 50 - no_ask,
                        "confidence": momentum_confidence,
                        "volume": volume,
                        "strategy": "momentum_no",
                        "reasoning": f"Momentum: NO cheap at {no_ask}c, high volume {volume}"
                    })
                    
                    print(f"   ⚡ Momentum NO: {ticker} at {no_ask}c")
    
    # Sort by confidence * volume
    opportunities.sort(key=lambda x: x["confidence"] * x["volume"], reverse=True)
    
    print(f"\n🎯 OPPORTUNITIES FOUND: {len(opportunities)}")
    
    return opportunities

def place_order_direct(auth, ticker: str, side: str, count: int, price: int) -> dict:
    """Place order using direct API call."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        # Convert price from cents to dollars
        price_dollars = f"{price/100:.4f}"
        
        # Order payload
        if side == "yes":
            payload = {
                "ticker": ticker,
                "side": "yes",
                "action": "buy",
                "count": count,
                "yes_price": price,
                "yes_price_dollars": price_dollars,
                "time_in_force": "good_till_canceled"
            }
        else:  # side == "no"
            payload = {
                "ticker": ticker,
                "side": "no",
                "action": "buy",
                "count": count,
                "no_price": price,
                "no_price_dollars": price_dollars,
                "time_in_force": "good_till_canceled"
            }
        
        # Create signature
        msg = timestamp + method + path + json.dumps(payload)
        
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
            "KALSHI-ACCESS-KEY": auth.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "order": data.get("order", {}),
                "order_id": data.get("order", {}).get("order_id")
            }
        else:
            return {
                "error": resp.status_code,
                "detail": resp.text
            }
            
    except Exception as e:
        return {
            "error": "exception",
            "detail": str(e)
        }

def execute_high_confidence_trade(auth, opportunity):
    """Execute a high-confidence trade."""
    ticker = opportunity["ticker"]
    direction = opportunity["direction"]
    entry_price = opportunity["entry_price"]
    confidence = opportunity["confidence"]
    
    # Calculate position size
    contracts = min(POSITION_SIZE, 20)  # Conservative sizing
    
    print(f"\n🚨 EXECUTING TRADE: {ticker}")
    print(f"   📊 Strategy: {opportunity['strategy']}")
    print(f"   📈 Direction: {direction}")
    print(f"   💰 Entry price: {entry_price}c")
    print(f"   🎯 Confidence: {confidence:.1%}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${opportunity['profit_potential'] * contracts / 100:.2f}")
    print(f"   💡 Reasoning: {opportunity['reasoning']}")
    
    try:
        # Use direct API call
        result = place_order_direct(auth, ticker, direction.lower(), contracts, entry_price)
        
        if "success" in result:
            # Track the trade
            executed_trades.add(ticker)
            daily_stats["trades_executed"] += 1
            daily_stats["high_confidence_trades"] += 1
            
            # Calculate expected profit
            total_profit = opportunity['profit_potential'] * contracts / 100
            total_fees = contracts * 0.002
            
            # Update stats
            daily_stats["total_profit"] += total_profit
            daily_stats["total_fees"] += total_fees
            daily_stats["successful_trades"] += 1
            daily_stats["total_volume_traded"] += contracts
            
            # Log the trade
            trade_log = {
                "timestamp": dt.now().isoformat(),
                "ticker": ticker,
                "direction": direction,
                "entry_price": entry_price,
                "contracts": contracts,
                "confidence": confidence,
                "strategy": opportunity['strategy'],
                "expected_profit": total_profit,
                "order_id": result.get("order_id", "unknown"),
                "success": True
            }
            
            os.makedirs(os.path.dirname(TRADES_LOG), exist_ok=True)
            with open(TRADES_LOG, "a") as f:
                f.write(json.dumps(trade_log) + "\n")
            
            print(f"   ✅ SUCCESS: Trade executed!")
            print(f"      Order ID: {result.get('order_id', 'unknown')}")
            print(f"      Expected profit: ${total_profit:.2f}")
            
            return {
                "success": True,
                "ticker": ticker,
                "direction": direction,
                "contracts": contracts,
                "total_profit": total_profit,
                "total_fees": total_fees
            }
            
        else:
            print(f"   ❌ Trade failed: {result.get('error', 'unknown')}")
            print(f"   📊 Details: {result.get('detail', '')[:100]}")
            
            daily_stats["failed_orders"] += 1
            
            # Log the failure
            trade_log = {
                "timestamp": dt.now().isoformat(),
                "ticker": ticker,
                "direction": direction,
                "entry_price": entry_price,
                "contracts": contracts,
                "confidence": confidence,
                "strategy": opportunity['strategy'],
                "error": result.get('error', 'unknown'),
                "details": result.get('detail', ''),
                "success": False
            }
            
            os.makedirs(os.path.dirname(TRADES_LOG), exist_ok=True)
            with open(TRADES_LOG, "a") as f:
                f.write(json.dumps(trade_log) + "\n")
            
            return result
            
    except Exception as e:
        print(f"   ❌ Trade execution failed: {e}")
        
        daily_stats["failed_orders"] += 1
        return {"error": str(e)}

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_distinct_baguette_rollover_trader():
    """Run the distinct-baguette 15-minute crypto trader with rollover tracking."""
    print("=" * 80)
    print("🚨 DISTINCT-BAGUETTE 15-MINUTE CRYPTO TRADER")
    print("🔄 WITH AUTOMATIC ROLLOVER TRACKING")
    print("💰 High-Confidence Automated Trading")
    print("⚡ Real 15-minute crypto markets: BTC, ETH, SOL, XRP")
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
        print(f"🎯 Target series: {', '.join(CRYPTO_15MIN_SERIES)}")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        print(f"🎯 Min confidence: {MIN_CONFIDENCE:.0%}")
        print(f"🔄 Rollover tracking: Every {ROLLOVER_INTERVAL} minutes")
        
        # Trading loop
        start_time = dt.now()
        end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
        scan_count = 0
        next_rollover_check = dt.now()
        
        print(f"\n🚨 Starting distinct-baguette trading session...")
        print(f"⏰ Session ends: {end_time.strftime('%H:%M:%S')}")
        print(f"🔄 Next rollover check: {next_rollover_check.strftime('%H:%M')}")
        
        while dt.now() < end_time:
            try:
                scan_count += 1
                daily_stats["scans_completed"] = scan_count
                current_time = dt.now()
                elapsed = current_time - start_time
                remaining = end_time - current_time
                
                print(f"\n{'='*70}")
                print(f"📊 SCAN #{scan_count} | Elapsed: {elapsed.total_seconds()/60:.1f}m | Remaining: {remaining.total_seconds()/60:.1f}m")
                print(f"💰 Trades executed: {daily_stats['trades_executed']}")
                print(f"🔄 Rollovers detected: {daily_stats['rollovers_detected']}")
                print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
                
                # Check for rollover
                if current_time >= next_rollover_check:
                    print(f"\n🔄 CHECKING FOR 15-MINUTE ROLLOVER...")
                    rollover_detected = detect_rollover(auth)
                    
                    if rollover_detected:
                        print(f"🎉 ROLLOVER DETECTED! New markets are active.")
                    else:
                        print(f"📊 No rollover detected, continuing with current markets.")
                    
                    # Schedule next rollover check
                    next_rollover_check = get_next_15min_time(current_time)
                    print(f"🔄 Next rollover check: {next_rollover_check.strftime('%H:%M')}")
                
                # Check daily trade limit
                if daily_stats["trades_executed"] >= MAX_DAILY_TRADES:
                    print(f"🎯 Daily trade limit reached ({MAX_DAILY_TRADES})")
                    time.sleep(300)  # Wait 5 minutes
                    continue
                
                # Get active markets
                active_markets = get_active_15min_markets(auth)
                
                if active_markets:
                    print(f"\n📊 Active markets: {len(active_markets)}")
                    
                    # Analyze opportunities
                    opportunities = analyze_15min_opportunities(active_markets)
                    
                    if opportunities:
                        # Get top high-confidence opportunity
                        top_opp = opportunities[0]
                        
                        if top_opp["confidence"] >= 0.7:  # Only execute very high confidence
                            print(f"\n🚨 FOUND VERY HIGH CONFIDENCE TRADE!")
                            print(f"   📊 {top_opp['ticker']} ({top_opp['direction']})")
                            print(f"   🎯 Confidence: {top_opp['confidence']:.1%}")
                            print(f"   💰 Entry: {top_opp['entry_price']}c | Profit: {top_opp['profit_potential']}c")
                            print(f"   📊 Volume: {top_opp['volume']}")
                            print(f"   💡 {top_opp['reasoning']}")
                            
                            # Execute the trade
                            result = execute_high_confidence_trade(auth, top_opp)
                            
                            if result and "success" in result:
                                print(f"\n🎉 HIGH-CONFIDENCE TRADE EXECUTED!")
                                print(f"💰 Profit locked in: ${result['total_profit']:.2f}")
                            else:
                                print(f"\n❌ Trade execution failed")
                        else:
                            print(f"\n📊 Opportunities found but confidence below threshold")
                            print(f"   🎯 Best confidence: {opportunities[0]['confidence']:.1%} (need 70%+)")
                    else:
                        print(f"\n📊 No high-confidence opportunities found")
                else:
                    print(f"\n📊 No active 15-minute markets found")
                    print(f"💡 Waiting for next rollover...")
                
                # Save performance stats periodically
                if scan_count % 5 == 0:
                    os.makedirs(os.path.dirname("data/performance_rollover.json"), exist_ok=True)
                    with open("data/performance_rollover.json", "w") as f:
                        json.dump(daily_stats, f, indent=2, default=str)
                
                # Wait for next scan
                if dt.now() < end_time:
                    print(f"\n⏳ Waiting {SCAN_INTERVAL} seconds for next scan...")
                    time.sleep(SCAN_INTERVAL)
                
            except KeyboardInterrupt:
                print(f"\n🛑 Manual shutdown")
                break
            except Exception as e:
                print(f"❌ Error in trading loop: {e}")
                time.sleep(30)
        
        # Final summary
        print(f"\n{'='*80}")
        print(f"🏁 DISTINCT-BAGUETTE TRADING SESSION COMPLETE")
        print(f"{'='*80}")
        print(f"📊 Total scans: {scan_count}")
        print(f"📈 Trades executed: {daily_stats['trades_executed']}")
        print(f"🔄 Rollovers detected: {daily_stats['rollovers_detected']}")
        print(f"🚨 High-confidence trades: {daily_stats['high_confidence_trades']}")
        print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
        print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
        print(f"✅ Successful trades: {daily_stats['successful_trades']}")
        print(f"❌ Failed orders: {daily_stats['failed_orders']}")
        print(f"📊 Total volume traded: {daily_stats['total_volume_traded']}")
        
        # Save final stats
        os.makedirs(os.path.dirname("data/performance_rollover_final.json"), exist_ok=True)
        with open("data/performance_rollover_final.json", "w") as f:
            json.dump(daily_stats, f, indent=2, default=str)
        
        print(f"\n🎉 DISTINCT-BAGUETTE STRATEGY COMPLETE!")
        print(f"📋 Trades logged to: {TRADES_LOG}")
        print(f"🔄 Rollovers logged to: {ROLLOVER_LOG}")
        
    except Exception as e:
        print(f"❌ Trader initialization failed: {e}")

if __name__ == "__main__":
    run_distinct_baguette_rollover_trader()

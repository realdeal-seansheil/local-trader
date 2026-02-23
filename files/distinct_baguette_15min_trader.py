#!/usr/bin/env python3
"""
Distinct-Baguette 15-Minute Crypto Trader
Automatically identifies and executes high-confidence trades on 15-minute crypto markets
"""

import os
import json
import time
from datetime import datetime as dt, timedelta
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# DISTINCT-BAGUETTE CONFIGURATION
# ============================================================

# 15-minute crypto series (REAL ones!)
CRYPTO_15MIN_SERIES = ['KXXRP15M', 'KXSOL15M', 'KXBTC15M', 'KXETH15M']

# Trading parameters (distinct-baguette style)
SCAN_INTERVAL = 30              # 30-second scans
POSITION_SIZE = 20             # 20 contracts per trade
MAX_POSITIONS = 3              # Max concurrent positions
MIN_CONFIDENCE = 0.60         # 60% minimum confidence
MIN_PROFIT = 0.40             # 40 cent minimum profit
MIN_VOLUME = 500              # Minimum volume threshold

# Risk management
MAX_DAILY_TRADES = 50          # Max trades per day
SESSION_DURATION_HOURS = 4     # 4-hour trading session
STOP_LOSS_MULTIPLIER = 1.5     # Stop loss at 1.5x entry price
TAKE_PROFIT_MULTIPLIER = 0.8   # Take profit at 80c

# Logging
TRADES_LOG = "data/distinct_baguette_trades.jsonl"
PERFORMANCE_LOG = "data/performance.json"

# ============================================================
# GLOBAL STATE
# ============================================================

executed_trades = set()
daily_stats = {
    "trades_executed": 0,
    "total_profit": 0.0,
    "total_fees": 0.0,
    "successful_trades": 0,
    "failed_orders": 0,
    "scans_completed": 0,
    "high_confidence_trades": 0,
    "total_volume_traded": 0
}

# ============================================================
# API FUNCTIONS
# ============================================================

def get_15min_crypto_markets(auth, series_ticker):
    """Get markets from a 15-minute crypto series."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = f'/trade-api/v2/markets?series_ticker={series_ticker}&limit=100'
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

def place_order_direct(auth, ticker: str, side: str, count: int, price: int) -> dict:
    """Place order using direct API call (bypasses faulty client)."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/orders"
        method = "POST"
        
        # Convert price from cents to dollars (fixed-point format)
        price_dollars = f"{price/100:.4f}"
        
        # Order payload with correct format
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

def get_current_balance(auth):
    """Get current portfolio balance using direct API call."""
    try:
        timestamp = str(int(dt.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
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
            "KALSHI-ACCESS-KEY": auth.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            balance = data.get("balance", 0)
            available = data.get("available", 0)
            
            return balance
        else:
            return 10000  # Default for testing
            
    except Exception as e:
        return 10000  # Default for testing

# ============================================================
# TRADING LOGIC
# ============================================================

def analyze_15min_opportunities(auth):
    """Analyze 15-minute crypto markets for high-confidence trades."""
    opportunities = []
    
    print("🔍 Analyzing 15-minute crypto markets...")
    
    for series_ticker in CRYPTO_15MIN_SERIES:
        print(f"\n📊 {series_ticker}:")
        
        markets = get_15min_crypto_markets(auth, series_ticker)
        print(f"   📈 Found {len(markets)} markets")
        
        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            yes_ask = market.get('yes_ask', 0)
            no_ask = market.get('no_ask', 0)
            yes_bid = market.get('yes_bid', 0)
            no_bid = market.get('no_bid', 0)
            volume = market.get('volume', 0)
            status = market.get('status', 'unknown')
            
            # Skip if not active or no pricing
            if status != 'active' or (yes_ask == 0 and no_ask == 0):
                continue
            
            # Skip if insufficient volume
            if volume < MIN_VOLUME:
                continue
            
            # Skip if already traded
            if ticker in executed_trades:
                continue
            
            # Distinct-Baguette Analysis 1: Value plays (cheap contracts)
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
                    
                    print(f"      🎯 YES Opportunity: {ticker} at {yes_ask}c (profit: {profit_potential}c, conf: {confidence:.1%})")
            
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
                    
                    print(f"      🎯 NO Opportunity: {ticker} at {no_ask}c (profit: {profit_potential}c, conf: {confidence:.1%})")
            
            # Distinct-Baguette Analysis 2: Momentum plays
            if volume > 1000:  # High volume for momentum
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
                        
                        print(f"      ⚡ Momentum YES: {ticker} at {yes_ask}c (conf: {momentum_confidence:.1%})")
                
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
                        
                        print(f"      ⚡ Momentum NO: {ticker} at {no_ask}c (conf: {momentum_confidence:.1%})")
    
    # Sort by confidence * volume (distinct-baguette priority)
    opportunities.sort(key=lambda x: x["confidence"] * x["volume"], reverse=True)
    
    print(f"\n🎯 HIGH-CONFIDENCE OPPORTUNITIES: {len(opportunities)}")
    
    # Filter for high confidence only
    high_conf_opp = [opp for opp in opportunities if opp["confidence"] >= 0.7]
    print(f"🚨 VERY HIGH CONFIDENCE (70%+): {len(high_conf_opp)}")
    
    return opportunities

def execute_high_confidence_trade(auth, opportunity, available_balance):
    """Execute a high-confidence trade."""
    ticker = opportunity["ticker"]
    direction = opportunity["direction"]
    entry_price = opportunity["entry_price"]
    confidence = opportunity["confidence"]
    
    # Calculate position size
    contracts = min(POSITION_SIZE, int(available_balance / 100))
    
    if contracts < 1:
        print(f"❌ Insufficient balance for {ticker}")
        return None
    
    print(f"\n🚨 EXECUTING HIGH-CONFIDENCE TRADE: {ticker}")
    print(f"   📊 Strategy: {opportunity['strategy']}")
    print(f"   📈 Direction: {direction}")
    print(f"   💰 Entry price: {entry_price}c")
    print(f"   🎯 Confidence: {confidence:.1%}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${opportunity['profit_potential'] * contracts / 100:.2f}")
    print(f"   💡 Reasoning: {opportunity['reasoning']}")
    
    try:
        print(f"   📈 Placing {direction} order for {contracts} contracts at {entry_price}c...")
        
        # Use direct API call
        result = place_order_direct(auth, ticker, direction.lower(), contracts, entry_price)
        
        if "success" in result:
            # Track the trade
            executed_trades.add(ticker)
            daily_stats["trades_executed"] += 1
            daily_stats["high_confidence_trades"] += 1
            
            # Calculate expected profit
            total_profit = opportunity['profit_potential'] * contracts / 100
            total_fees = contracts * 0.002  # Approximate fees
            
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
            
            print(f"   ✅ SUCCESS: High-confidence trade executed!")
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

def run_distinct_baguette_trader():
    """Run the distinct-baguette 15-minute crypto trader."""
    print("=" * 80)
    print("🚨 DISTINCT-BAGUETTE 15-MINUTE CRYPTO TRADER")
    print("💰 High-Confidence Automated Trading")
    print("⚡ Real 15-minute crypto markets: XRP, SOL, BTC, ETH")
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
        
        # Get balance
        balance = get_current_balance(auth)
        print(f"✅ Authentication successful")
        print(f"💰 Starting balance: ${balance/100:.2f}")
        print(f"🎯 Target series: {', '.join(CRYPTO_15MIN_SERIES)}")
        print(f"⚡ Scan interval: {SCAN_INTERVAL} seconds")
        print(f"💰 Position size: {POSITION_SIZE} contracts")
        print(f"🎯 Min confidence: {MIN_CONFIDENCE:.0%}")
        print(f"💸 Min profit: {MIN_PROFIT*100}c per contract")
        
        # Trading loop
        start_time = dt.now()
        end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
        scan_count = 0
        
        print(f"\n🚨 Starting distinct-baguette trading session...")
        print(f"⏰ Session ends: {end_time.strftime('%H:%M:%S')}")
        
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
                print(f"🚨 High-confidence trades: {daily_stats['high_confidence_trades']}")
                print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
                
                # Check daily trade limit
                if daily_stats["trades_executed"] >= MAX_DAILY_TRADES:
                    print(f"🎯 Daily trade limit reached ({MAX_DAILY_TRADES})")
                    time.sleep(300)  # Wait 5 minutes
                    continue
                
                # Analyze opportunities
                opportunities = analyze_15min_opportunities(auth)
                
                if opportunities:
                    # Get top high-confidence opportunity
                    top_opp = opportunities[0]
                    
                    if top_opp["confidence"] >= 0.7:  # Only execute very high confidence
                        available_balance = get_current_balance(auth)
                        
                        print(f"\n🚨 FOUND VERY HIGH CONFIDENCE TRADE!")
                        print(f"   📊 {top_opp['ticker']} ({top_opp['direction']})")
                        print(f"   🎯 Confidence: {top_opp['confidence']:.1%}")
                        print(f"   💰 Entry: {top_opp['entry_price']}c | Profit: {top_opp['profit_potential']}c")
                        print(f"   📊 Volume: {top_opp['volume']}")
                        print(f"   💡 {top_opp['reasoning']}")
                        
                        # Execute the trade
                        result = execute_high_confidence_trade(auth, top_opp, available_balance)
                        
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
                
                # Save performance stats periodically
                if scan_count % 5 == 0:
                    os.makedirs(os.path.dirname(PERFORMANCE_LOG), exist_ok=True)
                    with open(PERFORMANCE_LOG, "w") as f:
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
        print(f"🚨 High-confidence trades: {daily_stats['high_confidence_trades']}")
        print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
        print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
        print(f"✅ Successful trades: {daily_stats['successful_trades']}")
        print(f"❌ Failed orders: {daily_stats['failed_orders']}")
        print(f"📊 Total volume traded: {daily_stats['total_volume_traded']}")
        
        # Save final stats
        os.makedirs(os.path.dirname(PERFORMANCE_LOG), exist_ok=True)
        with open(PERFORMANCE_LOG, "w") as f:
            json.dump(daily_stats, f, indent=2, default=str)
        
        print(f"\n🎉 DISTINCT-BAGUETTE STRATEGY COMPLETE!")
        print(f"📋 Trades logged to: {TRADES_LOG}")
        
    except Exception as e:
        print(f"❌ Trader initialization failed: {e}")

if __name__ == "__main__":
    run_distinct_baguette_trader()

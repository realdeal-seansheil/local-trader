#!/usr/bin/env python3
"""
Conservative 48-Hour Trading Bot
Reverted to the original marginally effective strategy (+$30 in 18 hrs)
"""

import os
import json
import time
import signal
import sys
from datetime import datetime, timedelta
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, USE_DEMO
from order_manager import ArbitrageOrderManager

# ============================================================
# CONSERVATIVE TRADING CONFIGURATION
# ============================================================

# Trading Parameters - CONSERVATIVE SETTINGS
SCAN_INTERVAL = 30              # Seconds between scans (30 seconds - conservative)
AUTO_EXECUTE = True              # Enable automatic execution
MAX_CONTRACTS_PER_TRADE = 10     # Position size per arbitrage (REDUCED for safety)
MIN_PROFIT_THRESHOLD = 0.05     # Minimum 5 cents profit per contract
MAX_DAILY_TRADES_TARGET = 20     # Target trades per day (REDUCED)
SESSION_DURATION_HOURS = 48      # Total runtime

# Risk Management
MAX_CONCURRENT_POSITIONS = 3     # Max simultaneous arbitrage positions (REDUCED)
TRACK_EXECUTED_TRADES = True    # Prevent duplicate executions
MIN_LIQUIDITY_THRESHOLD = 10    # Minimum 10 bids on each side (INCREASED safety)

# Order Management - CONSERVATIVE
ORDER_MAX_WAIT_HOURS = 7        # Maximum hours to wait for fills
ORDER_UPGRADE_INTERVALS = [2, 5, 7]  # Hours when to upgrade price (LESS frequent)
DYNAMIC_PRICING_ENABLED = True    # Enable dynamic pricing strategy

# Conservative Strategy Features
FILL_RATE_MONITORING = True       # Monitor actual fill rates
BASE_ORDER_PRICE = 1              # Base price in cents (CONSERVATIVE)
MAX_ORDER_PRICE = 5               # Maximum price in cents (LIMITED)
PRICE_UPGRADE_STEP = 1            # Price increase per upgrade (cents)
MIN_FILL_RATE_THRESHOLD = 0.2    # Minimum fill rate before price adjustment (LOWER threshold)

# Logging
LOG_FILE = "data/conservative_48hour_trading.jsonl"
POSITIONS_FILE = "data/conservative_positions.json"
PERFORMANCE_FILE = "data/conservative_performance.json"

# ============================================================
# GLOBAL STATE
# ============================================================

executed_trades = set()
daily_stats = {
    "trades_executed": 0,
    "total_profit": 0.0,
    "total_fees": 0.0,
    "successful_arbs": 0,
    "failed_orders": 0
}

# ============================================================
# LOGGING FUNCTIONS
# ============================================================

def log_event(event_type, data):
    """Log events to JSONL file."""
    timestamp = datetime.now().isoformat()
    log_entry = {
        "timestamp": timestamp,
        "type": event_type,
        "data": data
    }
    
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

def save_performance_stats():
    """Save performance statistics."""
    os.makedirs(os.path.dirname(PERFORMANCE_FILE), exist_ok=True)
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(daily_stats, f, indent=2, default=str)

def load_performance_stats():
    """Load existing performance statistics."""
    try:
        if os.path.exists(PERFORMANCE_FILE):
            with open(PERFORMANCE_FILE, "r") as f:
                return json.load(f)
    except:
        pass
    return daily_stats

# ============================================================
# POSITION MANAGEMENT
# ============================================================

def save_positions(positions):
    """Save active positions to file."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)

def get_active_positions():
    """Load active positions from file."""
    try:
        if os.path.exists(POSITIONS_FILE):
            with open(POSITIONS_FILE, "r") as f:
                positions = json.load(f)
                return positions if positions is not None else {}
    except:
        pass
    return {}

def update_position_status(ticker, status, profit=None):
    """Update position status."""
    positions = get_active_positions()
    if ticker in positions:
        positions[ticker]["status"] = status
        positions[ticker]["updated"] = datetime.now().isoformat()
        if profit is not None:
            positions[ticker]["profit"] = profit
        save_positions(positions)

# ============================================================
# TRADING FUNCTIONS
# ============================================================

def check_portfolio_balance(client):
    """Check portfolio balance - use total balance instead of available."""
    try:
        # Use direct API call with correct URL
        import requests
        import datetime
        import base64
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        
        timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
        path = "/trade-api/v2/portfolio/balance"
        method = "GET"
        
        msg = timestamp + method + path
        
        sig_bytes = client.auth.private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        signature = base64.b64encode(sig_bytes).decode()
        
        headers = {
            "KALSHI-ACCESS-KEY": client.auth.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
        
        url = "https://api.elections.kalshi.com" + path
        resp = requests.get(url, headers=headers, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            # Use total balance instead of available
            total_balance = data.get("balance", 0)
            available = data.get("available", 0)
            
            log_event("balance_check", {
                "total_balance": total_balance, 
                "available": available,
                "using_total": True
            })
            
            print(f"✅ Balance check: ${total_balance/100:.2f} total, ${available/100:.2f} available")
            print(f"🚀 Using total balance for trading: ${total_balance/100:.2f}")
            return total_balance
        else:
            print(f"❌ Balance check failed: {resp.status_code} - {resp.text}")
            return 0
            
    except Exception as e:
        print(f"❌ Balance check error: {e}")
        return 0

def execute_arbitrage(executor, opportunity, available_balance):
    """Execute an arbitrage opportunity with conservative pricing."""
    ticker = opportunity["ticker"]
    
    # Check if already executed
    if ticker in executed_trades:
        log_event("duplicate_skipped", {"ticker": ticker})
        return None
    
    # Check liquidity
    yes_bids = opportunity.get("yes_bids", 0)
    no_bids = opportunity.get("no_bids", 0)
    
    if yes_bids < MIN_LIQUIDITY_THRESHOLD or no_bids < MIN_LIQUIDITY_THRESHOLD:
        log_event("insufficient_liquidity", {
            "ticker": ticker,
            "yes_bids": yes_bids,
            "no_bids": no_bids,
            "threshold": MIN_LIQUIDITY_THRESHOLD
        })
        return None
    
    # Calculate position size
    contracts = min(MAX_CONTRACTS_PER_TRADE, int(available_balance / 100))
    
    if contracts < 1:
        log_event("insufficient_balance", {
            "ticker": ticker,
            "available_balance": available_balance,
            "required": 100
        })
        return None
    
    print(f"\n🎯 EXECUTING ARBITRAGE: {ticker}")
    print(f"   📊 YES Bids: {yes_bids} | NO Bids: {no_bids}")
    print(f"   💰 Profit per contract: ${opportunity['net_profit_per_contract']:.4f}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${opportunity['net_profit_per_contract'] * contracts:.2f}")
    
    # Place orders using conservative pricing
    try:
        # Use conservative base price
        yes_price = BASE_ORDER_PRICE
        no_price = BASE_ORDER_PRICE
        
        print(f"   📈 Placing orders at {yes_price}c each (CONSERVATIVE)...")
        
        # Place YES order
        yes_result = executor.place_order(ticker, "yes", yes_price, contracts)
        
        if "error" in yes_result:
            log_event("execution_failed", {
                "ticker": ticker,
                "error": f"YES order failed: {yes_result['error']}"
            })
            print(f"   ❌ YES order failed: {yes_result['error']}")
            return yes_result
        
        # Place NO order
        no_result = executor.place_order(ticker, "no", no_price, contracts)
        
        if "error" in no_result:
            log_event("execution_failed", {
                "ticker": ticker,
                "error": f"NO order failed: {no_result['error']}"
            })
            print(f"   ❌ NO order failed: {no_result['error']}")
            return no_result
        
        # Track the arbitrage
        executed_trades.add(ticker)
        daily_stats["trades_executed"] += 1
        
        # Calculate expected profit
        total_profit = opportunity['net_profit_per_contract'] * contracts
        total_fees = opportunity.get('total_fees_per_contract', 0) * contracts
        
        # Save position
        position = {
            "ticker": ticker,
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "contracts": contracts,
            "yes_price": yes_price,
            "no_price": no_price,
            "expected_profit": total_profit,
            "total_fees": total_fees,
            "status": "active",
            "created": datetime.now().isoformat(),
            "strategy": "conservative"
        }
        
        positions = get_active_positions()
        positions[ticker] = position
        save_positions(positions)
        
        # Update stats
        daily_stats["total_profit"] += total_profit
        daily_stats["total_fees"] += total_fees
        daily_stats["successful_arbs"] += 1
        
        log_event("execution_success", {
            "ticker": ticker,
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees,
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "strategy": "conservative",
            "initial_prices": {"yes": yes_price, "no": no_price}
        })
        
        print(f"   ✅ SUCCESS: Orders placed")
        print(f"      YES Order ID: {yes_result.get('order', {}).get('order_id')}")
        print(f"      NO Order ID: {no_result.get('order', {}).get('order_id')}")
        print(f"      Expected profit: ${total_profit:.2f}")
        
        return {
            "success": True,
            "ticker": ticker,
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees
        }
        
    except Exception as e:
        log_event("execution_exception", {
            "ticker": ticker,
            "error": str(e)
        })
        print(f"   ❌ Execution failed: {e}")
        return {"error": str(e)}

def scan_opportunities(executor):
    """Scan for arbitrage opportunities using the same scanner as original bot."""
    try:
        # Find opportunities using the same method as original bot
        opportunities = executor.find_arb_opportunities()
        
        # Handle None response
        if opportunities is None:
            log_event("scan_no_opportunities", {"scans": daily_stats["scans"]})
            print(f"   ⚠️  No opportunities returned from scanner")
            return []
        
        daily_stats["opportunities_found"] += len(opportunities)
        
        if not opportunities:
            log_event("scan_no_opportunities", {"scans": daily_stats["scans"]})
            print(f"   ⚠️  No profitable opportunities found")
            return []
        
        log_event("scan_opportunities", {
            "count": len(opportunities),
            "top_spread": opportunities[0].get("spread", 0)
        })
        
        print(f"\n📊 Found {len(opportunities)} profitable opportunities")
        
        # Show top 3
        for i, opp in enumerate(opportunities[:3]):
            ticker = opp.get("ticker", "Unknown")
            spread = opp.get("spread", 0)
            net_profit = opp.get("net_profit_per_contract", 0)
            fees = opp.get("total_fees_per_contract", 0)
            roi = opp.get("roi_net_percent", 0)
            
            print(f"   {i+1}. {ticker}: {spread} spread")
            print(f"      Net profit: ${net_profit:.4f} | Fees: ${fees:.4f} | ROI: {roi:.1f}%")
        
        return opportunities
        
    except Exception as e:
        log_event("scan_error", {"error": str(e)})
        print(f"   ❌ Scan error: {e}")
        import traceback
        print(f"   🐛 Traceback: {traceback.format_exc()}")
        return []

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_conservative_bot():
    """Run the conservative 48-hour trading bot."""
    print("=" * 80)
    print("🐢 CONSERVATIVE 48-HOUR TRADING BOT")
    print("🎯 Reverted to Original Marginally Effective Strategy")
    print("=" * 80)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        print("export KALSHI_API_KEY_ID='your-api-key-id'")
        return
    
    # Initialize trading components
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        client = KalshiClient(auth)
        executor = StrategyExecutor(client)
        order_manager = ArbitrageOrderManager(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication
        balance = check_portfolio_balance(client)
        if balance == 0:
            print("❌ Authentication failed or no balance")
            return
            
        print(f"✅ Authentication successful")
        print(f"💰 Starting balance: ${balance/100:.2f}")
        
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        return
    
    # Load existing stats
    global daily_stats
    daily_stats = load_performance_stats()
    
    # Setup signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print(f"\n🛑 Graceful shutdown initiated...")
        save_performance_stats()
        print(f"📊 Final stats: {daily_stats}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Trading loop
    start_time = datetime.now()
    end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
    scan_count = 0
    
    print(f"🚀 Starting trading session")
    print(f"⏰ Duration: {SESSION_DURATION_HOURS} hours")
    print(f"📊 Scan interval: {SCAN_INTERVAL} seconds")
    print(f"💰 Max contracts per trade: {MAX_CONTRACTS_PER_TRADE}")
    print(f"🎯 Base order price: {BASE_ORDER_PRICE}c")
    print(f"📈 Session ends: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    while datetime.now() < end_time:
        try:
            scan_count += 1
            current_time = datetime.now()
            elapsed = current_time - start_time
            remaining = end_time - current_time
            
            print(f"\n{'='*60}")
            print(f"📊 Scan #{scan_count} | Elapsed: {elapsed.total_seconds()/3600:.1f}h | Remaining: {remaining.total_seconds()/3600:.1f}h")
            print(f"💰 Current balance: ${check_portfolio_balance(client)/100:.2f}")
            print(f"📈 Trades executed: {daily_stats['trades_executed']}")
            print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
            
            # Check daily trade limit
            if daily_stats["trades_executed"] >= MAX_DAILY_TRADES_TARGET:
                print(f"🎯 Daily trade target reached ({MAX_DAILY_TRADES_TARGET})")
                time.sleep(300)  # Wait 5 minutes
                continue
            
            # Scan for opportunities
            opportunities = scan_opportunities(executor)
            
            if not opportunities:
                print(f"📊 No profitable opportunities found")
            else:
                print(f"🎯 Found {len(opportunities)} opportunities")
                
                # Execute best opportunity
                best_opp = opportunities[0]
                available_balance = check_portfolio_balance(client)
                
                # Check concurrent positions limit
                active_positions = get_active_positions()
                active_count = len([p for p in active_positions.values() if p.get("status") == "active"])
                
                if active_count < MAX_CONCURRENT_POSITIONS:
                    result = execute_arbitrage(executor, best_opp, available_balance)
                    
                    if result and "success" in result:
                        print(f"🎉 Arbitrage executed successfully!")
                    else:
                        print(f"❌ Arbitrage execution failed")
                        daily_stats["failed_orders"] += 1
                else:
                    print(f"📊 Max concurrent positions reached ({MAX_CONCURRENT_POSITIONS})")
            
            # Save performance stats periodically
            if scan_count % 10 == 0:
                save_performance_stats()
            
            # Wait for next scan
            print(f"⏳ Waiting {SCAN_INTERVAL} seconds...")
            time.sleep(SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            print(f"\n🛑 Manual shutdown")
            break
        except Exception as e:
            print(f"❌ Error in trading loop: {e}")
            log_event("loop_error", {"error": str(e)})
            time.sleep(60)  # Wait 1 minute before retrying
    
    # Final summary
    print(f"\n{'='*80}")
    print(f"🏁 TRADING SESSION COMPLETE")
    print(f"{'='*80}")
    
    final_balance = check_portfolio_balance(client)
    pnl = final_balance - balance
    
    print(f"💰 Starting balance: ${balance/100:.2f}")
    print(f"💰 Ending balance: ${final_balance/100:.2f}")
    print(f"📈 P&L: ${pnl/100:.2f}")
    print(f"📊 Total trades: {daily_stats['trades_executed']}")
    print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
    print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
    print(f"✅ Successful arbitrages: {daily_stats['successful_arbs']}")
    print(f"❌ Failed orders: {daily_stats['failed_orders']}")
    
    # Save final stats
    save_performance_stats()
    
    log_event("session_complete", {
        "duration_hours": SESSION_DURATION_HOURS,
        "starting_balance": balance,
        "ending_balance": final_balance,
        "pnl": pnl,
        "trades_executed": daily_stats["trades_executed"],
        "total_profit": daily_stats["total_profit"],
        "total_fees": daily_stats["total_fees"],
        "successful_arbs": daily_stats["successful_arbs"],
        "failed_orders": daily_stats["failed_orders"]
    })

if __name__ == "__main__":
    run_conservative_bot()

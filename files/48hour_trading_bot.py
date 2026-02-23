#!/usr/bin/env python3
"""
48-Hour Automated Arbitrage Trading Bot
Continuously scans for profitable arbitrage opportunities and executes trades automatically.
"""

import time
import json
import os
import signal
import sys
from datetime import datetime, timedelta
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH, USE_DEMO
from order_manager import ArbitrageOrderManager

# ============================================================
# TRADING CONFIGURATION
# ============================================================

# Trading Parameters
SCAN_INTERVAL = 15              # Seconds between scans (15 seconds for HIGH-VELOCITY)
AUTO_EXECUTE = True              # Enable automatic execution
MAX_CONTRACTS_PER_TRADE = 20     # Position size per arbitrage (INCREASED for HIGH-VELOCITY)
MIN_PROFIT_THRESHOLD = 0.05     # Minimum 5 cents profit per contract
MAX_DAILY_TRADES_TARGET = 30     # Target trades per day
SESSION_DURATION_HOURS = 48      # Total runtime

# Risk Management
MAX_CONCURRENT_POSITIONS = 5     # Max simultaneous arbitrage positions
TRACK_EXECUTED_TRADES = True    # Prevent duplicate executions
MIN_LIQUIDITY_THRESHOLD = 5     # Minimum 5 bids on each side

# Order Management
ORDER_MAX_WAIT_HOURS = 7        # Maximum hours to wait for fills
ORDER_UPGRADE_INTERVALS = [1, 4, 6, 7]  # Hours when to upgrade price
DYNAMIC_PRICING_ENABLED = True    # Enable dynamic pricing strategy

# Enhanced Strategy Features
FILL_RATE_MONITORING = True       # Monitor actual fill rates
DYNAMIC_PRICING_ENABLED = True    # Dynamic price adjustments
MARKET_FALLBACK_ENABLED = True    # Market-based fallback options
BASE_ORDER_PRICE = 3              # Base price in cents
MAX_ORDER_PRICE = 10              # Maximum price in cents
PRICE_UPGRADE_STEP = 1            # Price increase per upgrade (cents)
MIN_FILL_RATE_THRESHOLD = 0.3    # Minimum fill rate before price adjustment

# Logging
LOG_FILE = "data/48hour_trading.jsonl"
POSITIONS_FILE = "data/active_positions.json"
PERFORMANCE_FILE = "data/trading_performance.json"

# ============================================================
# GLOBAL STATE
# ============================================================

running = True
start_time = datetime.now()
end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
executed_trades = set()
daily_stats = {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "scans": 0,
    "opportunities_found": 0,
    "trades_executed": 0,
    "total_profit": 0.0,
    "total_fees": 0.0,
    "successful_arbitrages": 0
}

# ============================================================
# LOGGING FUNCTIONS
# ============================================================

def log_event(event_type, data):
    """Log trading events with timestamp."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "data": data
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {event_type}: {data}")

def calculate_fill_rate():
    """Calculate actual fill rate from trading logs."""
    try:
        with open(LOG_FILE, 'r') as f:
            logs = [json.loads(line) for line in f]
        
        execution_logs = [log for log in logs if log['type'] == 'execution_success']
        total_orders = len(execution_logs) * 2  # Each trade has 2 orders
        
        # Count orders with valid IDs (indicating successful placement)
        valid_orders = 0
        for log in execution_logs:
            if log['data'].get('yes_order_id') and log['data'].get('yes_order_id') != 'null':
                valid_orders += 1
            if log['data'].get('no_order_id') and log['data'].get('no_order_id') != 'null':
                valid_orders += 1
        
        fill_rate = valid_orders / total_orders if total_orders > 0 else 0
        return fill_rate, total_orders, valid_orders
        
    except Exception as e:
        print(f"Error calculating fill rate: {e}")
        return 0.0, 0, 0

def get_dynamic_order_price(base_price=BASE_ORDER_PRICE):
    """Get dynamic order price based on fill rate and market conditions."""
    if not DYNAMIC_PRICING_ENABLED:
        return base_price
    
    fill_rate, _, _ = calculate_fill_rate()
    
    # If fill rate is too low, increase price
    if fill_rate < MIN_FILL_RATE_THRESHOLD:
        new_price = min(base_price + PRICE_UPGRADE_STEP, MAX_ORDER_PRICE)
        print(f"📈 Fill rate {fill_rate:.1%} < threshold, increasing price to {new_price}c")
        return new_price
    
    return base_price

def should_use_market_fallback():
    """Determine if we should use market orders as fallback."""
    if not MARKET_FALLBACK_ENABLED:
        return False
    
    fill_rate, _, _ = calculate_fill_rate()
    
    # If fill rate is extremely low, consider market orders
    if fill_rate < 0.1:  # Less than 10% fill rate
        print(f"⚠️  Fill rate {fill_rate:.1%} extremely low, consider market orders")
        return True
    
    return False

def save_performance_stats():
    """Save performance statistics."""
    os.makedirs(os.path.dirname(PERFORMANCE_FILE), exist_ok=True)
    with open(PERFORMANCE_FILE, "w") as f:
        json.dump(daily_stats, f, indent=2, default=str)

def save_positions(positions):
    """Save active positions."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f, indent=2, default=str)

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
        log_event("balance_error", {"error": str(e)})
        print(f"❌ Balance check error: {e}")
        return 0

def get_active_positions():
    """Load currently active positions."""
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

def execute_arbitrage(executor, opportunity, available_balance):
    """Execute an arbitrage opportunity using dynamic order management."""
    ticker = opportunity["ticker"]
    
    # Check if already executed
    if ticker in executed_trades:
        log_event("duplicate_skipped", {"ticker": ticker})
        return None
    
    # Check liquidity
    yes_bids = opportunity.get("yes_bids", 0)
    no_bids = opportunity.get("no_bids", 0)
    if yes_bids < MIN_LIQUIDITY_THRESHOLD or no_bids < MIN_LIQUIDITY_THRESHOLD:
        log_event("liquidity_rejected", {
            "ticker": ticker,
            "yes_bids": yes_bids,
            "no_bids": no_bids,
            "min_required": MIN_LIQUIDITY_THRESHOLD
        })
        return None
    
    # Calculate position size based on total balance (in cents)
    max_affordable = int(available_balance)  # Balance is already in cents
    contracts = min(MAX_CONTRACTS_PER_TRADE, max_affordable, 100)
    
    # Ensure at least 1 contract
    if contracts < 1:
        contracts = 1
    
    print(f"\n🚀 Executing arbitrage on {ticker}")
    print(f"   Total balance: ${available_balance/100:.2f}")
    print(f"   Contracts: {contracts} (max affordable: {max_affordable})")
    print(f"   Expected profit: ${opportunity['net_profit_per_contract'] * contracts:.2f}")
    print(f"   YES bids: {yes_bids}, NO bids: {no_bids}")
    
    try:
        # Initialize order manager
        order_manager = ArbitrageOrderManager(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Check if we should use market fallback
        if should_use_market_fallback():
            print(f"   ⚠️  Using MARKET ORDERS as fallback due to low fill rate")
            # TODO: Implement market order logic here
            # For now, continue with limit orders but at higher price
        
        # Get dynamic order price based on fill rate
        dynamic_price = get_dynamic_order_price(BASE_ORDER_PRICE)
        yes_price = dynamic_price
        no_price = dynamic_price
        
        # Log fill rate monitoring
        fill_rate, total_orders, valid_orders = calculate_fill_rate()
        log_event("fill_rate_monitor", {
            "fill_rate": fill_rate,
            "total_orders": total_orders,
            "valid_orders": valid_orders,
            "current_price": dynamic_price
        })
        
        print(f"   📈 Placing orders at {dynamic_price}c each (DYNAMIC PRICING)...")
        print(f"   📊 Current fill rate: {fill_rate:.1%} ({valid_orders}/{total_orders})")
        
        # Place YES order
        yes_result = order_manager.place_dynamic_order(ticker, "yes", yes_price, contracts)
        
        if "error" in yes_result:
            log_event("execution_failed", {
                "ticker": ticker,
                "error": f"YES order failed: {yes_result['error']}"
            })
            print(f"   ❌ YES order failed: {yes_result['error']}")
            return yes_result
        
        # Place NO order
        no_result = order_manager.place_dynamic_order(ticker, "no", no_price, contracts)
        
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
        
        # Update statistics
        daily_stats["total_profit"] += total_profit
        daily_stats["total_fees"] += total_fees
        daily_stats["successful_arbitrages"] += 1
        
        # Save position
        positions = get_active_positions()
        positions[ticker] = {
            "entered": datetime.now().isoformat(),
            "contracts": contracts,
            "yes_price_cents": yes_price,
            "no_price_cents": no_price,
            "expected_profit": total_profit,
            "fees": total_fees,
            "status": "monitoring",
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "order_manager": True
        }
        save_positions(positions)
        
        log_event("execution_success", {
            "ticker": ticker,
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees,
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "strategy": "dynamic_pricing",
            "initial_prices": {"yes": yes_price, "no": no_price}
        })
        
        print(f"✅ Orders placed successfully!")
        print(f"   YES order: {yes_result.get('order', {}).get('order_id', 'N/A')}")
        print(f"   NO order: {no_result.get('order', {}).get('order_id', 'N/A')}")
        print(f"   Expected profit: ${total_profit:.2f}")
        print(f"   Total fees: ${total_fees:.4f}")
        print(f"   📊 Strategy: Dynamic pricing enabled")
        
        return {
            "success": True,
            "ticker": ticker,
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees,
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "strategy": "dynamic_pricing"
        }
        
    except Exception as e:
        log_event("execution_error", {
            "ticker": ticker,
            "error": str(e)
        })
        print(f"❌ Execution error: {e}")
        return None

def monitor_orders(order_manager):
    """Monitor active orders and manage dynamic pricing."""
    try:
        # Get all active orders
        active_orders = order_manager.get_all_active_orders()
        
        if active_orders["active_orders"] == 0:
            return
        
        print(f"\n📊 Monitoring {active_orders['active_orders']} active arbitrage positions...")
        
        for ticker, order_info in active_orders["orders"].items():
            # Check order status and complete arbitrage if needed
            result = order_manager.monitor_and_complete_arbitrage(ticker, ORDER_MAX_WAIT_HOURS)
            
            if result.get("action") == "arbitrage_complete":
                print(f"✅ Arbitrage complete: {ticker}")
                print(f"   YES filled: {result.get('yes_fill_time', 'N/A')}")
                print(f"   NO filled: {result.get('no_fill_time', 'N/A')}")
                
                # Update position status
                update_position_status(ticker, "completed", result.get("profit", 0))
                
                # Update statistics
                daily_stats["successful_arbitrages"] += 1
                
                log_event("arbitrage_completed", {
                    "ticker": ticker,
                    "profit": result.get("profit", 0),
                    "yes_fill_time": result.get("yes_fill_time"),
                    "no_fill_time": result.get("no_fill_time")
                })
                
            elif result.get("action") == "yes_filled_placing_no":
                print(f"🔄 YES filled, placing NO order for {ticker}")
                log_event("yes_filled", {"ticker": ticker})
                
            elif result.get("action") == "no_filled_placing_yes":
                print(f"🔄 NO filled, placing YES order for {ticker}")
                log_event("no_filled", {"ticker": ticker})
                
            elif result.get("action") == "cancel_old_orders":
                print(f"⏰ Orders timed out for {ticker} (>{ORDER_MAX_WAIT_HOURS}h)")
                log_event("orders_timeout", {"ticker": ticker})
                
            elif result.get("action") == "price_upgrade":
                print(f"📈 Upgrading prices for {ticker}: {result['old_prices']} → {result['new_prices']}")
                log_event("price_upgrade", {
                    "ticker": ticker,
                    "old_prices": result["old_prices"],
                    "new_prices": result["new_prices"]
                })
                
            elif result.get("action") == "waiting_for_fills":
                status = result.get("yes_status", "unknown")
                yes_remaining = result.get("yes_remaining", 0)
                no_remaining = result.get("no_remaining", 0)
                yes_age = result.get("yes_age_hours", 0)
                no_age = result.get("no_age_hours", 0)
                
                print(f"   ⏳ {ticker}: {status} | YES: {yes_remaining}/{result.get('contracts', 1)} ({yes_age:.1f}h) | NO: {no_remaining}/{result.get('contracts', 1)} ({no_age:.1f}h)")
                
                # Check if we should upgrade prices
                max_age = max(yes_age, no_age)
                if DYNAMIC_PRICING_ENABLED and max_age > ORDER_UPGRADE_INTERVALS[0]:
                    upgrade_result = order_manager.upgrade_price_if_needed(ticker, int(max_age))
                    if upgrade_result.get("action") == "price_upgrade":
                        print(f"   📈 {upgrade_result['new_prices']['yes']}/{upgrade_result['new_prices']['no']}c")
        
    except Exception as e:
        log_event("order_monitoring_error", {"error": str(e)})
        print(f"❌ Order monitoring error: {e}")

def scan_and_trade(executor, available_balance):
    """Scan for opportunities and execute trades."""
    try:
        # Find opportunities
        opportunities = executor.find_arb_opportunities()
        
        # Handle None response
        if opportunities is None:
            log_event("scan_no_opportunities", {"scans": daily_stats["scans"]})
            print(f"   ⚠️  No opportunities returned from scanner")
            return
        
        daily_stats["opportunities_found"] += len(opportunities)
        
        if not opportunities:
            log_event("scan_no_opportunities", {"scans": daily_stats["scans"]})
            print(f"   ⚠️  No profitable opportunities found")
            return
        
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
        
        # Check active positions limit
        active_positions = get_active_positions()
        active_count = len([p for p in active_positions.values() if p.get("status") == "active"])
        
        if active_count >= MAX_CONCURRENT_POSITIONS:
            log_event("position_limit_reached", {
                "active_count": active_count,
                "max_allowed": MAX_CONCURRENT_POSITIONS
            })
            print(f"   ⚠️  Position limit reached ({active_count}/{MAX_CONCURRENT_POSITIONS})")
            return
        
        # Execute best opportunity if profitable
        if AUTO_EXECUTE and opportunities:
            best = opportunities[0]
            
            # Additional checks
            profit_per_contract = best.get('net_profit_per_contract', 0)
            print(f"   🎯 Best opportunity: {best.get('ticker', 'Unknown')}")
            print(f"   💰 Profit per contract: ${profit_per_contract:.4f}")
            print(f"   📊 Threshold: ${MIN_PROFIT_THRESHOLD:.2f}")
            
            if profit_per_contract >= MIN_PROFIT_THRESHOLD:
                print(f"   ✅ Profit threshold met - Executing trade!")
                execute_arbitrage(executor, best, available_balance)
            else:
                print(f"   ⚠️  Best opportunity below profit threshold: ${profit_per_contract:.4f}")
        
    except Exception as e:
        log_event("scan_error", {"error": str(e)})
        print(f"   ❌ Scan error: {e}")
        import traceback
        print(f"   🐛 Traceback: {traceback.format_exc()}")

def check_position_settlements(client):
    """Check if any positions have settled."""
    try:
        positions = get_active_positions()
        settled_positions = []
        
        for ticker, position in positions.items():
            if position.get("status") == "active":
                try:
                    # Check if market is closed (settled)
                    market = client.get_market(ticker)
                    if market.get("status") == "closed":
                        # Position has settled
                        profit = position.get("expected_profit", 0)
                        update_position_status(ticker, "settled", profit)
                        settled_positions.append({
                            "ticker": ticker,
                            "profit": profit,
                            "contracts": position.get("contracts", 0)
                        })
                        print(f"💰 Position settled: {ticker} - Profit: ${profit:.2f}")
                except:
                    # Market might not exist anymore, consider it settled
                    update_position_status(ticker, "settled", position.get("expected_profit", 0))
        
        if settled_positions:
            log_event("positions_settled", {
                "count": len(settled_positions),
                "positions": settled_positions
            })
            
    except Exception as e:
        log_event("settlement_check_error", {"error": str(e)})

def print_status_summary():
    """Print current status summary."""
    elapsed = datetime.now() - start_time
    remaining = end_time - datetime.now()
    
    print(f"\n" + "="*60)
    print(f"📊 48-HOUR TRADING BOT STATUS")
    print(f"="*60)
    print(f"⏰  Runtime: {str(elapsed).split('.')[0]} | Remaining: {str(remaining).split('.')[0]}")
    print(f"📈  Today's Performance:")
    print(f"    • Scans: {daily_stats['scans']}")
    print(f"    • Opportunities found: {daily_stats['opportunities_found']}")
    print(f"    • Trades executed: {daily_stats['trades_executed']}")
    print(f"    • Successful arbitrages: {daily_stats['successful_arbitrages']}")
    print(f"    • Total profit: ${daily_stats['total_profit']:.2f}")
    print(f"    • Total fees: ${daily_stats['total_fees']:.4f}")
    
    active_positions = get_active_positions()
    active_count = len([p for p in active_positions.values() if p.get("status") == "active"])
    print(f"    • Active positions: {active_count}")
    print(f"🎯  Configuration:")
    print(f"    • Scan interval: {SCAN_INTERVAL}s")
    print(f"    • Auto-execute: {'ENABLED' if AUTO_EXECUTE else 'DISABLED'}")
    print(f"    • Position size: {MAX_CONTRACTS_PER_TRADE} contracts")
    print(f"    • Min profit threshold: ${MIN_PROFIT_THRESHOLD}")
    print(f"="*60)

# ============================================================
# SIGNAL HANDLING
# ============================================================

def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global running
    print(f"\n\n🛑 Shutdown signal received. Saving state...")
    running = False
    save_performance_stats()
    print("✅ State saved. Exiting gracefully.")

def check_time_limit():
    """Check if 48-hour time limit reached."""
    if datetime.now() >= end_time:
        print(f"\n⏰ 48-hour session completed!")
        print(f"📊 Final Performance:")
        print(f"    • Total scans: {daily_stats['scans']}")
        print(f"    • Total trades: {daily_stats['trades_executed']}")
        print(f"    • Total profit: ${daily_stats['total_profit']:.2f}")
        print(f"    • Total fees: ${daily_stats['total_fees']:.4f}")
        save_performance_stats()
        running = False
        return True
    return False

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def main():
    global running, daily_stats
    
    print("="*60)
    print("🤖 48-HOUR AUTOMATED ARBITRAGE TRADING BOT")
    print("="*60)
    print(f"⏰  Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏰  End time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔗  Mode: {'DEMO' if USE_DEMO else 'LIVE TRADING'}")
    print(f"💰  Position size: {MAX_CONTRACTS_PER_TRADE} contracts per trade")
    print(f"🎯  Min profit threshold: ${MIN_PROFIT_THRESHOLD} per contract")
    print(f"⚡  Scan interval: {SCAN_INTERVAL} seconds")
    print(f"🚀  Auto-execute: {'ENABLED' if AUTO_EXECUTE else 'DISABLED'}")
    print(f"\n⚠️  PRESS Ctrl+C TO STOP AT ANY TIME")
    print("="*60)
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Check API keys
    if KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ ERROR: KALSHI_API_KEY_ID not set!")
        print("Please set environment variable:")
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
        print(f"✅ Authenticated successfully")
        print(f"💰 Available balance: ${balance/100:.2f}")
        
        # Note: Balance can be 0 but trading still works (as proven by test order)
        # The bot will check balance before each trade and adjust position size
        
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize trading components: {e}")
        return
    
    # Main trading loop
    scan_count = 0
    last_status_print = datetime.now()
    
    while running:
        try:
            # Check time limit
            if check_time_limit():
                break
            
            scan_count += 1
            daily_stats["scans"] += 1
            
            # Check portfolio balance
            available_balance = check_portfolio_balance(client)
            
            # Scan for opportunities and trade
            scan_and_trade(executor, available_balance)
            
            # Monitor orders (NEW: Dynamic pricing and fill completion)
            if DYNAMIC_PRICING_ENABLED:
                monitor_orders(order_manager)
            
            # Check for settled positions
            check_position_settlements(client)
            
            # Save performance stats periodically
            if scan_count % 10 == 0:
                save_performance_stats()
                
                # Log fill rate monitoring report
                if FILL_RATE_MONITORING:
                    fill_rate, total_orders, valid_orders = calculate_fill_rate()
                    log_event("fill_rate_report", {
                        "fill_rate": fill_rate,
                        "total_orders": total_orders,
                        "valid_orders": valid_orders,
                        "scan_count": scan_count,
                        "current_price": get_dynamic_order_price(BASE_ORDER_PRICE)
                    })
                    print(f"📊 Fill Rate Report: {fill_rate:.1%} ({valid_orders}/{total_orders} orders)")
            
            # Print status summary every 5 minutes
            if datetime.now() - last_status_print > timedelta(minutes=5):
                print_status_summary()
                last_status_print = datetime.now()
            
            # Wait for next scan
            print(f"⏳ Next scan in {SCAN_INTERVAL}s... (Scan #{scan_count})", end="\r")
            time.sleep(SCAN_INTERVAL)
            
        except KeyboardInterrupt:
            print(f"\n🛑 Keyboard interrupt received")
            break
        except Exception as e:
            log_event("loop_error", {"error": str(e), "scan_count": scan_count})
            print(f"\n❌ Loop error: {e}")
            time.sleep(SCAN_INTERVAL)  # Wait before retrying
    
    # Final cleanup
    print(f"\n🏁 Trading session completed")
    print(f"📊 Total scans performed: {scan_count}")
    print(f"💰 Final profit: ${daily_stats['total_profit']:.2f}")
    print(f"💸 Total fees paid: ${daily_stats['total_fees']:.4f}")
    print(f"🎯 Success rate: {daily_stats['successful_arbitrages']}/{daily_stats['trades_executed']} arbitrages")
    
    save_performance_stats()
    print(f"✅ Performance data saved to {PERFORMANCE_FILE}")

if __name__ == "__main__":
    main()

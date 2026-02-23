#!/usr/bin/env python3
"""
Enhanced 48-Hour Trading Bot with Orderbook Scanner and P&L Monitoring
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
MAX_CONTRACTS_PER_TRADE = 10     # Position size per arbitrage (CONSERVATIVE)
MIN_PROFIT_THRESHOLD = 0.05     # Minimum 5 cents profit per contract
MAX_DAILY_TRADES_TARGET = 20     # Target trades per day (REDUCED)
SESSION_DURATION_HOURS = 48      # Total runtime

# Risk Management
MAX_CONCURRENT_POSITIONS = 3     # Max simultaneous arbitrage positions (REDUCED)
TRACK_EXECUTED_TRADES = True    # Prevent duplicate executions
MIN_LIQUIDITY_THRESHOLD = 5     # Minimum 5 bids on each side

# Order Management - CONSERVATIVE
ORDER_MAX_WAIT_HOURS = 7        # Maximum hours to wait for fills
ORDER_UPGRADE_INTERVALS = [2, 5, 7]  # Hours when to upgrade price (LESS frequent)
BASE_ORDER_PRICE = 1              # Base price in cents (CONSERVATIVE)
MAX_ORDER_PRICE = 5               # Maximum price in cents (LIMITED)
PRICE_UPGRADE_STEP = 1            # Price increase per upgrade (cents)

# P&L Monitoring
PNL_REPORT_INTERVAL = 3600      # Hourly P&L reports (3600 seconds)
DETAILED_LOGGING = True          # Enable detailed logging

# Logging
LOG_FILE = "data/enhanced_48hour_trading.jsonl"
POSITIONS_FILE = "data/enhanced_positions.json"
PERFORMANCE_FILE = "data/enhanced_performance.json"
HOURLY_REPORT_FILE = "data/hourly_pnl_reports.json"

# ============================================================
# GLOBAL STATE
# ============================================================

executed_trades = set()
daily_stats = {
    "trades_executed": 0,
    "total_profit": 0.0,
    "total_fees": 0.0,
    "successful_arbs": 0,
    "failed_orders": 0,
    "scans": 0,
    "opportunities_found": 0
}

# P&L Tracking
pnl_history = []
last_pnl_report_time = datetime.now()
initial_balance = 0

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

def save_hourly_report(report):
    """Save hourly P&L report."""
    os.makedirs(os.path.dirname(HOURLY_REPORT_FILE), exist_ok=True)
    with open(HOURLY_REPORT_FILE, "a") as f:
        f.write(json.dumps(report, default=str) + "\n")

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
# P&L MONITORING
# ============================================================

def get_current_balance(client):
    """Get current portfolio balance using the same method as working bot."""
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
            return total_balance
        else:
            print(f"❌ Balance check failed: {resp.status_code} - {resp.text}")
            return 0
            
    except Exception as e:
        print(f"❌ Balance check error: {e}")
        return 0

def generate_hourly_pnl_report(client, start_time):
    """Generate hourly P&L report."""
    global last_pnl_report_time, initial_balance, pnl_history
    
    current_time = datetime.now()
    current_balance = get_current_balance(client)
    
    if initial_balance == 0:
        initial_balance = current_balance
    
    pnl = current_balance - initial_balance
    elapsed_hours = (current_time - start_time).total_seconds() / 3600
    
    # Calculate hourly rate
    if elapsed_hours > 0:
        hourly_rate = pnl / elapsed_hours
    else:
        hourly_rate = 0
    
    # Get position summary
    positions = get_active_positions()
    active_positions = len([p for p in positions.values() if p.get("status") == "active"])
    completed_positions = len([p for p in positions.values() if p.get("status") in ["completed", "settled"]])
    
    report = {
        "timestamp": current_time.isoformat(),
        "elapsed_hours": round(elapsed_hours, 2),
        "initial_balance": initial_balance,
        "current_balance": current_balance,
        "pnl": pnl,
        "pnl_dollars": pnl / 100,
        "hourly_rate": hourly_rate / 100,
        "trades_executed": daily_stats["trades_executed"],
        "successful_arbs": daily_stats["successful_arbs"],
        "failed_orders": daily_stats["failed_orders"],
        "active_positions": active_positions,
        "completed_positions": completed_positions,
        "total_scans": daily_stats["scans"],
        "opportunities_found": daily_stats["opportunities_found"]
    }
    
    # Save to history
    pnl_history.append(report)
    save_hourly_report(report)
    
    # Print report
    print("\n" + "="*80)
    print(f"📊 HOURLY P&L REPORT - Hour {int(elapsed_hours)}")
    print("="*80)
    print(f"💰 Initial Balance: ${initial_balance/100:.2f}")
    print(f"💰 Current Balance: ${current_balance/100:.2f}")
    print(f"📈 P&L: ${pnl/100:+.2f}")
    print(f"⚡ Hourly Rate: ${hourly_rate/100:+.2f}")
    print(f"📊 Trades Executed: {daily_stats['trades_executed']}")
    print(f"✅ Successful ARBs: {daily_stats['successful_arbs']}")
    print(f"❌ Failed Orders: {daily_stats['failed_orders']}")
    print(f"🎯 Active Positions: {active_positions}")
    print(f"✅ Completed Positions: {completed_positions}")
    print(f"🔍 Total Scans: {daily_stats['scans']}")
    print(f"🎯 Opportunities Found: {daily_stats['opportunities_found']}")
    
    # Performance analysis
    if daily_stats["trades_executed"] > 0:
        success_rate = daily_stats["successful_arbs"] / daily_stats["trades_executed"] * 100
        print(f"📈 Success Rate: {success_rate:.1f}%")
    
    if pnl > 0:
        print(f"🎉 PROFITABLE SESSION!")
    elif pnl < 0:
        print(f"⚠️  LOSING SESSION - Review Strategy")
    else:
        print(f"⏸️  BREAK-EVEN SESSION")
    
    print("="*80)
    
    last_pnl_report_time = current_time
    return report

# ============================================================
# ORDERBOOK SCANNER
# ============================================================

def scan_orderbook_opportunities(executor):
    """Scan for arbitrage opportunities using orderbook data."""
    try:
        # Get all markets first
        result = executor.client.get_markets(status="open", limit=200)
        markets = result.get("markets", [])
        
        opportunities = []
        
        for market in markets:
            ticker = market.get("ticker", "")
            
            try:
                # Get orderbook data like the original bot
                orderbook = executor.client.get_orderbook(ticker)
                
                if not orderbook or "orderbook" not in orderbook:
                    continue
                    
                yes_bids = orderbook["orderbook"].get("yes", [])
                no_bids = orderbook["orderbook"].get("no", [])
                
                if not yes_bids or not no_bids:
                    continue
                
                # Get best prices from orderbook
                best_yes_price = yes_bids[0][0] if yes_bids else None
                best_no_price = no_bids[0][0] if no_bids else None
                
                if not best_yes_price or not best_no_price:
                    continue
                
                combined = (best_yes_price + best_no_price) / 100
                
                if combined < 1.0 - MIN_PROFIT_THRESHOLD:
                    spread = round(1.0 - combined, 4)
                    
                    opportunities.append({
                        "ticker": ticker,
                        "title": market.get("title", ""),
                        "yes_price_cents": best_yes_price,
                        "no_price_cents": best_no_price,
                        "combined": round(combined, 4),
                        "spread": spread,
                        "volume": market.get("volume", 0),
                        "net_profit_per_contract": spread - 0.002,  # Approximate fees
                        "total_fees_per_contract": 0.002,
                        "roi_net_percent": (spread - 0.002) / 0.98 * 100,
                        "source": "orderbook",
                        "yes_bids": len(yes_bids),
                        "no_bids": len(no_bids)
                    })
                    
            except Exception as e:
                continue
        
        # Sort by spread (best first)
        opportunities.sort(key=lambda x: x["spread"], reverse=True)
        
        daily_stats["opportunities_found"] += len(opportunities)
        
        if opportunities:
            print(f"\n📊 Found {len(opportunities)} arbitrage opportunities:")
            for i, opp in enumerate(opportunities[:3]):
                print(f"   {i+1}. {opp.get('ticker', 'Unknown')}")
                print(f"      Spread: {opp.get('spread', 0)} | Net profit: ${opp.get('net_profit_per_contract', 0):.4f}")
                print(f"      Liquidity: YES {opp.get('yes_bids', 0)} | NO {opp.get('no_bids', 0)}")
        
        return opportunities
        
    except Exception as e:
        log_event("scan_error", {"error": str(e)})
        print(f"❌ Scan error: {e}")
        return []

# ============================================================
# TRADING FUNCTIONS
# ============================================================

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
        # Use orderbook prices for execution
        yes_price = opportunity["yes_price_cents"]
        no_price = opportunity["no_price_cents"]
        
        print(f"   📈 Placing orders at orderbook prices: YES {yes_price}c, NO {no_price}c")
        
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
            "strategy": "conservative_orderbook"
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
            "strategy": "conservative_orderbook",
            "prices": {"yes": yes_price, "no": no_price}
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

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_enhanced_bot():
    """Run the enhanced 48-hour trading bot with P&L monitoring."""
    print("=" * 80)
    print("🚀 ENHANCED 48-HOUR TRADING BOT")
    print("📊 Orderbook Scanner + Hourly P&L Monitoring")
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
        balance = get_current_balance(client)
        if balance == 0:
            print("❌ Authentication failed or no balance")
            return
            
        print(f"✅ Authentication successful")
        print(f"💰 Starting balance: ${balance/100:.2f}")
        
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        return
    
    # Load existing stats
    global daily_stats, initial_balance
    daily_stats = load_performance_stats()
    initial_balance = balance
    
    # Setup signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print(f"\n🛑 Graceful shutdown initiated...")
        save_performance_stats()
        generate_hourly_pnl_report(client, start_time)
        print(f"📊 Final stats: {daily_stats}")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Trading loop
    start_time = datetime.now()
    end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
    scan_count = 0
    last_pnl_report_time = start_time
    
    print(f"🚀 Starting trading session")
    print(f"⏰ Duration: {SESSION_DURATION_HOURS} hours")
    print(f"📊 Scan interval: {SCAN_INTERVAL} seconds")
    print(f"💰 Max contracts per trade: {MAX_CONTRACTS_PER_TRADE}")
    print(f"🎯 Min profit threshold: ${MIN_PROFIT_THRESHOLD}")
    print(f"📈 Session ends: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Hourly P&L reports: Every {PNL_REPORT_INTERVAL/3600} hour(s)")
    
    while datetime.now() < end_time:
        try:
            scan_count += 1
            daily_stats["scans"] += 1
            current_time = datetime.now()
            elapsed = current_time - start_time
            remaining = end_time - current_time
            
            print(f"\n{'='*60}")
            print(f"📊 Scan #{scan_count} | Elapsed: {elapsed.total_seconds()/3600:.1f}h | Remaining: {remaining.total_seconds()/3600:.1f}h")
            print(f"💰 Current balance: ${get_current_balance(client)/100:.2f}")
            print(f"📈 Trades executed: {daily_stats['trades_executed']}")
            print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
            
            # Check daily trade limit
            if daily_stats["trades_executed"] >= MAX_DAILY_TRADES_TARGET:
                print(f"🎯 Daily trade target reached ({MAX_DAILY_TRADES_TARGET})")
                time.sleep(300)  # Wait 5 minutes
                continue
            
            # Scan for opportunities using orderbook
            opportunities = scan_orderbook_opportunities(executor)
            
            if not opportunities:
                print(f"📊 No profitable opportunities found")
            else:
                print(f"🎯 Found {len(opportunities)} opportunities")
                
                # Execute best opportunity
                best_opp = opportunities[0]
                available_balance = get_current_balance(client)
                
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
            
            # Check for hourly P&L report
            if current_time - last_pnl_report_time >= timedelta(seconds=PNL_REPORT_INTERVAL):
                generate_hourly_pnl_report(client, start_time)
            
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
    
    final_balance = get_current_balance(client)
    pnl = final_balance - initial_balance
    
    print(f"💰 Initial balance: ${initial_balance/100:.2f}")
    print(f"💰 Final balance: ${final_balance/100:.2f}")
    print(f"📈 P&L: ${pnl/100:.2f}")
    print(f"📊 Total trades: {daily_stats['trades_executed']}")
    print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
    print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
    print(f"✅ Successful arbitrages: {daily_stats['successful_arbs']}")
    print(f"❌ Failed orders: {daily_stats['failed_orders']}")
    
    # Final P&L report
    generate_hourly_pnl_report(client, start_time)
    
    # Save final stats
    save_performance_stats()
    
    log_event("session_complete", {
        "duration_hours": SESSION_DURATION_HOURS,
        "starting_balance": initial_balance,
        "ending_balance": final_balance,
        "pnl": pnl,
        "trades_executed": daily_stats["trades_executed"],
        "total_profit": daily_stats["total_profit"],
        "total_fees": daily_stats["total_fees"],
        "successful_arbs": daily_stats["successful_arbs"],
        "failed_orders": daily_stats["failed_orders"],
        "hourly_reports": len(pnl_history)
    })

if __name__ == "__main__":
    run_enhanced_bot()

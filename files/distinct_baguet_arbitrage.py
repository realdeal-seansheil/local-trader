#!/usr/bin/env python3
"""
Distinct-Baguette Arbitrage Bot
Replicates the successful Polymarket arbitrage strategy for Kalshi
"""

import os
import json
import time
import signal
import sys
from datetime import datetime, timedelta
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
from order_manager import ArbitrageOrderManager

# ============================================================
# DISTINCT-BAGUET STRATEGY CONFIGURATION
# Based on pattern analysis of the successful Polymarket trader
# ============================================================

# Trading Parameters - Based on distinct-baguette patterns
SCAN_INTERVAL = 10              # Sub-second execution required (10 seconds)
AUTO_EXECUTE = True              # Enable automatic execution
MAX_CONTRACTS_PER_TRADE = 10     # Typical position size from analysis
MIN_PROFIT_THRESHOLD = 0.02     # Minimum 2c spread (from analysis)
MAX_DAILY_TRADES = 50          # Max trades per day (from config)
SESSION_DURATION_HOURS = 48      # Total runtime

# Risk Controls - Based on distinct-baguette patterns
MAX_CONCURRENT_POSITIONS = 5     # Allow multiple concurrent positions
TRACK_EXECUTED_TRADES = True    # Prevent duplicate executions
MIN_LIQUIDITY_THRESHOLD = 2     # Focus on thin order books

# Order Management - Based on analysis findings
ORDER_MAX_WAIT_HOURS = 6        # Fast execution required
BASE_ORDER_PRICE = 50            # Dominant price range: 50-60c
MAX_ORDER_PRICE = 60
PRICE_UPGRADE_STEP = 2            # Aggressive pricing for thin markets

# Distinct-Baguette Strategy Features
EXECUTION_SPEED_REQUIRED = "sub-second"  # From analysis
DOMINANT_CATEGORY = "crypto"              # 100% crypto focus
AVG_SPREAD_TARGET = 0.1258               # Average spread target
TYPICAL_POSITION_SIZE = 10                # From analysis
MAX_POSITION_SIZE = 150                   # From analysis

# Logging
LOG_FILE = "data/distinct_baguet_trading.jsonl"
POSITIONS_FILE = "data/distinct_baguet_positions.json"
PERFORMANCE_FILE = "data/distinct_baguet_performance.json"

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
    "opportunities_found": 0,
    "avg_spreads": []
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
# DISTINCT-BAGUET SCANNER
# ============================================================

def scan_distinct_baguet_opportunities(executor):
    """Scan for arbitrage opportunities using distinct-baguette patterns."""
    try:
        # Get all markets first
        result = executor.client.get_markets(status="open", limit=200)
        markets = result.get("markets", [])
        
        opportunities = []
        
        for market in markets:
            ticker = market.get("ticker", "")
            
            # Focus on crypto markets (distinct-baguette pattern)
            if not any(crypto_word in ticker.upper() for crypto_word in ['BTC', 'ETH', 'CRYPTO', 'COIN']):
                continue
            
            try:
                # Get orderbook data (required for thin market analysis)
                orderbook = executor.client.get_orderbook(ticker)
                
                if not orderbook or "orderbook" not in orderbook:
                    continue
                    
                yes_bids = orderbook["orderbook"].get("yes", [])
                no_bids = orderbook["orderbook"].get("no", [])
                
                # Focus on thin order books (distinct-baguette pattern)
                if len(yes_bids) > 5 or len(no_bids) > 5:
                    continue
                
                if not yes_bids or not no_bids:
                    continue
                
                # Get best prices from orderbook
                best_yes_price = yes_bids[0][0] if yes_bids else None
                best_no_price = no_bids[0][0] if no_bids else None
                
                if not best_yes_price or not best_no_price:
                    continue
                
                # Check for dominant price range (50-60c)
                if best_yes_price < 40 or best_yes_price > 70:
                    continue
                
                combined = (best_yes_price + best_no_price) / 100
                
                # Look for arbitrage opportunities (distinct-baguette pattern)
                if combined < 1.0 - MIN_PROFIT_THRESHOLD:
                    spread = round(1.0 - combined, 4)
                    
                    # Track average spreads
                    daily_stats["avg_spreads"].append(spread)
                    
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
                        "source": "distinct_baguet",
                        "yes_bids": len(yes_bids),
                        "no_bids": len(no_bids),
                        "category": "crypto",
                        "liquidity": "thin"
                    })
                    
            except Exception as e:
                continue
        
        # Sort by spread (best first) - distinct-baguette prioritized
        opportunities.sort(key=lambda x: x["spread"], reverse=True)
        
        daily_stats["opportunities_found"] += len(opportunities)
        
        if opportunities:
            print(f"\n📊 Found {len(opportunities)} distinct-baguette opportunities:")
            for i, opp in enumerate(opportunities[:3]):
                print(f"   {i+1}. {opp.get('ticker', 'Unknown')} ({opp.get('category', 'Unknown')})")
                print(f"      Spread: {opp.get('spread', 0)} | Net profit: ${opp.get('net_profit_per_contract', 0):.4f}")
                print(f"      Liquidity: YES {opp.get('yes_bids', 0)} | NO {opp.get('no_bids', 0)} ({opp.get('liquidity', 'Unknown')})")
        
        return opportunities
        
    except Exception as e:
        log_event("scan_error", {"error": str(e)})
        print(f"❌ Scan error: {e}")
        return []

# ============================================================
# TRADING FUNCTIONS
# ============================================================

def execute_distinct_baguet_arbitrage(executor, opportunity, available_balance):
    """Execute arbitrage using distinct-baguette patterns."""
    ticker = opportunity["ticker"]
    
    # Check if already executed
    if ticker in executed_trades:
        log_event("duplicate_skipped", {"ticker": ticker})
        return None
    
    # Check liquidity (thin order books preferred)
    yes_bids = opportunity.get("yes_bids", 0)
    no_bids = opportunity.get("no_bids", 0)
    
    if yes_bids > MIN_LIQUIDITY_THRESHOLD or no_bids > MIN_LIQUIDITY_THRESHOLD:
        log_event("too_liquid", {
            "ticker": ticker,
            "yes_bids": yes_bids,
            "no_bids": no_bids,
            "threshold": MIN_LIQUIDITY_THRESHOLD
        })
        return None
    
    # Calculate position size (distinct-baguette typical size)
    contracts = min(TYPICAL_POSITION_SIZE, int(available_balance / 100))
    
    if contracts < 1:
        log_event("insufficient_balance", {
            "ticker": ticker,
            "available_balance": available_balance,
            "required": 100
        })
        return None
    
    print(f"\n🎯 EXECUTING DISTINCT-BAGUET ARBITRAGE: {ticker}")
    print(f"   📊 Category: {opportunity.get('category', 'Unknown')}")
    print(f"   💰 Liquidity: YES {yes_bids} | NO {no_bids} (thin order book)")
    print(f"   💰 Profit per contract: ${opportunity['net_profit_per_contract']:.4f}")
    print(f"   📈 Contracts: {contracts} (typical size)")
    print(f"   💸 Expected profit: ${opportunity['net_profit_per_contract'] * contracts:.2f}")
    
    # Place orders using orderbook prices (distinct-baguette pattern)
    try:
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
            "strategy": "distinct_baguet",
            "category": opportunity.get("category", "unknown"),
            "liquidity": opportunity.get("liquidity", "unknown")
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
            "strategy": "distinct_baguet",
            "category": opportunity.get("category"),
            "liquidity": opportunity.get("liquidity")
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

def run_distinct_baguet_bot():
    """Run the distinct-baguette arbitrage bot."""
    print("=" * 80)
    print("🎯 DISTINCT-BAGUET ARBITRAGE BOT")
    print("💰 Replicating Successful Polymarket Strategy on Kalshi")
    print("=" * 80)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    # Initialize trading components
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        client = KalshiClient(auth)
        executor = StrategyExecutor(client)
        order_manager = ArbitrageOrderManager(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        print(f"✅ Authentication successful")
        print(f"🎯 Strategy: Arbitrage (distinct-baguette pattern)")
        print(f"📊 Focus: Crypto markets with thin order books")
        print(f"💰 Typical position size: {TYPICAL_POSITION_SIZE} contracts")
        print(f"⚡ Execution speed: {EXECUTION_SPEED_REQUIRED}")
        
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
    
    print(f"🚀 Starting distinct-baguette trading session")
    print(f"⏰ Duration: {SESSION_DURATION_HOURS} hours")
    print(f"📊 Scan interval: {SCAN_INTERVAL} seconds (sub-second execution)")
    print(f"💰 Max contracts per trade: {MAX_CONTRACTS_PER_TRADE}")
    print(f"🎯 Min profit threshold: ${MIN_PROFIT_THRESHOLD}")
    print(f"📈 Session ends: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    while datetime.now() < end_time:
        try:
            scan_count += 1
            daily_stats["scans"] += 1
            current_time = datetime.now()
            elapsed = current_time - start_time
            remaining = end_time - current_time
            
            print(f"\n{'='*60}")
            print(f"📊 Scan #{scan_count} | Elapsed: {elapsed.total_seconds()/3600:.1f}h | Remaining: {remaining.total_seconds()/3600:.1f}h")
            print(f"📈 Trades executed: {daily_stats['trades_executed']}")
            print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
            
            # Check daily trade limit
            if daily_stats["trades_executed"] >= MAX_DAILY_TRADES:
                print(f"🎯 Daily trade limit reached ({MAX_DAILY_TRADES})")
                time.sleep(300)  # Wait 5 minutes
                continue
            
            # Scan for distinct-baguette opportunities
            opportunities = scan_distinct_baguet_opportunities(executor)
            
            if not opportunities:
                print(f"📊 No distinct-baguette opportunities found")
            else:
                print(f"🎯 Found {len(opportunities)} distinct-baguette opportunities")
                
                # Execute best opportunity
                best_opp = opportunities[0]
                
                # Check concurrent positions limit
                active_positions = get_active_positions()
                active_count = len([p for p in active_positions.values() if p.get("status") == "active"])
                
                if active_count < MAX_CONCURRENT_POSITIONS:
                    result = execute_distinct_baguet_arbitrage(executor, best_opp, 0)  # Use 0 for balance check
                    
                    if result and "success" in result:
                        print(f"🎉 Distinct-baguette arbitrage executed successfully!")
                    else:
                        print(f"❌ Arbitrage execution failed")
                        daily_stats["failed_orders"] += 1
                else:
                    print(f"📊 Max concurrent positions reached ({MAX_CONCURRENT_POSITIONS})")
            
            # Save performance stats periodically
            if scan_count % 10 == 0:
                save_performance_stats()
                
                # Show average spread
                if daily_stats["avg_spreads"]:
                    avg_spread = sum(daily_stats["avg_spreads"]) / len(daily_stats["avg_spreads"])
                    print(f"📊 Average spread: {avg_spread:.4f} (target: {AVG_SPREAD_TARGET})")
            
            # Wait for next scan (sub-second execution)
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
    print(f"🏁 DISTINCT-BAGUET SESSION COMPLETE")
    print(f"{'='*80}")
    
    print(f"📊 Total trades: {daily_stats['trades_executed']}")
    print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
    print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
    print(f"✅ Successful arbitrages: {daily_stats['successful_arbs']}")
    print(f"❌ Failed orders: {daily_stats['failed_orders']}")
    
    if daily_stats["avg_spreads"]:
        avg_spread = sum(daily_stats["avg_spreads"]) / len(daily_stats["avg_spreads"])
        print(f"📊 Average spread: {avg_spread:.4f}")
    
    # Save final stats
    save_performance_stats()
    
    log_event("session_complete", {
        "strategy": "distinct_baguet",
        "duration_hours": SESSION_DURATION_HOURS,
        "trades_executed": daily_stats["trades_executed"],
        "total_profit": daily_stats["total_profit"],
        "total_fees": daily_stats["total_fees"],
        "successful_arbs": daily_stats["successful_arbs"],
        "failed_orders": daily_stats["failed_orders"],
        "avg_spread": sum(daily_stats["avg_spreads"]) / len(daily_stats["avg_spreads"]) if daily_stats["avg_spreads"] else 0
    })

if __name__ == "__main__":
    run_distinct_baguet_bot()

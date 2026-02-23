#!/usr/bin/env python3
"""
Crypto Arbitrage Bot - Distinct-Baguette Strategy for Kalshi
Replicates the successful Polymarket arbitrage strategy on Kalshi crypto markets
"""

import os
import json
import time
import signal
import sys
import datetime
from datetime import datetime as dt, timedelta
from kalshi_executor import KalshiAuth, KalshiClient, StrategyExecutor
from kalshi_executor import KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH
import requests
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ============================================================
# CRYPTO ARBITRAGE CONFIGURATION
# Based on distinct-baguette strategy analysis
# ============================================================

# Trading Parameters - Distinct-Baguette Style
SCAN_INTERVAL = 15              # 15-second scans (sub-second execution)
AUTO_EXECUTE = True              # Enable automatic execution
MAX_CONTRACTS_PER_TRADE = 10     # Position size per arbitrage
MIN_PROFIT_THRESHOLD = 0.02     # Minimum 2 cents profit per contract
MAX_DAILY_TRADES = 50          # Max trades per day
SESSION_DURATION_HOURS = 48      # Total runtime

# Risk Controls - Conservative
MAX_CONCURRENT_POSITIONS = 5     # Max simultaneous arbitrage positions
TRACK_EXECUTED_TRADES = True    # Prevent duplicate executions
MIN_LIQUIDITY_THRESHOLD = 2     # Minimum liquidity for execution

# Crypto Market Focus
CRYPTO_SERIES = [
    'KXBTCMAXM',      # Bitcoin max price markets
    'KXDOGE',         # Dogecoin price range markets  
    'KXETHATH',       # Ethereum ATH markets
    'KXCRYPTOPERFORMY', # Crypto performance markets
    'KXSATOSHIBTCYEAR', # Satoshi Bitcoin markets
    'ETHETF',         # ETH ETF markets
    'KXHEGSETH',      # ETH/HEG markets
    'KXBOXINGMOV',    # Boxing movie crypto (if any)
]

# Logging
LOG_FILE = "data/crypto_arbitrage_trading.jsonl"
POSITIONS_FILE = "data/crypto_positions.json"
PERFORMANCE_FILE = "data/crypto_performance.json"

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
    "crypto_markets_scanned": 0,
    "active_crypto_markets": 0
}

# ============================================================
# LOGGING FUNCTIONS
# ============================================================

def log_event(event_type, data):
    """Log events to JSONL file."""
    timestamp = dt.now().isoformat()
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
        positions[ticker]["updated"] = dt.now().isoformat()
        if profit is not None:
            positions[ticker]["profit"] = profit
        save_positions(positions)

# ============================================================
# CRYPTO MARKET SCANNER
# ============================================================

def get_crypto_series_markets(auth, series_ticker):
    """Get markets for a specific crypto series."""
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
            print(f"❌ Error getting markets for {series_ticker}: {resp.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Exception getting markets for {series_ticker}: {e}")
        return []

def scan_crypto_arbitrage_opportunities(auth):
    """Scan for crypto arbitrage opportunities using distinct-baguette strategy."""
    try:
        opportunities = []
        total_markets = 0
        active_markets = 0
        
        print("🔍 Scanning crypto series for arbitrage opportunities...")
        
        for series_ticker in CRYPTO_SERIES:
            print(f"   📊 Scanning {series_ticker}...")
            
            markets = get_crypto_series_markets(auth, series_ticker)
            total_markets += len(markets)
            
            for market in markets:
                ticker = market.get('ticker', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                yes_bid = market.get('yes_bid', 0)
                no_bid = market.get('no_bid', 0)
                
                # Skip markets with no pricing
                if yes_ask == 0 and no_ask == 0:
                    continue
                
                active_markets += 1
                
                # Check for arbitrage opportunity
                if yes_ask and no_ask:
                    combined = (yes_ask + no_ask) / 100
                    
                    if combined < 1.0 - MIN_PROFIT_THRESHOLD:
                        spread = round(1.0 - combined, 4)
                        
                        # Calculate profit
                        net_profit_per_contract = spread - 0.002  # Approximate fees
                        total_fees_per_contract = 0.002
                        roi_net_percent = (net_profit_per_contract / 0.98) * 100
                        
                        opportunities.append({
                            "ticker": ticker,
                            "series": series_ticker,
                            "title": market.get('title', ''),
                            "yes_price_cents": yes_ask,
                            "no_price_cents": no_ask,
                            "yes_bid": yes_bid,
                            "no_bid": no_bid,
                            "combined": round(combined, 4),
                            "spread": spread,
                            "net_profit_per_contract": net_profit_per_contract,
                            "total_fees_per_contract": total_fees_per_contract,
                            "roi_net_percent": roi_net_percent,
                            "volume": market.get('volume', 0),
                            "status": market.get('status', 'unknown'),
                            "source": "crypto_arbitrage"
                        })
        
        # Sort by spread (best first)
        opportunities.sort(key=lambda x: x["spread"], reverse=True)
        
        daily_stats["crypto_markets_scanned"] = total_markets
        daily_stats["active_crypto_markets"] = active_markets
        daily_stats["opportunities_found"] += len(opportunities)
        
        print(f"📊 Crypto Market Scan Results:")
        print(f"   📈 Total markets scanned: {total_markets}")
        print(f"   🚀 Active markets: {active_markets}")
        print(f"   🎉 Arbitrage opportunities: {len(opportunities)}")
        
        if opportunities:
            print(f"\n🎉 Crypto Arbitrage Opportunities Found:")
            for i, opp in enumerate(opportunities[:3]):
                print(f"   {i+1}. {opp.get('ticker', 'Unknown')} ({opp.get('series', 'Unknown')})")
                print(f"      Spread: {opp.get('spread', 0)} | Net profit: ${opp.get('net_profit_per_contract', 0):.4f}")
                print(f"      YES: {opp.get('yes_bid', 0)}c/{opp.get('yes_price_cents', 0)}c")
                print(f"      NO: {opp.get('no_bid', 0)}c/{opp.get('no_price_cents', 0)}c")
                print(f"      📊 {opp.get('title', '')[:60]}")
        
        return opportunities
        
    except Exception as e:
        log_event("crypto_scan_error", {"error": str(e)})
        print(f"❌ Crypto scan error: {e}")
        return []

# ============================================================
# TRADING FUNCTIONS
# ============================================================

def execute_crypto_arbitrage(auth, opportunity, available_balance):
    """Execute crypto arbitrage using distinct-baguette strategy."""
    ticker = opportunity["ticker"]
    
    # Check if already executed
    if ticker in executed_trades:
        log_event("duplicate_skipped", {"ticker": ticker})
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
    
    print(f"\n🎯 EXECUTING CRYPTO ARBITRAGE: {ticker}")
    print(f"   📊 Series: {opportunity.get('series', 'Unknown')}")
    print(f"   💰 Net profit per contract: ${opportunity['net_profit_per_contract']:.4f}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${opportunity['net_profit_per_contract'] * contracts:.2f}")
    
    # Place orders using the Kalshi client
    try:
        client = KalshiClient(auth)
        executor = StrategyExecutor(client)
        
        yes_price = opportunity["yes_price_cents"]
        no_price = opportunity["no_price_cents"]
        
        print(f"   📈 Placing orders at market prices: YES {yes_price}c, NO {no_price}c")
        
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
            "series": opportunity.get('series', 'unknown'),
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "contracts": contracts,
            "yes_price": yes_price,
            "no_price": no_price,
            "expected_profit": total_profit,
            "total_fees": total_fees,
            "status": "active",
            "created": dt.now().isoformat(),
            "strategy": "crypto_arbitrage",
            "spread": opportunity.get('spread', 0),
            "net_profit_per_contract": opportunity.get('net_profit_per_contract', 0)
        }
        
        positions = get_active_positions()
        positions[ticker] = position
        save_positions(positions)
        
        # Update stats
        daily_stats["total_profit"] += total_profit
        daily_stats["total_fees"] += total_fees
        daily_stats["successful_arbs"] += 1
        
        log_event("crypto_execution_success", {
            "ticker": ticker,
            "series": opportunity.get('series'),
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees,
            "yes_order_id": yes_result.get("order", {}).get("order_id"),
            "no_order_id": no_result.get("order", {}).get("order_id"),
            "strategy": "crypto_arbitrage",
            "spread": opportunity.get('spread', 0)
        })
        
        print(f"   ✅ SUCCESS: Crypto arbitrage executed!")
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
        log_event("crypto_execution_exception", {
            "ticker": ticker,
            "error": str(e)
        })
        print(f"   ❌ Crypto execution failed: {e}")
        return {"error": str(e)}

def get_current_balance(auth):
    """Get current portfolio balance."""
    try:
        client = KalshiClient(auth)
        
        # Use direct API call for balance
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
            total_balance = data.get("balance", 0)
            available = data.get("available", 0)
            
            log_event("balance_check", {
                "total_balance": total_balance, 
                "available": available,
                "using_total": True
            })
            
            return total_balance
        else:
            print(f"❌ Balance check failed: {resp.status_code}")
            return 0
            
    except Exception as e:
        print(f"❌ Balance check error: {e}")
        return 0

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_crypto_arbitrage_bot():
    """Run the crypto arbitrage bot with distinct-baguette strategy."""
    print("=" * 80)
    print("🚀 CRYPTO ARBITRAGE BOT - DISTINCT-BAGUETTE STRATEGY")
    print("💰 Replicating Successful Polymarket Strategy on Kalshi Crypto Markets")
    print("=" * 80)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    # Initialize authentication
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication
        balance = get_current_balance(auth)
        if balance == 0:
            print("❌ Authentication failed or no balance")
            return
            
        print(f"✅ Authentication successful")
        print(f"💰 Starting balance: ${balance/100:.2f}")
        print(f"🎯 Strategy: Crypto arbitrage (distinct-baguette style)")
        print(f"📊 Focus: {len(CRYPTO_SERIES)} crypto series")
        print(f"⚡ Execution speed: {SCAN_INTERVAL} seconds")
        
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
    start_time = dt.now()
    end_time = start_time + timedelta(hours=SESSION_DURATION_HOURS)
    scan_count = 0
    
    print(f"🚀 Starting crypto arbitrage trading session")
    print(f"⏰ Duration: {SESSION_DURATION_HOURS} hours")
    print(f"📊 Scan interval: {SCAN_INTERVAL} seconds")
    print(f"💰 Max contracts per trade: {MAX_CONTRACTS_PER_TRADE}")
    print(f"🎯 Min profit threshold: ${MIN_PROFIT_THRESHOLD}")
    print(f"📈 Session ends: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Crypto series: {', '.join(CRYPTO_SERIES)}")
    
    while dt.now() < end_time:
        try:
            scan_count += 1
            daily_stats["scans"] += 1
            current_time = dt.now()
            elapsed = current_time - start_time
            remaining = end_time - current_time
            
            print(f"\n{'='*60}")
            print(f"📊 Scan #{scan_count} | Elapsed: {elapsed.total_seconds()/3600:.1f}h | Remaining: {remaining.total_seconds()/3600:.1f}h")
            print(f"💰 Current balance: ${get_current_balance(auth)/100:.2f}")
            print(f"📈 Trades executed: {daily_stats['trades_executed']}")
            print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
            print(f"🚀 Crypto markets scanned: {daily_stats['crypto_markets_scanned']}")
            print(f"🎯 Active crypto markets: {daily_stats['active_crypto_markets']}")
            
            # Check daily trade limit
            if daily_stats["trades_executed"] >= MAX_DAILY_TRADES:
                print(f"🎯 Daily trade limit reached ({MAX_DAILY_TRADES})")
                time.sleep(300)  # Wait 5 minutes
                continue
            
            # Scan for crypto arbitrage opportunities
            opportunities = scan_crypto_arbitrage_opportunities(auth)
            
            if not opportunities:
                print(f"📊 No crypto arbitrage opportunities found")
            else:
                print(f"🎯 Found {len(opportunities)} crypto arbitrage opportunities")
                
                # Execute best opportunity
                best_opp = opportunities[0]
                available_balance = get_current_balance(auth)
                
                # Check concurrent positions limit
                active_positions = get_active_positions()
                active_count = len([p for p in active_positions.values() if p.get("status") == "active"])
                
                if active_count < MAX_CONCURRENT_POSITIONS:
                    result = execute_crypto_arbitrage(auth, best_opp, available_balance)
                    
                    if result and "success" in result:
                        print(f"🎉 Crypto arbitrage executed successfully!")
                    else:
                        print(f"❌ Crypto arbitrage execution failed")
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
    print(f"🏁 CRYPTO ARBITRAGE SESSION COMPLETE")
    print(f"{'='*80}")
    
    final_balance = get_current_balance(auth)
    pnl = final_balance - balance
    
    print(f"💰 Initial balance: ${balance/100:.2f}")
    print(f"💰 Final balance: ${final_balance/100:.2f}")
    print(f"📈 P&L: ${pnl/100:.2f}")
    print(f"📊 Total trades: {daily_stats['trades_executed']}")
    print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
    print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
    print(f"✅ Successful arbitrages: {daily_stats['successful_arbs']}")
    print(f"❌ Failed orders: {daily_stats['failed_orders']}")
    print(f"🚀 Crypto markets scanned: {daily_stats['crypto_markets_scanned']}")
    print(f"🎯 Active crypto markets: {daily_stats['active_crypto_markets']}")
    
    # Save final stats
    save_performance_stats()
    
    log_event("crypto_session_complete", {
        "strategy": "crypto_arbitrage",
        "duration_hours": SESSION_DURATION_HOURS,
        "starting_balance": balance,
        "ending_balance": final_balance,
        "pnl": pnl,
        "trades_executed": daily_stats["trades_executed"],
        "total_profit": daily_stats["total_profit"],
        "total_fees": daily_stats["total_fees"],
        "successful_arbs": daily_stats["successful_arbs"],
        "failed_orders": daily_stats["failed_orders"],
        "crypto_markets_scanned": daily_stats["crypto_markets_scanned"],
        "active_crypto_markets": daily_stats["active_crypto_markets"]
    })

if __name__ == "__main__":
    run_crypto_arbitrage_bot()

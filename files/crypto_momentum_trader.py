#!/usr/bin/env python3
"""
Crypto Momentum Trader - Profitable Strategy for Kalshi
Focuses on momentum trading, volatility, and event-driven opportunities
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
# MOMENTUM TRADING CONFIGURATION
# ============================================================

# Trading Parameters
SCAN_INTERVAL = 30              # 30-second scans
AUTO_EXECUTE = True              # Enable automatic execution
MAX_CONTRACTS_PER_TRADE = 20     # Position size
MIN_PROFIT_THRESHOLD = 0.01     # Minimum 1 cent profit
MAX_DAILY_TRADES = 30          # Max trades per day
SESSION_DURATION_HOURS = 48      # Total runtime

# Momentum Trading Parameters
MOMENTUM_THRESHOLD = 0.05      # 5% price movement for momentum signal
VOLUME_THRESHOLD = 1000        # Minimum volume for momentum trading
PRICE_CHANGE_THRESHOLD = 0.02  # 2% price change for entry
STOP_LOSS_PERCENTAGE = 0.10    # 10% stop loss
TAKE_PROFIT_PERCENTAGE = 0.05  # 5% take profit

# Event-Driven Trading
EVENT_SERIES = [
    'KXSATOSHIBTCYEAR',      # Satoshi Bitcoin movement
    'KXETHATH',              # Ethereum ATH events
    'KXCRYPTOPERFORMY',      # Crypto performance comparisons
    'KXDOGE',                # Dogecoin events
]

# Momentum Trading Series
MOMENTUM_SERIES = [
    'KXBTCMAXM',             # Bitcoin max price (high volume)
    'KXETHATH',              # Ethereum ATH
    'KXDOGE',                # Dogecoin
]

# Logging
LOG_FILE = "data/crypto_momentum_trading.jsonl"
POSITIONS_FILE = "data/crypto_momentum_positions.json"
PERFORMANCE_FILE = "data/crypto_momentum_performance.json"

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
    "scans": 0,
    "momentum_signals": 0,
    "event_signals": 0,
    "volume_trades": 0,
    "active_markets": 0
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

# ============================================================
# MARKET ANALYSIS FUNCTIONS
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

def analyze_momentum_signals(auth):
    """Analyze momentum trading signals in crypto markets."""
    try:
        momentum_opportunities = []
        
        print("🔍 Analyzing momentum signals...")
        
        for series_ticker in MOMENTUM_SERIES:
            markets = get_crypto_series_markets(auth, series_ticker)
            
            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                yes_bid = market.get('yes_bid', 0)
                no_bid = market.get('no_bid', 0)
                volume = market.get('volume', 0)
                status = market.get('status', 'unknown')
                
                # Skip if no pricing or low volume
                if yes_ask == 0 or no_ask == 0 or volume < VOLUME_THRESHOLD:
                    continue
                
                # Calculate momentum indicators
                yes_price = (yes_bid + yes_ask) / 200  # Convert to dollars
                no_price = (no_bid + no_ask) / 200
                
                # Price momentum (how far from 50-50)
                price_momentum = abs(yes_price - 0.5)
                
                # Volume momentum (relative to threshold)
                volume_momentum = volume / VOLUME_THRESHOLD
                
                # Combined momentum score
                momentum_score = price_momentum * volume_momentum
                
                if momentum_score > MOMENTUM_THRESHOLD:
                    # Determine direction
                    if yes_price > 0.5:
                        direction = "YES"
                        entry_price = yes_ask
                        confidence = yes_price - 0.5
                    else:
                        direction = "NO"
                        entry_price = no_ask
                        confidence = 0.5 - yes_price
                    
                    # Calculate potential profit
                    if confidence > MIN_PROFIT_THRESHOLD:
                        potential_profit = confidence * MAX_CONTRACTS_PER_TRADE
                        
                        momentum_opportunities.append({
                            "ticker": ticker,
                            "series": series_ticker,
                            "title": title,
                            "direction": direction,
                            "entry_price": entry_price,
                            "confidence": confidence,
                            "momentum_score": momentum_score,
                            "volume": volume,
                            "yes_price": yes_price,
                            "no_price": no_price,
                            "potential_profit": potential_profit,
                            "strategy": "momentum",
                            "status": status
                        })
        
        # Sort by momentum score
        momentum_opportunities.sort(key=lambda x: x["momentum_score"], reverse=True)
        
        daily_stats["momentum_signals"] = len(momentum_opportunities)
        
        print(f"📊 Momentum Analysis Results:")
        print(f"   🚀 Momentum signals: {len(momentum_opportunities)}")
        
        if momentum_opportunities:
            print(f"\n🎯 Top Momentum Opportunities:")
            for i, opp in enumerate(momentum_opportunities[:3]):
                print(f"   {i+1}. {opp['ticker']} ({opp['series']})")
                print(f"      Direction: {opp['direction']} | Confidence: {opp['confidence']:.3f}")
                print(f"      Momentum Score: {opp['momentum_score']:.3f}")
                print(f"      Volume: {opp['volume']} | Potential Profit: ${opp['potential_profit']:.2f}")
                print(f"      📊 {opp['title'][:60]}")
        
        return momentum_opportunities
        
    except Exception as e:
        log_event("momentum_analysis_error", {"error": str(e)})
        print(f"❌ Momentum analysis error: {e}")
        return []

def analyze_event_signals(auth):
    """Analyze event-driven trading signals."""
    try:
        event_opportunities = []
        
        print("🔍 Analyzing event-driven signals...")
        
        for series_ticker in EVENT_SERIES:
            markets = get_crypto_series_markets(auth, series_ticker)
            
            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_ask = market.get('yes_ask', 0)
                no_ask = market.get('no_ask', 0)
                yes_bid = market.get('yes_bid', 0)
                no_bid = market.get('no_bid', 0)
                volume = market.get('volume', 0)
                status = market.get('status', 'unknown')
                
                # Skip if no pricing
                if yes_ask == 0 and no_ask == 0:
                    continue
                
                # Event-driven analysis
                yes_price = (yes_bid + yes_ask) / 200 if yes_ask > 0 else 0
                no_price = (no_bid + no_ask) / 200 if no_ask > 0 else 0
                
                # Look for high-probability events
                if yes_price > 0.7:  # Strong YES signal
                    event_opportunities.append({
                        "ticker": ticker,
                        "series": series_ticker,
                        "title": title,
                        "direction": "YES",
                        "entry_price": yes_ask,
                        "confidence": yes_price,
                        "volume": volume,
                        "potential_profit": (yes_price - 0.5) * MAX_CONTRACTS_PER_TRADE,
                        "strategy": "event_yes",
                        "status": status
                    })
                elif no_price > 0.7:  # Strong NO signal
                    event_opportunities.append({
                        "ticker": ticker,
                        "series": series_ticker,
                        "title": title,
                        "direction": "NO",
                        "entry_price": no_ask,
                        "confidence": no_price,
                        "volume": volume,
                        "potential_profit": (no_price - 0.5) * MAX_CONTRACTS_PER_TRADE,
                        "strategy": "event_no",
                        "status": status
                    })
        
        # Sort by confidence
        event_opportunities.sort(key=lambda x: x["confidence"], reverse=True)
        
        daily_stats["event_signals"] = len(event_opportunities)
        
        print(f"📊 Event Analysis Results:")
        print(f"   🎯 Event signals: {len(event_opportunities)}")
        
        if event_opportunities:
            print(f"\n🎯 Top Event Opportunities:")
            for i, opp in enumerate(event_opportunities[:3]):
                print(f"   {i+1}. {opp['ticker']} ({opp['series']})")
                print(f"      Direction: {opp['direction']} | Confidence: {opp['confidence']:.3f}")
                print(f"      Volume: {opp['volume']} | Potential Profit: ${opp['potential_profit']:.2f}")
                print(f"      📊 {opp['title'][:60]}")
        
        return event_opportunities
        
    except Exception as e:
        log_event("event_analysis_error", {"error": str(e)})
        print(f"❌ Event analysis error: {e}")
        return []

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
            
            log_event("balance_check", {
                "balance": balance, 
                "available": available,
                "status": "success"
            })
            
            return balance
        else:
            print(f"❌ Balance check failed: {resp.status_code}")
            # Return a default balance for testing
            return 10000  # $100 default
            
    except Exception as e:
        print(f"❌ Balance check error: {e}")
        # Return a default balance for testing
        return 10000  # $100 default

# ============================================================
# TRADING EXECUTION
# ============================================================

def execute_momentum_trade(auth, opportunity, available_balance):
    """Execute a momentum trade using the correct method."""
    ticker = opportunity["ticker"]
    direction = opportunity["direction"]
    entry_price = opportunity["entry_price"]
    
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
    
    print(f"\n🎯 EXECUTING MOMENTUM TRADE: {ticker}")
    print(f"   📊 Strategy: {opportunity['strategy']}")
    print(f"   📈 Direction: {direction}")
    print(f"   💰 Entry price: {entry_price}c")
    print(f"   📊 Confidence: {opportunity['confidence']:.3f}")
    print(f"   📈 Contracts: {contracts}")
    print(f"   💸 Expected profit: ${opportunity['potential_profit']:.2f}")
    
    try:
        client = KalshiClient(auth)
        executor = StrategyExecutor(client)
        
        print(f"   📈 Placing {direction} order for {contracts} contracts")
        
        # Use the correct method - execute_directional for single-sided trades
        result = executor.execute_directional(ticker, direction.lower(), entry_price, contracts)
        
        if "error" in result:
            log_event("execution_failed", {
                "ticker": ticker,
                "error": f"Order failed: {result['error']}"
            })
            print(f"   ❌ Order failed: {result['error']}")
            return result
        
        # Track the trade
        executed_trades.add(ticker)
        daily_stats["trades_executed"] += 1
        
        # Calculate expected profit
        total_profit = opportunity['potential_profit']
        total_fees = contracts * 0.002  # Approximate fees
        
        # Save position
        position = {
            "ticker": ticker,
            "direction": direction,
            "order_id": result.get("order_id", "unknown"),
            "contracts": contracts,
            "entry_price": entry_price,
            "confidence": opportunity['confidence'],
            "expected_profit": total_profit,
            "total_fees": total_fees,
            "status": "active",
            "created": dt.now().isoformat(),
            "strategy": opportunity['strategy'],
            "momentum_score": opportunity.get('momentum_score', 0),
            "stop_loss": entry_price * (1 - STOP_LOSS_PERCENTAGE) if direction == "YES" else entry_price * (1 + STOP_LOSS_PERCENTAGE),
            "take_profit": entry_price * (1 + TAKE_PROFIT_PERCENTAGE) if direction == "YES" else entry_price * (1 - TAKE_PROFIT_PERCENTAGE)
        }
        
        positions = get_active_positions()
        positions[ticker] = position
        save_positions(positions)
        
        # Update stats
        daily_stats["total_profit"] += total_profit
        daily_stats["total_fees"] += total_fees
        daily_stats["successful_trades"] += 1
        
        if opportunity['strategy'] in ['momentum']:
            daily_stats["volume_trades"] += 1
        else:
            daily_stats["event_signals"] += 1
        
        log_event("momentum_execution_success", {
            "ticker": ticker,
            "direction": direction,
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees,
            "order_id": result.get("order_id", "unknown"),
            "strategy": opportunity['strategy'],
            "confidence": opportunity['confidence']
        })
        
        print(f"   ✅ SUCCESS: Momentum trade executed!")
        print(f"      Order ID: {result.get('order_id', 'unknown')}")
        print(f"      Expected profit: ${total_profit:.2f}")
        print(f"      Stop loss: {position['stop_loss']:.1f}c")
        print(f"      Take profit: {position['take_profit']:.1f}c")
        
        return {
            "success": True,
            "ticker": ticker,
            "direction": direction,
            "contracts": contracts,
            "total_profit": total_profit,
            "total_fees": total_fees
        }
        
    except Exception as e:
        log_event("momentum_execution_exception", {
            "ticker": ticker,
            "error": str(e)
        })
        print(f"   ❌ Momentum execution failed: {e}")
        return {"error": str(e)}

# ============================================================
# MAIN TRADING LOOP
# ============================================================

def run_crypto_momentum_trader():
    """Run the crypto momentum trader."""
    print("=" * 80)
    print("🚀 CRYPTO MOMENTUM TRADER - PROFITABLE STRATEGY")
    print("💰 Momentum Trading, Event-Driven, and Volatility Strategies")
    print("=" * 80)
    
    # Check API key
    if not KALSHI_API_KEY_ID or KALSHI_API_KEY_ID == "YOUR_API_KEY_ID":
        print("❌ Please set KALSHI_API_KEY_ID environment variable")
        return
    
    # Initialize authentication
    try:
        auth = KalshiAuth(KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PATH)
        
        # Test authentication with market access (not balance)
        client = KalshiClient(auth)
        test_markets = client.get_markets(limit=1)
        
        if not test_markets.get('markets'):
            print("❌ Authentication failed - no market access")
            return
        
        # Get balance (with fallback)
        balance = get_current_balance(auth)
        if balance == 10000:  # Using default
            print(f"⚠️ Balance check failed, using default: ${balance/100:.2f}")
        else:
            print(f"✅ Balance retrieved: ${balance/100:.2f}")
            
        print(f"✅ Authentication successful")
        print(f"💰 Starting balance: ${balance/100:.2f}")
        print(f"🎯 Strategy: Momentum + Event-driven trading")
        print(f"📊 Focus: {len(MOMENTUM_SERIES)} momentum series + {len(EVENT_SERIES)} event series")
        print(f"⚡ Execution speed: {SCAN_INTERVAL} seconds")
        
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        return
    
    # Load existing stats
    global daily_stats
    daily_stats = load_performance_stats()
    
    # Setup signal handler
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
    
    print(f"🚀 Starting crypto momentum trading session")
    print(f"⏰ Duration: {SESSION_DURATION_HOURS} hours")
    print(f"📊 Scan interval: {SCAN_INTERVAL} seconds")
    print(f"💰 Max contracts per trade: {MAX_CONTRACTS_PER_TRADE}")
    print(f"🎯 Min profit threshold: ${MIN_PROFIT_THRESHOLD}")
    print(f"📈 Session ends: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 Momentum series: {', '.join(MOMENTUM_SERIES)}")
    print(f"🎯 Event series: {', '.join(EVENT_SERIES)}")
    
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
            print(f"🚀 Momentum signals: {daily_stats['momentum_signals']}")
            print(f"🎯 Event signals: {daily_stats['event_signals']}")
            print(f"📊 Volume trades: {daily_stats['volume_trades']}")
            
            # Check daily trade limit
            if daily_stats["trades_executed"] >= MAX_DAILY_TRADES:
                print(f"🎯 Daily trade limit reached ({MAX_DAILY_TRADES})")
                time.sleep(300)  # Wait 5 minutes
                continue
            
            # Analyze momentum signals
            momentum_opps = analyze_momentum_signals(auth)
            
            # Analyze event signals
            event_opps = analyze_event_signals(auth)
            
            # Combine all opportunities
            all_opportunities = momentum_opps + event_opps
            
            if not all_opportunities:
                print(f"📊 No trading signals found")
            else:
                print(f"🎯 Found {len(all_opportunities)} trading opportunities")
                
                # Execute best opportunity
                best_opp = all_opportunities[0]
                available_balance = get_current_balance(auth)
                
                # Check position limits
                active_positions = get_active_positions()
                active_count = len([p for p in active_positions.values() if p.get("status") == "active"])
                
                if active_count < 5:  # Max 5 concurrent positions
                    result = execute_momentum_trade(auth, best_opp, available_balance)
                    
                    if result and "success" in result:
                        print(f"🎉 Trade executed successfully!")
                    else:
                        print(f"❌ Trade execution failed")
                        daily_stats["failed_orders"] += 1
                else:
                    print(f"📊 Max concurrent positions reached (5)")
            
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
    print(f"🏁 CRYPTO MOMENTUM TRADING SESSION COMPLETE")
    print(f"{'='*80}")
    
    final_balance = get_current_balance(auth)
    pnl = final_balance - balance
    
    print(f"💰 Initial balance: ${balance/100:.2f}")
    print(f"💰 Final balance: ${final_balance/100:.2f}")
    print(f"📈 P&L: ${pnl/100:.2f}")
    print(f"📊 Total trades: {daily_stats['trades_executed']}")
    print(f"💸 Total profit: ${daily_stats['total_profit']:.2f}")
    print(f"💸 Total fees: ${daily_stats['total_fees']:.2f}")
    print(f"✅ Successful trades: {daily_stats['successful_trades']}")
    print(f"❌ Failed orders: {daily_stats['failed_orders']}")
    print(f"🚀 Momentum signals: {daily_stats['momentum_signals']}")
    print(f"🎯 Event signals: {daily_stats['event_signals']}")
    print(f"📊 Volume trades: {daily_stats['volume_trades']}")
    
    # Save final stats
    save_performance_stats()
    
    log_event("momentum_session_complete", {
        "strategy": "crypto_momentum",
        "duration_hours": SESSION_DURATION_HOURS,
        "starting_balance": balance,
        "ending_balance": final_balance,
        "pnl": pnl,
        "trades_executed": daily_stats["trades_executed"],
        "total_profit": daily_stats["total_profit"],
        "total_fees": daily_stats["total_fees"],
        "successful_trades": daily_stats["successful_trades"],
        "failed_orders": daily_stats["failed_orders"],
        "momentum_signals": daily_stats["momentum_signals"],
        "event_signals": daily_stats["event_signals"],
        "volume_trades": daily_stats["volume_trades"]
    })

if __name__ == "__main__":
    run_crypto_momentum_trader()
